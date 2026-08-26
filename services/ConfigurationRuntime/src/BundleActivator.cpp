#include "PocoDDS/ConfigTransaction/ConfigurationRuntimeService.h"
#include "PocoDDS/ConfigTransaction/ConfigurationPreflight.h"
#include "PocoDDS/ConfigTransaction/ConfigurationParticipantCatalog.h"
#include "PocoDDS/ConfigTransaction/SqliteTransactionStore.h"
#include "PocoDDS/ConfigTransaction/TransactionEngine.h"
#include "PocoDDS/Capabilities/CapabilityRuntimeService.h"
#include "PocoDDS/Configuration/ConfigurationValidator.h"
#include "PocoDDS/ManagementAuth/IdentityService.h"
#include "PocoDDS/Health/Health.h"
#include "ParticipantAdmissionState.h"
#include "ParticipantExpectationState.h"
#include "KeyLifecycleState.h"

#include <Poco/AutoPtr.h>
#include <Poco/ClassLibrary.h>
#include <Poco/Delegate.h>
#include <Poco/Exception.h>
#include <Poco/JSON/Array.h>
#include <Poco/JSON/Object.h>
#include <Poco/JSON/Parser.h>
#include <Poco/Logger.h>
#include <Poco/Net/HTTPRequest.h>
#include <Poco/Net/HTTPResponse.h>
#include <Poco/Net/HTTPServerRequest.h>
#include <Poco/Net/HTTPServerResponse.h>
#include <Poco/Net/HTTPRequestHandler.h>
#include <Poco/OSP/Bundle.h>
#include <Poco/OSP/BundleActivator.h>
#include <Poco/OSP/BundleContext.h>
#include <Poco/OSP/BundleEvent.h>
#include <Poco/OSP/BundleEvents.h>
#include <Poco/OSP/PreferencesService.h>
#include <Poco/OSP/Properties.h>
#include <Poco/OSP/ServiceFinder.h>
#include <Poco/OSP/ServiceListener.h>
#include <Poco/OSP/ServiceRef.h>
#include <Poco/OSP/ServiceRegistry.h>
#include <Poco/OSP/Web/WebRequestHandlerFactory.h>
#include <Poco/Path.h>
#include <Poco/URI.h>
#include <Poco/Util/AbstractConfiguration.h>
#include <Poco/Util/MapConfiguration.h>

#include <algorithm>
#include <cstddef>
#include <memory>
#include <mutex>
#include <optional>
#include <sstream>
#include <string>
#include <utility>
#include <vector>

namespace PocoDDS::ConfigTransaction
{
namespace
{
constexpr const char* MANAGE_PERMISSION = "configuration.manage";
constexpr const char* REQUEST_ID_HEADER = "X-PDR-Request-Id";
constexpr std::size_t MAXIMUM_BODY_BYTES = 1024 * 1024;
constexpr const char* PARTICIPANT_DECLARATION_RESOURCE =
    "configuration-participants.json";
constexpr const char* KEY_LIFECYCLE_RESOURCE =
    "configuration-key-lifecycle.json";
#ifndef PDR_RUNTIME_VERSION
#define PDR_RUNTIME_VERSION "0.1.0"
#endif

class KeyLifecycleRuntimeService final : public Poco::OSP::Service
{
public:
    using Ptr = Poco::AutoPtr<KeyLifecycleRuntimeService>;
    static constexpr const char* SERVICE_NAME =
        "pdr.service.configurationKeyLifecycleRuntime";

    explicit KeyLifecycleRuntimeService(std::shared_ptr<KeyLifecycleState> state)
        : _state(std::move(state)) {}

    KeyLifecycleSnapshot snapshot() const { return _state->snapshot(); }

    const std::type_info& type() const override
    {
        return typeid(KeyLifecycleRuntimeService);
    }

    bool isA(const std::type_info& other) const override
    {
        return std::string(other.name()) == typeid(KeyLifecycleRuntimeService).name() ||
               Poco::OSP::Service::isA(other);
    }

private:
    std::shared_ptr<KeyLifecycleState> _state;
};

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
               const std::string& code, const std::string& message)
{
    Poco::JSON::Object body;
    body.set("code", code);
    body.set("error", message);
    send(response, status, body);
}

std::optional<std::string> authorize(
    const Poco::OSP::BundleContext::Ptr& context,
    Poco::Net::HTTPServerRequest& request,
    Poco::Net::HTTPServerResponse& response)
{
    const auto reference = context->registry().findByName(
        ManagementAuth::IdentityService::SERVICE_NAME);
    if (!reference)
    {
        sendError(response, Poco::Net::HTTPResponse::HTTP_SERVICE_UNAVAILABLE,
                  "CONFIGURATION_IDENTITY_UNAVAILABLE",
                  "Management identity service is unavailable");
        return std::nullopt;
    }
    const auto identity = reference->castedInstance<ManagementAuth::IdentityService>();
    const auto matched = identity->authenticateAuthorizationHeader(
        request.get("Authorization", ""));
    if (!matched)
    {
        response.set("WWW-Authenticate", "Bearer realm=\"pdr-configuration\"");
        sendError(response, Poco::Net::HTTPResponse::HTTP_UNAUTHORIZED,
                  "CONFIGURATION_AUTHENTICATION_REQUIRED",
                  "A valid management Bearer token is required");
        return std::nullopt;
    }
    if (!matched->authorized(MANAGE_PERMISSION))
    {
        sendError(response, Poco::Net::HTTPResponse::HTTP_FORBIDDEN,
                  "CONFIGURATION_PERMISSION_DENIED",
                  "Authenticated principal lacks configuration.manage");
        return std::nullopt;
    }
    response.set("X-PDR-Management-Principal", matched->id);
    return matched->id;
}

std::string readBody(Poco::Net::HTTPServerRequest& request)
{
    const auto declared = request.getContentLength64();
    if (declared > static_cast<Poco::Int64>(MAXIMUM_BODY_BYTES))
        throw Poco::RangeException("Configuration request exceeds 1 MiB");
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
            throw Poco::RangeException("Configuration request exceeds 1 MiB");
    }
    if (body.empty()) throw Poco::InvalidArgumentException("JSON request body is required");
    return body;
}

Poco::JSON::Array::Ptr strings(const std::vector<std::string>& values)
{
    Poco::JSON::Array::Ptr result = new Poco::JSON::Array;
    for (const auto& value : values) result->add(value);
    return result;
}

Poco::JSON::Object::Ptr transactionObject(const TransactionSummary& summary)
{
    Poco::JSON::Object::Ptr result = new Poco::JSON::Object;
    result->set("transactionId", summary.id);
    result->set("requestId", summary.requestId);
    result->set("principal", summary.principal);
    result->set("status", statusName(summary.status));
    result->set("previousGeneration", summary.previousGeneration);
    result->set("candidateGeneration", summary.candidateGeneration);
    result->set("candidateDigest", summary.candidateDigest);
    result->set("changedKeys", strings(summary.changedKeys));
    result->set("participants", strings(summary.participants));
    result->set("errorCode", summary.errorCode);
    result->set("errorMessage", summary.errorMessage);
    result->set("createdMicroseconds", summary.createdMicroseconds);
    result->set("updatedMicroseconds", summary.updatedMicroseconds);
    return result;
}

Poco::JSON::Object::Ptr applyObject(const ApplyResult& applied)
{
    Poco::JSON::Object::Ptr result = new Poco::JSON::Object;
    result->set("transactionId", applied.transactionId);
    result->set("status", statusName(applied.status));
    result->set("generation", applied.snapshot.generation);
    result->set("digest", applied.snapshot.digest);
    result->set("changedKeys", strings(applied.changedKeys));
    result->set("participants", strings(applied.participants));
    result->set("errorCode", applied.errorCode);
    result->set("errorMessage", applied.errorMessage);
    result->set("idempotentReplay", applied.idempotentReplay);
    result->set("rolledBack", applied.rolledBack);
    return result;
}

Poco::JSON::Object::Ptr preflightObject(
    const ConfigurationPreflightResult& preflight)
{
    Poco::JSON::Object::Ptr result = new Poco::JSON::Object;
    result->set("preflightId", preflight.preflightId);
    result->set("accepted", preflight.accepted);
    result->set("changed", preflight.changed);
    result->set("expectedGeneration", preflight.expectedGeneration);
    result->set("observedGeneration", preflight.observedGeneration);
    result->set("candidateGeneration", preflight.candidateGeneration);
    result->set("candidateDigest", preflight.candidateDigest);
    result->set("changedKeys", strings(preflight.changedKeys));
    result->set("participants", strings(preflight.participants));
    result->set("errorCode", preflight.errorCode);
    result->set("errorMessage", preflight.errorMessage);
    return result;
}

Poco::JSON::Object::Ptr participantCatalogObject(
    const ConfigurationParticipantCatalogSnapshot& catalog,
    const ConfigurationParticipantAdmissionSnapshot& admission,
    const ConfigurationParticipantExpectationSnapshot& expectations,
    const KeyLifecycleSnapshot& keyLifecycles,
    const std::string& principal)
{
    Poco::JSON::Array::Ptr participants = new Poco::JSON::Array;
    for (const auto& participant : catalog.participants)
    {
        Poco::JSON::Object::Ptr item = new Poco::JSON::Object;
        item->set("id", participant.id);
        item->set("ownedPrefixes", strings(participant.ownedPrefixes));
        item->set("after", strings(participant.after));
        item->set("unresolvedAfter", strings(participant.unresolvedAfter));
        item->set("registrationGeneration",
                  participant.registrationGeneration);
        participants->add(item);
    }
    Poco::JSON::Array::Ptr rejectedParticipants = new Poco::JSON::Array;
    for (const auto& failure : admission.rejectedParticipants)
    {
        Poco::JSON::Object::Ptr item = new Poco::JSON::Object;
        item->set("participantId", failure.participantId);
        item->set("code", failure.code);
        item->set("observationGeneration", failure.observationGeneration);
        rejectedParticipants->add(item);
    }
    Poco::JSON::Array::Ptr declaredParticipants = new Poco::JSON::Array;
    for (const auto& expectation : expectations.expectations)
    {
        Poco::JSON::Object::Ptr item = new Poco::JSON::Object;
        item->set("owner", expectation.owner);
        item->set("id", expectation.id);
        item->set("serviceName", expectation.serviceName);
        item->set("ownerActive", expectation.ownerActive);
        item->set("status", expectation.status);
        item->set("code", expectation.code);
        declaredParticipants->add(item);
    }
    Poco::JSON::Array::Ptr declarationIssues = new Poco::JSON::Array;
    for (const auto& issue : expectations.issues)
    {
        Poco::JSON::Object::Ptr item = new Poco::JSON::Object;
        item->set("owner", issue.owner);
        item->set("code", issue.code);
        declarationIssues->add(item);
    }
    Poco::JSON::Array::Ptr lifecycleEntries = new Poco::JSON::Array;
    for (const auto& entry : keyLifecycles.entries)
    {
        Poco::JSON::Object::Ptr item = new Poco::JSON::Object;
        item->set("owner", entry.owner);
        item->set("ownerActive", entry.ownerActive);
        item->set("id", entry.id);
        item->set("participantId", entry.participantId);
        item->set("operation", entry.operation);
        item->set("sourceKey", entry.sourceKey);
        if (entry.replacementKey.empty())
            item->set("replacementKey", Poco::Dynamic::Var());
        else
            item->set("replacementKey", entry.replacementKey);
        item->set("deprecatedSince", entry.deprecatedSince);
        item->set("removalAllowedFrom", entry.removalAllowedFrom);
        item->set("status", entry.status);
        item->set("code", entry.code);
        lifecycleEntries->add(item);
    }
    Poco::JSON::Array::Ptr lifecycleIssues = new Poco::JSON::Array;
    for (const auto& issue : keyLifecycles.issues)
    {
        Poco::JSON::Object::Ptr item = new Poco::JSON::Object;
        item->set("owner", issue.owner);
        item->set("code", issue.code);
        item->set("blocking", issue.blocking);
        lifecycleIssues->add(item);
    }
    Poco::JSON::Object::Ptr result = new Poco::JSON::Object;
    result->set("schemaVersion", 4);
    result->set("principal", principal);
    result->set("scope",
                "runtime-process/transactional-configuration-participants");
    result->set("generation", catalog.generation);
    result->set("digest", catalog.digest);
    result->set("participantCount", catalog.participants.size());
    result->set("participants", participants);
    result->set("admissionGeneration", admission.generation);
    result->set("rejectedCount", admission.rejectedParticipants.size());
    result->set("admissionOverflow", admission.overflow);
    result->set("rejectedParticipants", rejectedParticipants);
    result->set("expectationGeneration", expectations.generation);
    result->set("expectationsReady", expectations.ready);
    result->set("declaredParticipantCount", expectations.expectations.size());
    result->set("declaredParticipants", declaredParticipants);
    result->set("declarationIssueCount", expectations.issues.size());
    result->set("declarationIssues", declarationIssues);
    result->set("keyLifecycleGeneration", keyLifecycles.generation);
    result->set("keyLifecyclesReady", keyLifecycles.ready);
    result->set("keyLifecycleDeclarationCount", keyLifecycles.declarationCount);
    result->set("keyLifecycleEntryCount", keyLifecycles.entries.size());
    result->set("keyLifecycles", lifecycleEntries);
    result->set("keyLifecycleIssueCount", keyLifecycles.issues.size());
    result->set("keyLifecycleIssues", lifecycleIssues);
    return result;
}

class LoggingParticipant final : public ConfigurationParticipantService
{
public:
    ParticipantDescriptor descriptor() const override
    {
        return {"runtime-logging", {"logging.loggers.root.level"}, {}};
    }

    ParticipantResult preflight(const Context& context) override
    {
        const auto found = context.candidate.values.find("logging.loggers.root.level");
        if (found == context.candidate.values.end())
            return ParticipantResult::rejected("missing-level", "root logging level is required");
        return ParticipantResult::accepted();
    }

    ParticipantResult commit(const Context& context) override
    {
        Poco::Logger::root().setLevel(
            context.candidate.values.at("logging.loggers.root.level"));
        return ParticipantResult::accepted();
    }

    ParticipantResult rollback(const Context& context) override
    {
        const auto found = context.previous.values.find("logging.loggers.root.level");
        if (found != context.previous.values.end()) Poco::Logger::root().setLevel(found->second);
        return ParticipantResult::accepted();
    }
};
} // namespace

namespace
{
ConfigurationRuntimeService::Ptr runtime(
    const Poco::OSP::BundleContext::Ptr& context)
{
    const auto reference = context->registry().findByName(
        ConfigurationRuntimeService::SERVICE_NAME);
    if (!reference)
        throw Poco::NotFoundException("Configuration runtime service is unavailable");
    return reference->castedInstance<ConfigurationRuntimeService>();
}

ConfigurationPreflightRuntimeService::Ptr preflightRuntime(
    const Poco::OSP::BundleContext::Ptr& context)
{
    const auto reference = context->registry().findByName(
        ConfigurationPreflightRuntimeService::SERVICE_NAME);
    if (!reference)
        throw Poco::NotFoundException(
            "Configuration preflight runtime service is unavailable");
    return reference->castedInstance<ConfigurationPreflightRuntimeService>();
}

ConfigurationParticipantCatalogRuntimeService::Ptr participantCatalogRuntime(
    const Poco::OSP::BundleContext::Ptr& context)
{
    const auto reference = context->registry().findByName(
        ConfigurationParticipantCatalogRuntimeService::SERVICE_NAME);
    if (!reference)
        throw Poco::NotFoundException(
            "Configuration participant catalog runtime service is unavailable");
    return reference->castedInstance<
        ConfigurationParticipantCatalogRuntimeService>();
}

KeyLifecycleRuntimeService::Ptr keyLifecycleRuntime(
    const Poco::OSP::BundleContext::Ptr& context)
{
    const auto reference = context->registry().findByName(
        KeyLifecycleRuntimeService::SERVICE_NAME);
    if (!reference)
        throw Poco::NotFoundException(
            "Configuration key lifecycle runtime service is unavailable");
    return reference->castedInstance<KeyLifecycleRuntimeService>();
}

class Handler final : public Poco::Net::HTTPRequestHandler
{
public:
    explicit Handler(Poco::OSP::BundleContext::Ptr context): _context(std::move(context)) {}

    void handleRequest(Poco::Net::HTTPServerRequest& request,
                       Poco::Net::HTTPServerResponse& response) override
    {
        const auto path = Poco::URI(request.getURI()).getPath();
        const bool transactionPath = path ==
            "/api/v1/configuration-transactions";
        const bool preflightPath = path ==
            "/api/v1/configuration-transactions/preflight";
        const bool participantCatalogPath = path ==
            "/api/v1/configuration-participants";
        if (!transactionPath && !preflightPath && !participantCatalogPath)
        {
            sendError(response, Poco::Net::HTTPResponse::HTTP_NOT_FOUND,
                      "CONFIGURATION_ENDPOINT_NOT_FOUND",
                      "Unknown configuration transaction endpoint");
            return;
        }
        const auto principal = authorize(_context, request, response);
        if (!principal) return;
        try
        {
            if (participantCatalogPath)
            {
                if (request.getMethod() != Poco::Net::HTTPRequest::HTTP_GET)
                {
                    response.set("Allow", "GET");
                    sendError(response,
                              Poco::Net::HTTPResponse::HTTP_METHOD_NOT_ALLOWED,
                              "CONFIGURATION_METHOD_NOT_ALLOWED",
                              "Configuration participant catalog supports GET");
                    return;
                }
                if (!Poco::URI(request.getURI()).getQueryParameters().empty())
                    throw Poco::InvalidArgumentException(
                        "Configuration participant catalog accepts no query parameters");
                const auto catalogRuntime = participantCatalogRuntime(_context);
                const auto lifecycleRuntime = keyLifecycleRuntime(_context);
                const auto body = participantCatalogObject(
                    catalogRuntime->snapshot(), catalogRuntime->admission(),
                    catalogRuntime->expectations(), lifecycleRuntime->snapshot(),
                    *principal);
                send(response, Poco::Net::HTTPResponse::HTTP_OK, *body);
                return;
            }
            if (transactionPath &&
                request.getMethod() == Poco::Net::HTTPRequest::HTTP_GET)
            {
                std::size_t limit = 20;
                for (const auto& parameter : Poco::URI(request.getURI()).getQueryParameters())
                    if (parameter.first == "historyLimit")
                        limit = static_cast<std::size_t>(std::stoul(parameter.second));
                if (limit == 0 || limit > 100)
                    throw Poco::InvalidArgumentException(
                        "historyLimit must be between 1 and 100");
                auto service = runtime(_context);
                const auto snapshot = service->current();
                Poco::JSON::Array::Ptr history = new Poco::JSON::Array;
                for (const auto& item : service->history(limit))
                    history->add(transactionObject(item));
                Poco::JSON::Object body;
                body.set("schemaVersion", 1);
                body.set("principal", *principal);
                body.set("scope", "runtime-process/transactional-configuration");
                body.set("generation", snapshot.generation);
                body.set("digest", snapshot.digest);
                body.set("participants", strings(service->participantIds()));
                body.set("history", history);
                send(response, Poco::Net::HTTPResponse::HTTP_OK, body);
                return;
            }
            if (request.getMethod() != Poco::Net::HTTPRequest::HTTP_POST)
            {
                response.set("Allow", preflightPath ? "POST" : "GET, POST");
                sendError(response, Poco::Net::HTTPResponse::HTTP_METHOD_NOT_ALLOWED,
                          "CONFIGURATION_METHOD_NOT_ALLOWED",
                          preflightPath
                              ? "Configuration preflight endpoint supports POST"
                              : "Configuration transaction endpoint supports GET and POST");
                return;
            }

            const auto requestId = request.get(REQUEST_ID_HEADER, "");
            if (requestId.empty() || requestId.size() > 128)
                throw Poco::InvalidArgumentException(
                    "X-PDR-Request-Id must contain 1..128 characters");
            Poco::JSON::Parser parser;
            const auto object = parser.parse(readBody(request)).extract<
                Poco::JSON::Object::Ptr>();
            for (const auto& name : object->getNames())
                if (name != "expectedGeneration" && name != "changes")
                    throw Poco::InvalidArgumentException(
                        "Unknown configuration transaction field", name);
            if (!object->has("expectedGeneration") || !object->has("changes"))
                throw Poco::InvalidArgumentException(
                    "expectedGeneration and changes are required");
            const auto expectedGeneration =
                object->getValue<Poco::UInt64>("expectedGeneration");
            if (expectedGeneration == 0)
                throw Poco::InvalidArgumentException(
                    "expectedGeneration must be positive");
            const auto changes = object->getObject("changes");
            if (!changes || changes->size() == 0 || changes->size() > 128)
                throw Poco::InvalidArgumentException(
                    "changes must contain between 1 and 128 properties");
            auto service = runtime(_context);
            auto candidate = service->current().values;
            Values patch;
            for (const auto& key : changes->getNames())
            {
                const auto value = changes->get(key);
                if (!value.isString())
                    throw Poco::InvalidArgumentException(
                        "Configuration change values must be strings", key);
                const auto text = value.convert<std::string>();
                candidate[key] = text;
                patch[key] = text;
            }
            if (preflightPath)
            {
                const auto planned = preflightRuntime(_context)->preflight(
                    {requestId, expectedGeneration, std::move(candidate), *principal});
                const auto body = preflightObject(planned);
                if (planned.accepted)
                    send(response, Poco::Net::HTTPResponse::HTTP_OK, *body);
                else if (planned.errorCode == "generation-conflict")
                    send(response, Poco::Net::HTTPResponse::HTTP_CONFLICT, *body);
                else
                    send(response, Poco::Net::HTTPResponse::HTTP_UNPROCESSABLE_ENTITY,
                         *body);
                return;
            }

            const auto applied = service->apply(
                {requestId, expectedGeneration, std::move(candidate), *principal,
                 snapshotDigest(patch)});
            const auto body = applyObject(applied);
            if (applied.status == Status::committed)
                send(response, Poco::Net::HTTPResponse::HTTP_OK, *body);
            else if (applied.status == Status::preflightFailed)
                send(response, Poco::Net::HTTPResponse::HTTP_UNPROCESSABLE_ENTITY, *body);
            else if (applied.status == Status::rolledBack)
                send(response, Poco::Net::HTTPResponse::HTTP_CONFLICT, *body);
            else
                send(response, Poco::Net::HTTPResponse::HTTP_SERVICE_UNAVAILABLE, *body);
        }
        catch (const Poco::RangeException& exception)
        {
            sendError(response, Poco::Net::HTTPResponse::HTTP_REQUEST_ENTITY_TOO_LARGE,
                      "CONFIGURATION_REQUEST_TOO_LARGE", exception.displayText());
        }
        catch (const Poco::NoPermissionException& exception)
        {
            sendError(response, Poco::Net::HTTPResponse::HTTP_FORBIDDEN,
                      "CONFIGURATION_CAPABILITY_DENIED", exception.displayText());
        }
        catch (const Poco::Exception& exception)
        {
            sendError(response, Poco::Net::HTTPResponse::HTTP_BAD_REQUEST,
                      "CONFIGURATION_REQUEST_INVALID", exception.displayText());
        }
        catch (const std::exception& exception)
        {
            sendError(response, Poco::Net::HTTPResponse::HTTP_BAD_REQUEST,
                      "CONFIGURATION_REQUEST_INVALID", exception.what());
        }
    }

private:
    Poco::OSP::BundleContext::Ptr _context;
};
} // namespace

class ConfigurationRuntimeHandlerFactory final
    : public Poco::OSP::Web::WebRequestHandlerFactory
{
public:
    Poco::Net::HTTPRequestHandler* createRequestHandler(
        const Poco::Net::HTTPServerRequest&) override
    {
        return new Handler(context());
    }
};

class RuntimeServiceImpl final : public ConfigurationRuntimeService
{
public:
    RuntimeServiceImpl(std::unique_ptr<TransactionStore> store,
                       Poco::AutoPtr<Poco::OSP::PreferencesService> preferences,
                       Poco::AutoPtr<PocoDDS::Capabilities::CapabilityRuntimeService> capabilities)
        : _preferences(std::move(preferences)),
          _capabilities(std::move(capabilities)),
          _engine(std::move(store),
            {[this](const Snapshot& snapshot) {
                 Poco::AutoPtr<Poco::Util::MapConfiguration> candidate =
                     new Poco::Util::MapConfiguration;
                 for (const auto& [key, value] : snapshot.values)
                     candidate->setString(key, value);
                 PocoDDS::Configuration::ConfigurationValidator().validateOrThrow(*candidate);
             },
             [this](const Snapshot& snapshot) {
                 _preferences->replaceConfiguration(snapshot.values);
             },
             [this](const std::string& principal, const std::vector<std::string>& changedKeys) {
                 for (const auto& key : changedKeys)
                     _capabilities->require({principal,
                         PocoDDS::Capabilities::ResourceKind::configuration, key,
                         PocoDDS::Capabilities::Action::write});
             }})
    {
        Values initial = _preferences->configurationSnapshot();
        _engine.initialize(initial);
        _loggingParticipant = new LoggingParticipant;
        _loggingRegistration = _engine.attach(_loggingParticipant);
    }

    ParticipantRegistration attach(Poco::AutoPtr<ConfigurationParticipantService> participant)
    {
        auto registration = _engine.attach(std::move(participant));
        static_cast<void>(_engine.recover());
        return registration;
    }

    Snapshot current() const override { return _engine.current(); }
    ConfigurationPreflightResult preflight(
        const ConfigurationPreflightRequest& request)
    {
        return preflightConfigurationTransaction(_engine, request);
    }
    ConfigurationParticipantCatalogSnapshot participantCatalog() const
    {
        return configurationParticipantCatalog(_engine);
    }
    ApplyResult apply(const ApplyRequest& request) override { return _engine.apply(request); }
    std::vector<TransactionSummary> history(std::size_t limit) const override
    {
        return _engine.history(limit);
    }
    std::vector<std::string> participantIds() const override
    {
        return _engine.participantIds();
    }
    std::size_t recover() override { return _engine.recover(); }

private:
    Poco::AutoPtr<Poco::OSP::PreferencesService> _preferences;
    Poco::AutoPtr<PocoDDS::Capabilities::CapabilityRuntimeService> _capabilities;
    TransactionEngine _engine;
    Poco::AutoPtr<LoggingParticipant> _loggingParticipant;
    ParticipantRegistration _loggingRegistration;
};

class PreflightRuntimeServiceImpl final
    : public ConfigurationPreflightRuntimeService
{
public:
    explicit PreflightRuntimeServiceImpl(Poco::AutoPtr<RuntimeServiceImpl> runtime)
        : _runtime(std::move(runtime)) {}

    ConfigurationPreflightResult preflight(
        const ConfigurationPreflightRequest& request) override
    {
        return _runtime->preflight(request);
    }

private:
    Poco::AutoPtr<RuntimeServiceImpl> _runtime;
};

class ParticipantCatalogRuntimeServiceImpl final
    : public ConfigurationParticipantCatalogRuntimeService,
      public Health::IHealthContributor
{
public:
    explicit ParticipantCatalogRuntimeServiceImpl(
        Poco::AutoPtr<RuntimeServiceImpl> runtime,
        std::shared_ptr<ParticipantAdmissionState> admission,
        std::shared_ptr<ParticipantExpectationState> expectations,
        std::shared_ptr<KeyLifecycleState> keyLifecycles)
        : _runtime(std::move(runtime)), _admission(std::move(admission)),
          _expectations(std::move(expectations)),
          _keyLifecycles(std::move(keyLifecycles)) {}

    ConfigurationParticipantCatalogSnapshot snapshot() const override
    {
        return _runtime->participantCatalog();
    }

    ConfigurationParticipantAdmissionSnapshot admission() const override
    {
        return _admission->snapshot();
    }

    ConfigurationParticipantExpectationSnapshot expectations() const override
    {
        return _expectations->snapshot();
    }

    Health::Report health() const override
    {
        auto admission = _admission->health();
        admission.component = "configuration-participants";
        if (admission.status != Health::Status::up) return admission;
        auto expectations = _expectations->health();
        if (expectations.status != Health::Status::up) return expectations;
        auto keyLifecycles = _keyLifecycles->health();
        if (keyLifecycles.status != Health::Status::up)
        {
            keyLifecycles.component = "configuration-participants";
            return keyLifecycles;
        }
        return expectations;
    }

private:
    Poco::AutoPtr<RuntimeServiceImpl> _runtime;
    std::shared_ptr<ParticipantAdmissionState> _admission;
    std::shared_ptr<ParticipantExpectationState> _expectations;
    std::shared_ptr<KeyLifecycleState> _keyLifecycles;
};

class ConfigurationRuntimeBundleActivator final : public Poco::OSP::BundleActivator
{
public:
    void start(Poco::OSP::BundleContext::Ptr context) override
    {
        try
        {
            _context = context;
            auto preferences =
                Poco::OSP::ServiceFinder::find<Poco::OSP::PreferencesService>(context);
            auto capabilities = Poco::OSP::ServiceFinder::find<
                PocoDDS::Capabilities::CapabilityRuntimeService>(context);
            Poco::Path defaultDatabase(context->persistentDirectory());
            defaultDatabase.append("transactions.sqlite");
            const std::string database = preferences->configuration()->getString(
                "pdr.configurationRuntime.database", defaultDatabase.toString());
            _service = new RuntimeServiceImpl(
                std::make_unique<SqliteTransactionStore>(database), preferences, capabilities);
            _admissionState = std::make_shared<ParticipantAdmissionState>();
            _expectationState = std::make_shared<ParticipantExpectationState>();
            _keyLifecycleState = std::make_shared<KeyLifecycleState>();
            subscribeBundleEvents(context->events());

            _participantListener = context->registry().createListener(
                "pdr.configuration.participant.kind == \"transactional\"",
                Poco::delegate(this,
                    &ConfigurationRuntimeBundleActivator::onParticipantRegistered),
                Poco::delegate(this,
                    &ConfigurationRuntimeBundleActivator::onParticipantUnregistered));

            Poco::OSP::Properties properties;
            properties.set("pdr.service", "configurationRuntime");
            properties.set("pdr.configuration.transactional", "true");
            properties.set("pdr.bundle", context->thisBundle()->symbolicName());
            _serviceRef = context->registry().registerService(
                ConfigurationRuntimeService::SERVICE_NAME, _service, properties);
            _preflightService = new PreflightRuntimeServiceImpl(_service);
            Poco::OSP::Properties preflightProperties;
            preflightProperties.set("pdr.service", "configurationPreflightRuntime");
            preflightProperties.set("pdr.configuration.preflight", "true");
            preflightProperties.set("pdr.bundle", context->thisBundle()->symbolicName());
            _preflightServiceRef = context->registry().registerService(
                ConfigurationPreflightRuntimeService::SERVICE_NAME,
                _preflightService, preflightProperties);
            _participantCatalogService =
                new ParticipantCatalogRuntimeServiceImpl(
                    _service, _admissionState, _expectationState,
                    _keyLifecycleState);
            Poco::OSP::Properties catalogProperties;
            catalogProperties.set("pdr.service",
                                  "configurationParticipantCatalogRuntime");
            catalogProperties.set("pdr.configuration.participantCatalog", "true");
            catalogProperties.set("pdr.bundle",
                                  context->thisBundle()->symbolicName());
            _participantCatalogServiceRef = context->registry().registerService(
                ConfigurationParticipantCatalogRuntimeService::SERVICE_NAME,
                _participantCatalogService, catalogProperties);
            _keyLifecycleService = new KeyLifecycleRuntimeService(_keyLifecycleState);
            Poco::OSP::Properties lifecycleProperties;
            lifecycleProperties.set("pdr.service", "configurationKeyLifecycleRuntime");
            lifecycleProperties.set("pdr.configuration.keyLifecycle", "true");
            lifecycleProperties.set("pdr.bundle",
                                    context->thisBundle()->symbolicName());
            _keyLifecycleServiceRef = context->registry().registerService(
                KeyLifecycleRuntimeService::SERVICE_NAME,
                _keyLifecycleService, lifecycleProperties);
            Poco::OSP::Properties healthProperties;
            healthProperties.set("pdr.healthContributor", "true");
            healthProperties.set("pdr.healthContributor.component",
                                 "configuration-participants");
            healthProperties.set("pdr.bundle",
                                 context->thisBundle()->symbolicName());
            _healthServiceRef = context->registry().registerService(
                "pdr.healthContributor.configurationParticipantAdmission",
                _participantCatalogService, healthProperties);
            refreshExpectations();
            context->logger().information(
                "Transactional configuration runtime started at generation " +
                std::to_string(_service->current().generation) + " with database " + database + ".");
        }
        catch (...)
        {
            stop(context);
            throw;
        }
    }

    void stop(Poco::OSP::BundleContext::Ptr context) override
    {
        _participantListener = nullptr;
        if (_bundleEventsSubscribed) unsubscribeBundleEvents(context->events());
        if (_healthServiceRef)
        {
            try { context->registry().unregisterService(_healthServiceRef); }
            catch (...) {}
        }
        _healthServiceRef = nullptr;
        if (_participantCatalogServiceRef)
        {
            try { context->registry().unregisterService(
                _participantCatalogServiceRef); }
            catch (...) {}
        }
        _participantCatalogServiceRef = nullptr;
        _participantCatalogService = nullptr;
        if (_keyLifecycleServiceRef)
        {
            try { context->registry().unregisterService(_keyLifecycleServiceRef); }
            catch (...) {}
        }
        _keyLifecycleServiceRef = nullptr;
        _keyLifecycleService = nullptr;
        if (_preflightServiceRef)
        {
            try { context->registry().unregisterService(_preflightServiceRef); }
            catch (...) {}
        }
        _preflightServiceRef = nullptr;
        _preflightService = nullptr;
        if (_serviceRef)
        {
            try { context->registry().unregisterService(_serviceRef); }
            catch (...) {}
        }
        _serviceRef = nullptr;
        {
            std::lock_guard<std::mutex> lock(_participantMutex);
            _participants.clear();
        }
        if (_admissionState) _admissionState->reset();
        _admissionState.reset();
        if (_expectationState) _expectationState->reset();
        _expectationState.reset();
        if (_keyLifecycleState) _keyLifecycleState->reset();
        _keyLifecycleState.reset();
        _service = nullptr;
        _context = nullptr;
    }

private:
    struct ParticipantEntry
    {
        Poco::OSP::ServiceRef::Ptr reference;
        std::string id;
        ParticipantRegistration registration;
    };

    void onParticipantRegistered(const Poco::OSP::ServiceRef::Ptr& reference)
    {
        {
            std::lock_guard<std::mutex> lock(_participantMutex);
            if (!_service) return;
            if (std::any_of(_participants.begin(), _participants.end(),
                            [&](const auto& item) {
                                return item.reference->name() == reference->name();
                            })) return;
            const auto referenceKey = reference->name();
            auto participantId = reference->properties().get(
                ConfigurationParticipantService::PROPERTY_ID, "");
            auto failureCode = std::string("participant-service-invalid");
            try
            {
                auto participant = reference->castedInstance<ConfigurationParticipantService>();
                failureCode = "participant-descriptor-invalid";
                const auto descriptor = participant->descriptor();
                participantId = descriptor.id;
                const auto registeredId = reference->properties().get(
                    ConfigurationParticipantService::PROPERTY_ID, "");
                if (registeredId != descriptor.id)
                {
                    failureCode = "participant-identity-mismatch";
                    throw Poco::InvalidArgumentException(
                        "Configuration participant property/id mismatch", reference->name());
                }
                failureCode = "participant-contract-invalid";
                auto registration = _service->attach(participant);
                _participants.push_back(
                    {reference, descriptor.id, std::move(registration)});
                if (_admissionState) _admissionState->clear(referenceKey);
                if (_context)
                    _context->logger().information(
                        "Configuration participant " + descriptor.id + " attached.");
            }
            catch (const Poco::ExistsException& exception)
            {
                if (_admissionState)
                    _admissionState->recordFailure(
                        referenceKey, participantId,
                        "participant-ownership-conflict");
                logError("Configuration participant registration failed: " +
                         exception.displayText());
            }
            catch (const Poco::Exception& exception)
            {
                if (_admissionState)
                    _admissionState->recordFailure(
                        referenceKey, participantId, failureCode);
                logError("Configuration participant registration failed: " +
                         exception.displayText());
            }
            catch (const std::exception& exception)
            {
                if (_admissionState)
                    _admissionState->recordFailure(
                        referenceKey, participantId, failureCode);
                logError("Configuration participant registration failed: " +
                         std::string(exception.what()));
            }
        }
        refreshExpectations();
    }

    void onParticipantUnregistered(const Poco::OSP::ServiceRef::Ptr& reference)
    {
        {
            std::lock_guard<std::mutex> lock(_participantMutex);
            if (_admissionState) _admissionState->clear(reference->name());
            const auto found = std::find_if(
                _participants.begin(), _participants.end(),
                [&](const auto& item) {
                    return item.reference->name() == reference->name();
                });
            if (found != _participants.end())
            {
                const auto id = found->id;
                _participants.erase(found);
                if (_context) _context->logger().information(
                    "Configuration participant " + id + " detached.");
            }
        }
        refreshExpectations();
    }

    void refreshExpectations()
    {
        if (!_context || !_service || !_expectationState || !_keyLifecycleState)
            return;
        std::vector<ParticipantDeclarationDocument> documents;
        std::vector<KeyLifecycleDocument> lifecycleDocuments;
        std::vector<Poco::OSP::Bundle::Ptr> bundles;
        _context->listBundles(bundles);
        for (const auto& bundle : bundles)
        {
            try
            {
                std::unique_ptr<std::istream> stream(
                    bundle->getResource(PARTICIPANT_DECLARATION_RESOURCE));
                if (!stream) continue;
                std::string json;
                char buffer[4096];
                while (*stream && json.size() <=
                                      ParticipantExpectationState::MAXIMUM_DOCUMENT_BYTES)
                {
                    stream->read(buffer, sizeof(buffer));
                    const auto count = stream->gcount();
                    if (count <= 0) break;
                    json.append(buffer, static_cast<std::size_t>(count));
                }
                documents.push_back(
                    {bundle->symbolicName(),
                     bundle->state() == Poco::OSP::Bundle::BUNDLE_ACTIVE,
                     std::move(json)});
            }
            catch (const std::exception&)
            {
                documents.push_back(
                    {bundle->symbolicName(),
                     bundle->state() == Poco::OSP::Bundle::BUNDLE_ACTIVE,
                     "{"});
            }
        }
        for (const auto& bundle : bundles)
        {
            try
            {
                std::unique_ptr<std::istream> stream(
                    bundle->getResource(KEY_LIFECYCLE_RESOURCE));
                if (!stream) continue;
                std::string json;
                char buffer[4096];
                while (*stream && json.size() <=
                                      KeyLifecycleState::MAXIMUM_DOCUMENT_BYTES)
                {
                    stream->read(buffer, sizeof(buffer));
                    const auto count = stream->gcount();
                    if (count <= 0) break;
                    json.append(buffer, static_cast<std::size_t>(count));
                }
                lifecycleDocuments.push_back(
                    {bundle->symbolicName(),
                     bundle->state() == Poco::OSP::Bundle::BUNDLE_ACTIVE,
                     std::move(json)});
            }
            catch (const std::exception&)
            {
                lifecycleDocuments.push_back(
                    {bundle->symbolicName(),
                     bundle->state() == Poco::OSP::Bundle::BUNDLE_ACTIVE,
                     "{"});
            }
        }
        std::vector<AdmittedParticipantObservation> observations;
        {
            std::lock_guard<std::mutex> lock(_participantMutex);
            observations.reserve(_participants.size());
            for (const auto& participant : _participants)
                observations.push_back(
                    {participant.id,
                     participant.reference->properties().get("pdr.bundle", ""),
                     participant.reference->name()});
        }
        try
        {
            _expectationState->replace(
                documents, _service->participantCatalog(), observations);
            _keyLifecycleState->replace(
                lifecycleDocuments, _service->participantCatalog(), observations,
                PDR_RUNTIME_VERSION);
        }
        catch (const std::exception& exception)
        {
            logError("Configuration participant declaration refresh failed: " +
                     std::string(exception.what()));
        }
    }

    void subscribeBundleEvents(Poco::OSP::BundleEvents& events)
    {
        events.bundleInstalled += Poco::delegate(
            this, &ConfigurationRuntimeBundleActivator::onBundleChanged);
        events.bundleStarted += Poco::delegate(
            this, &ConfigurationRuntimeBundleActivator::onBundleChanged);
        events.bundleStopped += Poco::delegate(
            this, &ConfigurationRuntimeBundleActivator::onBundleChanged);
        events.bundleFailed += Poco::delegate(
            this, &ConfigurationRuntimeBundleActivator::onBundleChanged);
        events.bundleUninstalled += Poco::delegate(
            this, &ConfigurationRuntimeBundleActivator::onBundleChanged);
        _bundleEventsSubscribed = true;
    }

    void unsubscribeBundleEvents(Poco::OSP::BundleEvents& events) noexcept
    {
        try
        {
            events.bundleInstalled -= Poco::delegate(
                this, &ConfigurationRuntimeBundleActivator::onBundleChanged);
            events.bundleStarted -= Poco::delegate(
                this, &ConfigurationRuntimeBundleActivator::onBundleChanged);
            events.bundleStopped -= Poco::delegate(
                this, &ConfigurationRuntimeBundleActivator::onBundleChanged);
            events.bundleFailed -= Poco::delegate(
                this, &ConfigurationRuntimeBundleActivator::onBundleChanged);
            events.bundleUninstalled -= Poco::delegate(
                this, &ConfigurationRuntimeBundleActivator::onBundleChanged);
        }
        catch (...) {}
        _bundleEventsSubscribed = false;
    }

    void onBundleChanged(const void*, Poco::OSP::BundleEvent&)
    {
        refreshExpectations();
    }

    void logError(const std::string& message) const
    {
        if (_context) _context->logger().error(message);
    }

    Poco::OSP::BundleContext::Ptr _context;
    Poco::AutoPtr<RuntimeServiceImpl> _service;
    Poco::OSP::ServiceRef::Ptr _serviceRef;
    Poco::AutoPtr<PreflightRuntimeServiceImpl> _preflightService;
    Poco::OSP::ServiceRef::Ptr _preflightServiceRef;
    Poco::AutoPtr<ParticipantCatalogRuntimeServiceImpl> _participantCatalogService;
    Poco::OSP::ServiceRef::Ptr _participantCatalogServiceRef;
    Poco::AutoPtr<KeyLifecycleRuntimeService> _keyLifecycleService;
    Poco::OSP::ServiceRef::Ptr _keyLifecycleServiceRef;
    Poco::OSP::ServiceRef::Ptr _healthServiceRef;
    std::shared_ptr<ParticipantAdmissionState> _admissionState;
    std::shared_ptr<ParticipantExpectationState> _expectationState;
    std::shared_ptr<KeyLifecycleState> _keyLifecycleState;
    bool _bundleEventsSubscribed{false};
    Poco::OSP::ServiceListener::Ptr _participantListener;
    std::mutex _participantMutex;
    std::vector<ParticipantEntry> _participants;
};
} // namespace PocoDDS::ConfigTransaction

POCO_BEGIN_MANIFEST(Poco::OSP::BundleActivator)
    POCO_EXPORT_CLASS(PocoDDS::ConfigTransaction::ConfigurationRuntimeBundleActivator)
POCO_END_MANIFEST

POCO_BEGIN_NAMED_MANIFEST(WebServer, Poco::OSP::Web::WebRequestHandlerFactory)
    POCO_EXPORT_CLASS(PocoDDS::ConfigTransaction::ConfigurationRuntimeHandlerFactory)
POCO_END_MANIFEST
