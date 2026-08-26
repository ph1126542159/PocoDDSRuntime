#include "PocoDDS/ManagementAuth/IdentityService.h"
#include "PocoDDS/ResourceGovernance/ResourceGovernorService.h"

#include <Poco/AutoPtr.h>
#include <Poco/ClassLibrary.h>
#include <Poco/Exception.h>
#include <Poco/JSON/Array.h>
#include <Poco/JSON/Object.h>
#include <Poco/Net/HTTPRequest.h>
#include <Poco/Net/HTTPResponse.h>
#include <Poco/Net/HTTPServerRequest.h>
#include <Poco/Net/HTTPServerResponse.h>
#include <Poco/Net/HTTPRequestHandler.h>
#include <Poco/OSP/Bundle.h>
#include <Poco/OSP/BundleActivator.h>
#include <Poco/OSP/BundleContext.h>
#include <Poco/OSP/PreferencesService.h>
#include <Poco/OSP/Properties.h>
#include <Poco/OSP/ServiceFinder.h>
#include <Poco/OSP/ServiceRef.h>
#include <Poco/OSP/ServiceRegistry.h>
#include <Poco/OSP/Web/WebRequestHandlerFactory.h>
#include <Poco/URI.h>
#include <Poco/Util/AbstractConfiguration.h>

#include <chrono>
#include <optional>
#include <string>
#include <utility>
#include <vector>

namespace PocoDDS::ResourceGovernance
{
namespace
{
constexpr const char* READ_PERMISSION = "resource.read";

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

struct Authorization
{
    std::string principal;
};

std::optional<Authorization> authorize(
    const Poco::OSP::BundleContext::Ptr& context,
    Poco::Net::HTTPServerRequest& request,
    Poco::Net::HTTPServerResponse& response)
{
    const auto reference = context->registry().findByName(
        PocoDDS::ManagementAuth::IdentityService::SERVICE_NAME);
    if (!reference)
    {
        sendError(response, Poco::Net::HTTPResponse::HTTP_SERVICE_UNAVAILABLE,
                  "RESOURCE_IDENTITY_UNAVAILABLE",
                  "Management identity service is unavailable");
        return std::nullopt;
    }
    const auto identity = reference->castedInstance<
        PocoDDS::ManagementAuth::IdentityService>();
    const auto matched = identity->authenticateAuthorizationHeader(
        request.get("Authorization", ""));
    if (!matched)
    {
        if (!identity->snapshot().required)
            return Authorization{"development-anonymous"};
        response.set("WWW-Authenticate", "Bearer realm=\"pdr-resource-governance\"");
        sendError(response, Poco::Net::HTTPResponse::HTTP_UNAUTHORIZED,
                  "RESOURCE_AUTHENTICATION_REQUIRED",
                  "A valid management Bearer token is required");
        return std::nullopt;
    }
    if (!matched->authorized(READ_PERMISSION))
    {
        sendError(response, Poco::Net::HTTPResponse::HTTP_FORBIDDEN,
                  "RESOURCE_PERMISSION_DENIED",
                  "Authenticated principal lacks resource.read");
        return std::nullopt;
    }
    response.set("X-PDR-Management-Principal", matched->id);
    return Authorization{matched->id};
}

Poco::JSON::Object::Ptr snapshotObject(const Snapshot& snapshot)
{
    Poco::JSON::Object::Ptr result = new Poco::JSON::Object;
    result->set("owner", snapshot.policy.owner);
    result->set("maximumConcurrency",
                static_cast<Poco::UInt64>(snapshot.policy.maximumConcurrency));
    result->set("queueCapacity",
                static_cast<Poco::UInt64>(snapshot.policy.queueCapacity));
    result->set("queueTimeoutMilliseconds",
                static_cast<Poco::UInt64>(snapshot.policy.queueTimeout.count()));
    result->set("executionTimeoutMilliseconds",
                static_cast<Poco::UInt64>(snapshot.policy.executionTimeout.count()));
    result->set("failureThreshold",
                static_cast<Poco::UInt64>(snapshot.policy.failureThreshold));
    result->set("circuitResetMilliseconds",
                static_cast<Poco::UInt64>(snapshot.policy.circuitResetTimeout.count()));
    result->set("circuit", toString(snapshot.circuit));
    result->set("stopping", snapshot.stopping);
    result->set("active", static_cast<Poco::UInt64>(snapshot.active));
    result->set("pending", static_cast<Poco::UInt64>(snapshot.pending));
    result->set("consecutiveFailures",
                static_cast<Poco::UInt64>(snapshot.consecutiveFailures));
    result->set("submitted", snapshot.submitted);
    result->set("accepted", snapshot.accepted);
    result->set("rejectedQueueFull", snapshot.rejectedQueueFull);
    result->set("rejectedCircuitOpen", snapshot.rejectedCircuitOpen);
    result->set("queueTimedOut", snapshot.queueTimedOut);
    result->set("executionTimedOut", snapshot.executionTimedOut);
    result->set("succeeded", snapshot.succeeded);
    result->set("failed", snapshot.failed);
    result->set("cancelled", snapshot.cancelled);
    return result;
}

Policy readPolicy(const Poco::Util::AbstractConfiguration& configuration,
                  const std::string& prefix,
                  std::string owner)
{
    Policy policy;
    policy.owner = std::move(owner);
    policy.maximumConcurrency = configuration.getUInt(prefix + "maximumConcurrency", 2);
    policy.queueCapacity = configuration.getUInt(prefix + "queueCapacity", 128);
    policy.queueTimeout = std::chrono::milliseconds(
        configuration.getUInt(prefix + "queueTimeoutMilliseconds", 1000));
    policy.executionTimeout = std::chrono::milliseconds(
        configuration.getUInt(prefix + "executionTimeoutMilliseconds", 30000));
    policy.failureThreshold = configuration.getUInt(prefix + "failureThreshold", 5);
    policy.circuitResetTimeout = std::chrono::milliseconds(
        configuration.getUInt(prefix + "circuitResetMilliseconds", 10000));
    return policy;
}

class RuntimeServiceImpl final : public ResourceGovernorService
{
public:
    RuntimeServiceImpl(Policy defaultPolicy, std::vector<Policy> overrides)
        : _governor(std::move(defaultPolicy), std::move(overrides))
    {
    }

    Admission submit(const std::string& owner, WorkItem item) override
    {
        return _governor.submit(owner, std::move(item));
    }
    Snapshot snapshot(const std::string& owner) const override
    {
        return _governor.snapshot(owner);
    }
    std::vector<Snapshot> snapshots() const override
    {
        return _governor.snapshots();
    }
    void shutdown() noexcept { _governor.shutdown(ShutdownMode::cancelPending); }

private:
    ResourceGovernor _governor;
};

ResourceGovernorService::Ptr service(const Poco::OSP::BundleContext::Ptr& context)
{
    const auto reference = context->registry().findByName(
        ResourceGovernorService::SERVICE_NAME);
    if (!reference)
        throw Poco::NotFoundException("Resource governor service is unavailable");
    return reference->castedInstance<ResourceGovernorService>();
}

class Handler final : public Poco::Net::HTTPRequestHandler
{
public:
    explicit Handler(Poco::OSP::BundleContext::Ptr context): _context(std::move(context)) {}

    void handleRequest(Poco::Net::HTTPServerRequest& request,
                       Poco::Net::HTTPServerResponse& response) override
    {
        if (Poco::URI(request.getURI()).getPath() != "/api/v1/resource-governance")
        {
            sendError(response, Poco::Net::HTTPResponse::HTTP_NOT_FOUND,
                      "RESOURCE_ENDPOINT_NOT_FOUND",
                      "Unknown resource governance endpoint");
            return;
        }
        if (request.getMethod() != Poco::Net::HTTPRequest::HTTP_GET)
        {
            response.set("Allow", "GET");
            sendError(response, Poco::Net::HTTPResponse::HTTP_METHOD_NOT_ALLOWED,
                      "RESOURCE_METHOD_NOT_ALLOWED",
                      "Resource governance endpoint only supports GET");
            return;
        }
        const auto authorization = authorize(_context, request, response);
        if (!authorization) return;
        try
        {
            std::string owner;
            for (const auto& parameter : Poco::URI(request.getURI()).getQueryParameters())
                if (parameter.first == "owner") owner = parameter.second;
            const auto governor = service(_context);
            Poco::JSON::Array::Ptr lanes = new Poco::JSON::Array;
            Poco::UInt64 totalActive = 0;
            Poco::UInt64 totalPending = 0;
            if (!owner.empty())
            {
                const auto value = governor->snapshot(owner);
                totalActive = static_cast<Poco::UInt64>(value.active);
                totalPending = static_cast<Poco::UInt64>(value.pending);
                lanes->add(snapshotObject(value));
            }
            else
            {
                for (const auto& value : governor->snapshots())
                {
                    totalActive += static_cast<Poco::UInt64>(value.active);
                    totalPending += static_cast<Poco::UInt64>(value.pending);
                    lanes->add(snapshotObject(value));
                }
            }
            Poco::JSON::Object body;
            body.set("schemaVersion", 1);
            body.set("principal", authorization->principal);
            body.set("scope", "runtime-process/bundle-owner-lanes");
            body.set("cooperativeExecutionTimeout", true);
            body.set("hardThreadTermination", false);
            body.set("totalActive", totalActive);
            body.set("totalPending", totalPending);
            body.set("laneCount", static_cast<Poco::UInt64>(lanes->size()));
            body.set("lanes", lanes);
            send(response, Poco::Net::HTTPResponse::HTTP_OK, body);
        }
        catch (const Poco::Exception& exception)
        {
            _context->logger().error(
                "Resource governance status failed for principal " +
                authorization->principal + ": " + exception.displayText());
            sendError(response, Poco::Net::HTTPResponse::HTTP_SERVICE_UNAVAILABLE,
                      "RESOURCE_STATUS_UNAVAILABLE",
                      "Resource governance status is unavailable");
        }
        catch (const std::exception& exception)
        {
            _context->logger().error(
                "Resource governance status failed for principal " +
                authorization->principal + ": " + exception.what());
            sendError(response, Poco::Net::HTTPResponse::HTTP_BAD_REQUEST,
                      "RESOURCE_REQUEST_INVALID", "Invalid resource governance request");
        }
    }

private:
    Poco::OSP::BundleContext::Ptr _context;
};
} // namespace

class ResourceGovernorHandlerFactory final : public Poco::OSP::Web::WebRequestHandlerFactory
{
public:
    Poco::Net::HTTPRequestHandler* createRequestHandler(
        const Poco::Net::HTTPServerRequest&) override
    {
        return new Handler(context());
    }
};

class ResourceGovernorBundleActivator final : public Poco::OSP::BundleActivator
{
public:
    void start(Poco::OSP::BundleContext::Ptr context) override
    {
        try
        {
            auto preferences =
                Poco::OSP::ServiceFinder::find<Poco::OSP::PreferencesService>(context);
            const auto configuration = preferences->configuration();
            auto defaultPolicy = readPolicy(
                *configuration, "pdr.resourceGovernor.default.", "*");
            const auto count = configuration->getUInt(
                "pdr.resourceGovernor.overrides.count", 0);
            if (count > 128)
                throw Poco::InvalidArgumentException(
                    "pdr.resourceGovernor.overrides.count must not exceed 128");
            std::vector<Policy> overrides;
            overrides.reserve(count);
            for (unsigned index = 0; index < count; ++index)
            {
                const auto prefix = "pdr.resourceGovernor.overrides." +
                    std::to_string(index) + ".";
                overrides.push_back(readPolicy(
                    *configuration, prefix, configuration->getString(prefix + "owner")));
            }
            _service = new RuntimeServiceImpl(defaultPolicy, overrides);
            Poco::OSP::Properties properties;
            properties.set("pdr.service", "resourceGovernor");
            properties.set("pdr.resource.scope", "bundle-owner-lanes");
            properties.set("pdr.resource.default.maximumConcurrency",
                           std::to_string(defaultPolicy.maximumConcurrency));
            properties.set("pdr.resource.default.queueCapacity",
                           std::to_string(defaultPolicy.queueCapacity));
            properties.set("pdr.resource.overrideCount", std::to_string(overrides.size()));
            properties.set("pdr.bundle", context->thisBundle()->symbolicName());
            _serviceRef = context->registry().registerService(
                ResourceGovernorService::SERVICE_NAME, _service, properties);
            context->logger().information(
                "Bundle resource governor started with isolated owner lanes; " +
                std::to_string(overrides.size()) + " override(s), default concurrency " +
                std::to_string(defaultPolicy.maximumConcurrency) +
                ", default queue capacity " + std::to_string(defaultPolicy.queueCapacity) +
                ". Execution timeouts are cooperative.");
        }
        catch (...)
        {
            stop(context);
            throw;
        }
    }

    void stop(Poco::OSP::BundleContext::Ptr context) override
    {
        if (_service) _service->shutdown();
        if (_serviceRef)
        {
            try { context->registry().unregisterService(_serviceRef); }
            catch (...) {}
        }
        _serviceRef = nullptr;
        _service = nullptr;
    }

private:
    Poco::AutoPtr<RuntimeServiceImpl> _service;
    Poco::OSP::ServiceRef::Ptr _serviceRef;
};
} // namespace PocoDDS::ResourceGovernance

POCO_BEGIN_MANIFEST(Poco::OSP::BundleActivator)
    POCO_EXPORT_CLASS(PocoDDS::ResourceGovernance::ResourceGovernorBundleActivator)
POCO_END_MANIFEST

POCO_BEGIN_NAMED_MANIFEST(WebServer, Poco::OSP::Web::WebRequestHandlerFactory)
    POCO_EXPORT_CLASS(PocoDDS::ResourceGovernance::ResourceGovernorHandlerFactory)
POCO_END_MANIFEST
