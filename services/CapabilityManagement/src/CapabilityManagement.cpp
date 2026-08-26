#include "PocoDDS/Capabilities/CapabilityRuntimeService.h"
#include "PocoDDS/ManagementAuth/IdentityService.h"

#include <Poco/AutoPtr.h>
#include <Poco/ClassLibrary.h>
#include <Poco/Exception.h>
#include <Poco/JSON/Array.h>
#include <Poco/JSON/Object.h>
#include <Poco/JSON/Parser.h>
#include <Poco/Net/HTTPRequest.h>
#include <Poco/Net/HTTPResponse.h>
#include <Poco/Net/HTTPServerRequest.h>
#include <Poco/Net/HTTPServerResponse.h>
#include <Poco/Net/HTTPRequestHandler.h>
#include <Poco/OSP/Bundle.h>
#include <Poco/OSP/BundleActivator.h>
#include <Poco/OSP/BundleContext.h>
#include <Poco/OSP/ServiceRef.h>
#include <Poco/OSP/ServiceRegistry.h>
#include <Poco/OSP/Web/WebRequestHandlerFactory.h>
#include <Poco/Timestamp.h>
#include <Poco/URI.h>

#include <algorithm>
#include <deque>
#include <iterator>
#include <map>
#include <mutex>
#include <optional>
#include <sstream>
#include <string>
#include <utility>

namespace PocoDDS::CapabilityManagement
{
namespace
{
constexpr const char* READ_PERMISSION = "capability.read";
constexpr const char* MANAGE_PERMISSION = "capability.manage";
constexpr const char* REQUEST_ID_HEADER = "X-PDR-Request-Id";
constexpr std::size_t MAXIMUM_BODY_BYTES = 1024 * 1024;

void prepare(Poco::Net::HTTPServerResponse& response)
{
    response.setContentType("application/json; charset=utf-8");
    response.set("Cache-Control", "no-store");
    response.set("Pragma", "no-cache");
    response.set("X-Content-Type-Options", "nosniff");
}

void send(Poco::Net::HTTPServerResponse& response,
          Poco::Net::HTTPResponse::HTTPStatus status,
          const Poco::JSON::Object& body)
{
    prepare(response);
    response.setStatus(status);
    body.stringify(response.send());
}

void sendError(Poco::Net::HTTPServerResponse& response,
               Poco::Net::HTTPResponse::HTTPStatus status,
               const std::string& code,
               const std::string& message)
{
    Poco::JSON::Object body;
    body.set("code", code);
    body.set("error", message);
    send(response, status, body);
}

std::string readBody(Poco::Net::HTTPServerRequest& request)
{
    const auto declared = request.getContentLength64();
    if (declared > static_cast<Poco::Int64>(MAXIMUM_BODY_BYTES))
        throw Poco::RangeException("Capability policy request exceeds 1 MiB");
    std::string body;
    body.reserve(declared > 0 ? static_cast<std::size_t>(declared) : 4096);
    char buffer[8192];
    while (request.stream())
    {
        request.stream().read(buffer, sizeof(buffer));
        const auto count = request.stream().gcount();
        if (count <= 0) break;
        body.append(buffer, static_cast<std::size_t>(count));
        if (body.size() > MAXIMUM_BODY_BYTES)
            throw Poco::RangeException("Capability policy request exceeds 1 MiB");
    }
    if (body.empty()) throw Poco::InvalidArgumentException("JSON request body is required");
    return body;
}

Poco::JSON::Object::Ptr parseObject(const std::string& document)
{
    Poco::JSON::Parser parser;
    return parser.parse(document).extract<Poco::JSON::Object::Ptr>();
}

std::string objectDocument(const Poco::JSON::Object::Ptr& object)
{
    if (!object) throw Poco::InvalidArgumentException("Policy object is required");
    std::ostringstream output;
    object->stringify(output);
    return output.str();
}

bool rateAllowed(const std::string& principal)
{
    static std::mutex mutex;
    static std::map<std::string, std::deque<Poco::Timestamp::TimeVal>> recent;
    const auto now = Poco::Timestamp().epochMicroseconds();
    const auto cutoff = now - 60000000;
    std::lock_guard<std::mutex> lock(mutex);
    auto& entries = recent[principal];
    while (!entries.empty() && entries.front() < cutoff) entries.pop_front();
    if (entries.size() >= 30) return false;
    entries.push_back(now);
    if (recent.size() > 256)
        for (auto iterator = recent.begin(); iterator != recent.end();)
        {
            while (!iterator->second.empty() && iterator->second.front() < cutoff)
                iterator->second.pop_front();
            if (iterator->second.empty() && iterator->first != principal)
                iterator = recent.erase(iterator);
            else ++iterator;
        }
    return true;
}

struct Authorization
{
    std::string principal;
};

std::optional<Authorization> authorize(
    const Poco::OSP::BundleContext::Ptr& context,
    Poco::Net::HTTPServerRequest& request,
    Poco::Net::HTTPServerResponse& response,
    bool manage)
{
    const auto identityRef = context->registry().findByName(
        PocoDDS::ManagementAuth::IdentityService::SERVICE_NAME);
    if (!identityRef)
    {
        sendError(response, Poco::Net::HTTPResponse::HTTP_SERVICE_UNAVAILABLE,
                  "CAPABILITY_IDENTITY_UNAVAILABLE", "Management identity service is unavailable");
        return std::nullopt;
    }
    const auto identity = identityRef->castedInstance<
        PocoDDS::ManagementAuth::IdentityService>();
    const auto authorization = request.get("Authorization", "");
    const auto matched = identity->authenticateAuthorizationHeader(authorization);
    if (!matched)
    {
        if (!manage && !identity->snapshot().required)
            return Authorization{"development-anonymous"};
        response.set("WWW-Authenticate", "Bearer realm=\"pdr-capabilities\"");
        sendError(response, Poco::Net::HTTPResponse::HTTP_UNAUTHORIZED,
                  "CAPABILITY_AUTHENTICATION_REQUIRED",
                  "A valid management Bearer token is required");
        return std::nullopt;
    }
    const bool permitted = manage ? matched->authorized(MANAGE_PERMISSION) :
        (matched->authorized(READ_PERMISSION) || matched->authorized(MANAGE_PERMISSION));
    if (!permitted)
    {
        sendError(response, Poco::Net::HTTPResponse::HTTP_FORBIDDEN,
                  "CAPABILITY_PERMISSION_DENIED",
                  std::string("Authenticated principal lacks ") +
                      (manage ? MANAGE_PERMISSION : READ_PERMISSION));
        return std::nullopt;
    }
    response.set("X-PDR-Management-Principal", matched->id);
    return Authorization{matched->id};
}

PocoDDS::Capabilities::CapabilityRuntimeService::Ptr runtime(
    const Poco::OSP::BundleContext::Ptr& context)
{
    const auto reference = context->registry().findByName(
        PocoDDS::Capabilities::CapabilityRuntimeService::SERVICE_NAME);
    if (!reference)
        throw Poco::NotFoundException("Capability runtime service is unavailable");
    return reference->castedInstance<
        PocoDDS::Capabilities::CapabilityRuntimeService>();
}

Poco::JSON::Object::Ptr policySnapshot(
    const PocoDDS::Capabilities::PolicySnapshot& snapshot)
{
    Poco::JSON::Object::Ptr result = new Poco::JSON::Object;
    result->set("generation", snapshot.generation);
    result->set("digest", snapshot.digest);
    result->set("ruleCount", static_cast<Poco::UInt64>(snapshot.ruleCount));
    result->set("defaultEffect", PocoDDS::Capabilities::effectName(snapshot.defaultEffect));
    return result;
}

Poco::JSON::Object::Ptr leaseSnapshot(
    const PocoDDS::Capabilities::DecisionLeaseSnapshot& snapshot)
{
    Poco::JSON::Object::Ptr result = new Poco::JSON::Object;
    result->set("enabled", snapshot.enabled);
    result->set("policyGeneration", snapshot.policyGeneration);
    result->set("entries", static_cast<Poco::UInt64>(snapshot.entries));
    result->set("hits", snapshot.hits);
    result->set("misses", snapshot.misses);
    result->set("issued", snapshot.issued);
    result->set("denied", snapshot.denied);
    result->set("expired", snapshot.expired);
    result->set("invalidated", snapshot.invalidated);
    result->set("evicted", snapshot.evicted);
    return result;
}

Poco::JSON::Object::Ptr persistenceSnapshot(
    const PocoDDS::Capabilities::PersistenceSnapshot& snapshot)
{
    Poco::JSON::Object::Ptr result = new Poco::JSON::Object;
    result->set("backend", "sqlite-wal-full");
    result->set("healthy", snapshot.healthy);
    result->set("recoveryRequired", snapshot.recoveryRequired);
    result->set("generation", snapshot.generation);
    result->set("digest", snapshot.digest);
    result->set("auditRecords", snapshot.auditRecords);
    result->set("requestRecords", snapshot.requestRecords);
    if (!snapshot.error.empty()) result->set("error", snapshot.error);
    return result;
}

Poco::JSON::Object::Ptr auditRecord(
    const PocoDDS::Capabilities::AuditRecord& record)
{
    Poco::JSON::Object::Ptr result = new Poco::JSON::Object;
    result->set("timestampMicroseconds", record.timestampMicroseconds);
    result->set("principal", record.request.principal);
    result->set("resourceKind",
                PocoDDS::Capabilities::resourceKindName(record.request.resourceKind));
    result->set("resource", record.request.resource);
    result->set("action", PocoDDS::Capabilities::actionName(record.request.action));
    result->set("allowed", record.decision.allowed);
    result->set("code", record.decision.code);
    result->set("matchedRuleId", record.decision.matchedRuleId);
    result->set("policyGeneration", record.decision.policyGeneration);
    result->set("policyDigest", record.decision.policyDigest);
    result->set("explanation", record.decision.explanation);
    return result;
}

class Handler final : public Poco::Net::HTTPRequestHandler
{
public:
    explicit Handler(Poco::OSP::BundleContext::Ptr context): _context(std::move(context)) {}

    void handleRequest(Poco::Net::HTTPServerRequest& request,
                       Poco::Net::HTTPServerResponse& response) override
    {
        const auto path = Poco::URI(request.getURI()).getPath();
        const bool base = path == "/api/v1/capabilities" ||
                          path == "/api/v1/capabilities/";
        const bool audit = path == "/api/v1/capabilities/audit";
        const bool validate = path == "/api/v1/capabilities/validate";
        const bool replace = path == "/api/v1/capabilities/policy";
        if (!base && !audit && !validate && !replace)
        {
            sendError(response, Poco::Net::HTTPResponse::HTTP_NOT_FOUND,
                      "CAPABILITY_ENDPOINT_NOT_FOUND", "Unknown capability endpoint");
            return;
        }

        const bool manage = validate || replace;
        const auto authorization = authorize(_context, request, response, manage);
        if (!authorization) return;
        try
        {
            if (base) status(request, response, *authorization);
            else if (audit) auditTrail(request, response, *authorization);
            else if (validate) validatePolicy(request, response, *authorization);
            else replacePolicy(request, response, *authorization);
        }
        catch (const Poco::NoPermissionException& exception)
        {
            sendError(response, Poco::Net::HTTPResponse::HTTP_FORBIDDEN,
                      "CAPABILITY_POLICY_DENIED", exception.displayText());
        }
        catch (const Poco::RangeException& exception)
        {
            sendError(response, Poco::Net::HTTPResponse::HTTP_REQUEST_ENTITY_TOO_LARGE,
                      "CAPABILITY_REQUEST_TOO_LARGE", exception.displayText());
        }
        catch (const Poco::InvalidArgumentException& exception)
        {
            const auto message = exception.displayText();
            const bool conflict = message.find("conflict") != std::string::npos ||
                                  message.find("already used") != std::string::npos;
            sendError(response, conflict ? Poco::Net::HTTPResponse::HTTP_CONFLICT :
                                           Poco::Net::HTTPResponse::HTTP_BAD_REQUEST,
                      conflict ? "CAPABILITY_REPLACE_CONFLICT" : "CAPABILITY_REQUEST_INVALID",
                      message);
        }
        catch (const Poco::NotFoundException& exception)
        {
            sendError(response, Poco::Net::HTTPResponse::HTTP_SERVICE_UNAVAILABLE,
                      "CAPABILITY_RUNTIME_UNAVAILABLE", exception.displayText());
        }
        catch (const Poco::Exception& exception)
        {
            _context->logger().error(
                "Capability management request failed for principal " +
                authorization->principal + ": " + exception.displayText());
            sendError(response, Poco::Net::HTTPResponse::HTTP_SERVICE_UNAVAILABLE,
                      "CAPABILITY_OPERATION_FAILED", "Capability operation failed closed");
        }
        catch (const std::exception& exception)
        {
            _context->logger().error(
                "Capability management request failed for principal " +
                authorization->principal + ": " + exception.what());
            sendError(response, Poco::Net::HTTPResponse::HTTP_BAD_REQUEST,
                      "CAPABILITY_REQUEST_INVALID", "Invalid capability request");
        }
    }

private:
    void status(Poco::Net::HTTPServerRequest& request,
                Poco::Net::HTTPServerResponse& response,
                const Authorization& authorization)
    {
        if (request.getMethod() != Poco::Net::HTTPRequest::HTTP_GET)
        {
            response.set("Allow", "GET");
            sendError(response, Poco::Net::HTTPResponse::HTTP_METHOD_NOT_ALLOWED,
                      "CAPABILITY_METHOD_NOT_ALLOWED", "Status endpoint only supports GET");
            return;
        }
        const auto service = runtime(_context);
        Poco::JSON::Object body;
        body.set("schemaVersion", 1);
        body.set("principal", authorization.principal);
        body.set("actorSource", "authenticated-principal");
        body.set("anonymousWriteAllowed", false);
        body.set("policy", policySnapshot(service->snapshot()));
        body.set("persistence", persistenceSnapshot(service->persistence()));
        body.set("leases", leaseSnapshot(service->leases()));
        send(response, Poco::Net::HTTPResponse::HTTP_OK, body);
    }

    void auditTrail(Poco::Net::HTTPServerRequest& request,
                    Poco::Net::HTTPServerResponse& response,
                    const Authorization& authorization)
    {
        if (request.getMethod() != Poco::Net::HTTPRequest::HTTP_GET)
        {
            response.set("Allow", "GET");
            sendError(response, Poco::Net::HTTPResponse::HTTP_METHOD_NOT_ALLOWED,
                      "CAPABILITY_METHOD_NOT_ALLOWED", "Audit endpoint only supports GET");
            return;
        }
        std::size_t limit = 100;
        for (const auto& parameter : Poco::URI(request.getURI()).getQueryParameters())
            if (parameter.first == "limit")
            {
                std::size_t parsed = 0;
                const auto value = std::stoul(parameter.second, &parsed);
                if (parsed != parameter.second.size() || value == 0 || value > 100)
                    throw Poco::InvalidArgumentException("Audit limit must contain 1..100");
                limit = value;
            }
        const auto records = runtime(_context)->audit(limit);
        Poco::JSON::Array::Ptr items = new Poco::JSON::Array;
        for (const auto& record : records) items->add(auditRecord(record));
        Poco::JSON::Object body;
        body.set("schemaVersion", 1);
        body.set("principal", authorization.principal);
        body.set("count", static_cast<Poco::UInt64>(records.size()));
        body.set("items", items);
        send(response, Poco::Net::HTTPResponse::HTTP_OK, body);
    }

    void validatePolicy(Poco::Net::HTTPServerRequest& request,
                        Poco::Net::HTTPServerResponse& response,
                        const Authorization& authorization)
    {
        if (request.getMethod() != Poco::Net::HTTPRequest::HTTP_POST)
        {
            response.set("Allow", "POST");
            sendError(response, Poco::Net::HTTPResponse::HTTP_METHOD_NOT_ALLOWED,
                      "CAPABILITY_METHOD_NOT_ALLOWED", "Validation endpoint only supports POST");
            return;
        }
        if (!rateAllowed(authorization.principal))
        {
            sendError(response, Poco::Net::HTTPResponse::HTTP_TOO_MANY_REQUESTS,
                      "CAPABILITY_RATE_LIMITED", "Capability management rate limit exceeded");
            return;
        }
        const auto rules = PocoDDS::Capabilities::parsePolicyDocument(readBody(request));
        Poco::JSON::Object body;
        body.set("valid", true);
        body.set("defaultEffect", "deny");
        body.set("ruleCount", static_cast<Poco::UInt64>(rules.size()));
        body.set("digest", PocoDDS::Capabilities::policyDigest(rules));
        body.set("principal", authorization.principal);
        send(response, Poco::Net::HTTPResponse::HTTP_OK, body);
    }

    void replacePolicy(Poco::Net::HTTPServerRequest& request,
                       Poco::Net::HTTPServerResponse& response,
                       const Authorization& authorization)
    {
        if (request.getMethod() != Poco::Net::HTTPRequest::HTTP_POST)
        {
            response.set("Allow", "POST");
            sendError(response, Poco::Net::HTTPResponse::HTTP_METHOD_NOT_ALLOWED,
                      "CAPABILITY_METHOD_NOT_ALLOWED", "Policy endpoint only supports POST");
            return;
        }
        if (!rateAllowed(authorization.principal))
        {
            sendError(response, Poco::Net::HTTPResponse::HTTP_TOO_MANY_REQUESTS,
                      "CAPABILITY_RATE_LIMITED", "Capability management rate limit exceeded");
            return;
        }
        const auto requestId = request.get(REQUEST_ID_HEADER, "");
        if (requestId.empty() || requestId.size() > 128)
            throw Poco::InvalidArgumentException(
                "X-PDR-Request-Id must contain 1..128 characters");
        const auto object = parseObject(readBody(request));
        if (object->has("actor"))
            throw Poco::InvalidArgumentException(
                "actor is server-derived from the authenticated principal and must not be supplied");
        for (const auto& name : object->getNames())
            if (name != "expectedGeneration" && name != "policy")
                throw Poco::InvalidArgumentException(
                    "Unknown capability replacement field", name);
        if (!object->has("expectedGeneration") || !object->has("policy"))
            throw Poco::InvalidArgumentException(
                "expectedGeneration and policy are required");
        const auto expectedGeneration = object->getValue<Poco::UInt64>("expectedGeneration");
        if (expectedGeneration == 0)
            throw Poco::InvalidArgumentException("expectedGeneration must be positive");
        const auto rules = PocoDDS::Capabilities::parsePolicyDocument(
            objectDocument(object->getObject("policy")));
        const auto result = runtime(_context)->replace(
            {requestId, authorization.principal, expectedGeneration, rules});
        Poco::JSON::Object body;
        body.set("committed", true);
        body.set("requestId", requestId);
        body.set("idempotentReplay", result.idempotentReplay);
        body.set("actor", authorization.principal);
        body.set("policy", policySnapshot(result.snapshot));
        send(response, Poco::Net::HTTPResponse::HTTP_OK, body);
    }

    Poco::OSP::BundleContext::Ptr _context;
};
} // namespace

class HandlerFactory final : public Poco::OSP::Web::WebRequestHandlerFactory
{
public:
    Poco::Net::HTTPRequestHandler* createRequestHandler(
        const Poco::Net::HTTPServerRequest&) override
    {
        return new Handler(context());
    }
};

class BundleActivator final : public Poco::OSP::BundleActivator
{
public:
    void start(Poco::OSP::BundleContext::Ptr context) override
    {
        context->logger().information(
            "Capability management API started; write actors are bound to authenticated principals.");
    }
    void stop(Poco::OSP::BundleContext::Ptr) override {}
};
} // namespace PocoDDS::CapabilityManagement

POCO_BEGIN_MANIFEST(Poco::OSP::BundleActivator)
    POCO_EXPORT_CLASS(PocoDDS::CapabilityManagement::BundleActivator)
POCO_END_MANIFEST

POCO_BEGIN_NAMED_MANIFEST(WebServer, Poco::OSP::Web::WebRequestHandlerFactory)
    POCO_EXPORT_CLASS(PocoDDS::CapabilityManagement::HandlerFactory)
POCO_END_MANIFEST
