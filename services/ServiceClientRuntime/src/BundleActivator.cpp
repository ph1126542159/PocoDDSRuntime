#include "PocoDDS/Capabilities/CapabilityRuntimeService.h"
#include "PocoDDS/Health/Health.h"
#include "PocoDDS/ManagementAuth/IdentityService.h"
#include "PocoDDS/ResourceGovernance/ManagedWorkLane.h"
#include "PocoDDS/ServiceClient/ProviderRegistry.h"
#include "PocoDDS/ServiceClient/ServiceClientRuntimeService.h"
#include "PocoDDS/ServiceClient/ServiceInvocationProvider.h"
#include "PocoDDS/ServiceDirectory/ServiceDirectoryRuntimeService.h"
#include "InvocationTraceAdapter.h"
#include "SqliteInvocationJournal.h"

#include <Poco/AutoPtr.h>
#include <Poco/ClassLibrary.h>
#include <Poco/Delegate.h>
#include <Poco/Exception.h>
#include <Poco/JSON/Array.h>
#include <Poco/JSON/Object.h>
#include <Poco/Net/HTTPRequest.h>
#include <Poco/Net/HTTPRequestHandler.h>
#include <Poco/Net/HTTPResponse.h>
#include <Poco/Net/HTTPServerRequest.h>
#include <Poco/Net/HTTPServerResponse.h>
#include <Poco/OSP/Bundle.h>
#include <Poco/OSP/BundleActivator.h>
#include <Poco/OSP/BundleContext.h>
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

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstddef>
#include <cstdint>
#include <future>
#include <memory>
#include <mutex>
#include <optional>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace PocoDDS::ServiceClient
{
namespace
{
constexpr const char* OWNER = "pdr.service.serviceClientRuntime";
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
                  "SERVICE_CLIENT_IDENTITY_UNAVAILABLE",
                  "Management identity service is unavailable");
        return std::nullopt;
    }
    const auto identity = reference->castedInstance<
        ManagementAuth::IdentityService>();
    const auto matched = identity->authenticateAuthorizationHeader(
        request.get("Authorization", ""));
    if (!matched)
    {
        if (!identity->snapshot().required) return "development-anonymous";
        response.set("WWW-Authenticate", "Bearer realm=\"pdr-service-client\"");
        sendError(response, Poco::Net::HTTPResponse::HTTP_UNAUTHORIZED,
                  "SERVICE_CLIENT_AUTHENTICATION_REQUIRED",
                  "A valid management Bearer token is required");
        return std::nullopt;
    }
    if (!matched->authorized(READ_PERMISSION))
    {
        sendError(response, Poco::Net::HTTPResponse::HTTP_FORBIDDEN,
                  "SERVICE_CLIENT_PERMISSION_DENIED",
                  "Authenticated principal lacks resource.read");
        return std::nullopt;
    }
    response.set("X-PDR-Management-Principal", matched->id);
    return matched->id;
}

Poco::JSON::Object::Ptr providerJson(const ProviderSnapshot& value)
{
    Poco::JSON::Object::Ptr result = new Poco::JSON::Object;
    result->set("providerId", value.providerId);
    result->set("protocol", value.protocol);
    result->set("accepting", value.accepting);
    result->set("active", static_cast<Poco::UInt64>(value.active));
    result->set("dispatched", value.dispatched);
    result->set("failed", value.failed);
    return result;
}

Poco::JSON::Object::Ptr circuitJson(const CircuitSnapshot& value)
{
    Poco::JSON::Object::Ptr result = new Poco::JSON::Object;
    result->set("serviceName", value.serviceName);
    result->set("instanceId", value.instanceId);
    result->set("runtimeId", value.runtimeId);
    result->set("runtimeIncarnation",
                static_cast<Poco::UInt64>(value.runtimeIncarnation));
    result->set("state", toString(value.state));
    result->set("consecutiveFailures",
                static_cast<Poco::UInt64>(value.consecutiveFailures));
    result->set("probeInFlight", value.probeInFlight);
    return result;
}

} // namespace

class RuntimeServiceImpl final : public ServiceClientRuntimeService,
                                 public Health::IHealthContributor
{
public:
    RuntimeServiceImpl(
        RuntimeOptions options,
        ServiceDirectory::ServiceDirectoryRuntimeService::Ptr directory,
        ResourceGovernance::ResourceGovernorService::Ptr governor)
        : _coordinator(std::move(options), std::move(directory),
                       std::move(governor))
    {
    }

    ProviderAttachResult attach(ServiceInvocationProvider::Ptr provider)
    {
        return _coordinator.attach(std::move(provider));
    }

    bool detach(const std::string& providerId)
    {
        return _coordinator.detach(providerId);
    }

    InvocationSubmission submit(RuntimeInvocationRequest request) override
    {
        return _coordinator.submit(std::move(request));
    }

    RuntimeSnapshot snapshot() const override
    {
        return _coordinator.snapshot();
    }

    Health::Report health() const override
    {
        const auto value = snapshot();
        if (value.resourceLane.circuit ==
            ResourceGovernance::CircuitState::open)
            return {"service-client", Health::Status::degraded,
                    "Service Client ResourceGovernor lane circuit is open",
                    "PDR-HEALTH-SERVICE-CLIENT-LANE-OPEN",
                    "Inspect Provider exceptions and cooperative execution timeouts.",
                    {OWNER}};
        if (value.invocationJournal.enabled &&
            !value.invocationJournal.healthy)
            return {"service-client", Health::Status::degraded,
                    "Service Client invocation journal is unavailable",
                    "PDR-HEALTH-SERVICE-CLIENT-JOURNAL-UNAVAILABLE",
                    "Inspect the Service Client SQLite path, free space and permissions.",
                    {OWNER}};
        return {"service-client", Health::Status::up,
                std::to_string(value.providerRegistry.providers.size()) +
                    " invocation Provider(s), " +
                    std::to_string(value.client.circuits.size()) +
                    " instance circuit(s)",
                "PDR-HEALTH-SERVICE-CLIENT-UP", "", {OWNER}};
    }

    void shutdown() noexcept
    {
        _coordinator.shutdown();
    }

private:
    RuntimeCoordinator _coordinator;
};

namespace
{
ServiceClientRuntimeService::Ptr service(
    const Poco::OSP::BundleContext::Ptr& context)
{
    const auto reference = context->registry().findByName(
        ServiceClientRuntimeService::SERVICE_NAME);
    if (!reference)
        throw Poco::NotFoundException("Service Client Runtime is unavailable");
    return reference->castedInstance<ServiceClientRuntimeService>();
}

class Handler final : public Poco::Net::HTTPRequestHandler
{
public:
    explicit Handler(Poco::OSP::BundleContext::Ptr context)
        : _context(std::move(context))
    {
    }

    void handleRequest(Poco::Net::HTTPServerRequest& request,
                       Poco::Net::HTTPServerResponse& response) override
    {
        if (Poco::URI(request.getURI()).getPath() != "/api/v1/service-client")
        {
            sendError(response, Poco::Net::HTTPResponse::HTTP_NOT_FOUND,
                      "SERVICE_CLIENT_ENDPOINT_NOT_FOUND",
                      "Unknown Service Client endpoint");
            return;
        }
        if (request.getMethod() != Poco::Net::HTTPRequest::HTTP_GET)
        {
            response.set("Allow", "GET");
            sendError(response, Poco::Net::HTTPResponse::HTTP_METHOD_NOT_ALLOWED,
                      "SERVICE_CLIENT_METHOD_NOT_ALLOWED",
                      "Service Client status only supports GET");
            return;
        }
        const auto principal = authorize(_context, request, response);
        if (!principal) return;
        try
        {
            if (!Poco::URI(request.getURI()).getQueryParameters().empty())
                throw Poco::InvalidArgumentException(
                    "Service Client status does not accept query parameters");
            const auto value = service(_context)->snapshot();
            Poco::JSON::Array::Ptr providers = new Poco::JSON::Array;
            for (const auto& provider : value.providerRegistry.providers)
                providers->add(providerJson(provider));
            Poco::JSON::Array::Ptr circuits = new Poco::JSON::Array;
            for (const auto& circuit : value.client.circuits)
                circuits->add(circuitJson(circuit));
            Poco::JSON::Object body;
            body.set("schemaVersion", 1);
            body.set("principal", *principal);
            body.set("scope", "runtime-process/service-client");
            body.set("remoteInvocation", "provider-required");
            body.set("durableDelivery", false);
            body.set("idempotencyEnabled",
                     value.invocationJournal.enabled);
            body.set("idempotencyDurable",
                     value.invocationJournal.durable);
            body.set("idempotencyHealthy",
                     value.invocationJournal.healthy);
            body.set("idempotencyBackend",
                     value.invocationJournal.backend);
            body.set("idempotencyMaximumEntries",
                     static_cast<Poco::UInt64>(
                         value.invocationJournal.maximumEntries));
            body.set("idempotencyEntries",
                     static_cast<Poco::UInt64>(
                         value.invocationJournal.entries));
            body.set("idempotencyInFlight",
                     static_cast<Poco::UInt64>(
                         value.invocationJournal.inFlight));
            body.set("idempotencyCompleted",
                     static_cast<Poco::UInt64>(
                         value.invocationJournal.completed));
            body.set("idempotencyClaims",
                     value.invocationJournal.claims);
            body.set("idempotencyReplays",
                     value.invocationJournal.replays);
            body.set("idempotencyJoined", value.idempotencyJoined);
            body.set("idempotencyConflicts",
                     value.invocationJournal.conflicts);
            body.set("idempotencyIndeterminate",
                     value.invocationJournal.indeterminate);
            body.set("idempotencyRecovered",
                     value.idempotencyRecovered);
            body.set("idempotencyCapacityRejected",
                     value.invocationJournal.capacityRejected);
            body.set("idempotencyJournalErrors",
                     value.invocationJournal.errors);
            body.set("idempotencyCoordinatorErrors",
                     value.idempotencyErrors);
            body.set("providerGeneration", value.providerRegistry.generation);
            body.set("providerCount",
                     static_cast<Poco::UInt64>(providers->size()));
            body.set("maximumProviders",
                     static_cast<Poco::UInt64>(value.maximumProviders));
            body.set("providers", providers);
            body.set("calls", value.client.calls);
            body.set("succeeded", value.client.succeeded);
            body.set("failed", value.client.failed);
            body.set("attempts", value.client.attempts);
            body.set("retries", value.client.retries);
            body.set("noRoute", value.client.noRoute);
            body.set("circuitRejected", value.client.circuitRejected);
            body.set("deadlineExceeded", value.client.deadlineExceeded);
            body.set("cancelled", value.client.cancelled);
            body.set("instanceCircuitCount",
                     static_cast<Poco::UInt64>(circuits->size()));
            body.set("instanceCircuits", circuits);
            body.set("resourceOwner", value.resourceLane.policy.owner);
            body.set("resourceCircuit",
                     ResourceGovernance::toString(value.resourceLane.circuit));
            body.set("resourceActive",
                     static_cast<Poco::UInt64>(value.resourceLane.active));
            body.set("resourcePending",
                     static_cast<Poco::UInt64>(value.resourceLane.pending));
            body.set("maximumPayloadBytes",
                     static_cast<Poco::UInt64>(value.maximumPayloadBytes));
            body.set("maximumMetadataEntries",
                     static_cast<Poco::UInt64>(value.maximumMetadataEntries));
            body.set("maximumMetadataBytes",
                     static_cast<Poco::UInt64>(value.maximumMetadataBytes));
            body.set("authorizationRequired", value.authorizationRequired);
            body.set("authorizationAllowed", value.authorizationAllowed);
            body.set("authorizationDenied", value.authorizationDenied);
            body.set("authorizationErrors", value.authorizationErrors);
            body.set("auditEnabled", value.auditEnabled);
            body.set("auditEvents", value.auditEvents);
            body.set("auditErrors", value.auditErrors);
            send(response, Poco::Net::HTTPResponse::HTTP_OK, body);
        }
        catch (const std::exception& exception)
        {
            sendError(response, Poco::Net::HTTPResponse::HTTP_BAD_REQUEST,
                      "SERVICE_CLIENT_REQUEST_INVALID", exception.what());
        }
    }

private:
    Poco::OSP::BundleContext::Ptr _context;
};
} // namespace

class ServiceClientHandlerFactory final :
    public Poco::OSP::Web::WebRequestHandlerFactory
{
public:
    Poco::Net::HTTPRequestHandler* createRequestHandler(
        const Poco::Net::HTTPServerRequest&) override
    {
        return new Handler(context());
    }
};

class ServiceClientRuntimeBundleActivator final : public Poco::OSP::BundleActivator
{
public:
    void start(Poco::OSP::BundleContext::Ptr context) override
    {
        try
        {
            _context = context;
            auto preferences = Poco::OSP::ServiceFinder::find<
                Poco::OSP::PreferencesService>(context);
            auto configuration = preferences->configuration();
            RuntimeOptions options;
            options.resourceOwner = OWNER;
            options.maximumProviders = static_cast<std::size_t>(
                configuration->getUInt(
                    "pdr.serviceClient.maximumProviders", 256));
            options.client.maximumAttempts = configuration->getUInt(
                "pdr.serviceClient.maximumAttempts", 3);
            options.client.timeout = std::chrono::milliseconds(configuration->getUInt(
                "pdr.serviceClient.timeoutMilliseconds", 5000));
            options.client.initialBackoff = std::chrono::milliseconds(
                configuration->getUInt(
                    "pdr.serviceClient.initialBackoffMilliseconds", 50));
            options.client.maximumBackoff = std::chrono::milliseconds(
                configuration->getUInt(
                    "pdr.serviceClient.maximumBackoffMilliseconds", 1000));
            options.client.backoffMultiplier = configuration->getDouble(
                "pdr.serviceClient.backoffMultiplier", 2.0);
            options.client.circuitFailureThreshold = configuration->getUInt(
                "pdr.serviceClient.circuitFailureThreshold", 3);
            options.client.circuitResetTimeout = std::chrono::milliseconds(
                configuration->getUInt(
                    "pdr.serviceClient.circuitResetMilliseconds", 5000));
            options.client.maximumCircuitEntries = configuration->getUInt(
                "pdr.serviceClient.maximumCircuitEntries", 4096);
            options.client.circuitIdleRetention = std::chrono::milliseconds(
                configuration->getUInt(
                    "pdr.serviceClient.circuitIdleRetentionMilliseconds", 600000));
            options.maximumPayloadBytes = static_cast<std::size_t>(
                configuration->getUInt64(
                    "pdr.serviceClient.maximumPayloadBytes", 1024 * 1024));
            options.maximumMetadataEntries = static_cast<std::size_t>(
                configuration->getUInt(
                    "pdr.serviceClient.maximumMetadataEntries", 64));
            options.maximumMetadataBytes = static_cast<std::size_t>(
                configuration->getUInt64(
                    "pdr.serviceClient.maximumMetadataBytes", 64 * 1024));
            if (configuration->getBool(
                    "pdr.serviceClient.idempotency.enabled", true))
            {
                Poco::Path defaultDatabase(context->persistentDirectory());
                defaultDatabase.append("service-client-invocations.sqlite");
                const auto database = configuration->getString(
                    "pdr.serviceClient.idempotency.database",
                    defaultDatabase.toString());
                const auto maximumEntries = static_cast<std::size_t>(
                    configuration->getUInt64(
                        "pdr.serviceClient.idempotency.maximumEntries",
                        10000));
                const auto retention = std::chrono::milliseconds(
                    configuration->getUInt64(
                        "pdr.serviceClient.idempotency.retentionMilliseconds",
                        86400000));
                options.invocationJournal =
                    std::make_shared<SqliteInvocationJournal>(
                        database, maximumEntries, retention);
            }
            if (configuration->getBool(
                    "pdr.serviceClient.audit.enabled", true))
            {
                _audit = std::make_shared<InvocationTraceAdapter>(
                    static_cast<std::size_t>(configuration->getUInt(
                        "pdr.serviceClient.audit.maximumActiveTraces",
                        4096)));
                options.auditSink = [audit = _audit](
                    const InvocationAuditEvent& event) {
                    audit->publish(event);
                };
            }
            options.authorizationRequired = configuration->getBool(
                "pdr.serviceClient.authorizationRequired", false);
            if (options.authorizationRequired)
            {
                options.authorizer = [context](
                    const InvocationAuthorizationRequest& request) {
                    const auto reference = context->registry().findByName(
                        Capabilities::CapabilityRuntimeService::SERVICE_NAME);
                    if (!reference)
                        throw Poco::NotFoundException(
                            "Capability Runtime is unavailable");
                    const auto capabilities = reference->castedInstance<
                        Capabilities::CapabilityRuntimeService>();
                    const auto decision = capabilities->decideLeased({
                        request.principal,
                        Capabilities::ResourceKind::service,
                        request.serviceName + "/" + request.operation,
                        Capabilities::Action::use});
                    return InvocationAuthorizationDecision{
                        decision.allowed, decision.code, decision.explanation,
                        decision.policyGeneration};
                };
            }
            auto directory = Poco::OSP::ServiceFinder::find<
                ServiceDirectory::ServiceDirectoryRuntimeService>(context);
            auto governor = Poco::OSP::ServiceFinder::find<
                ResourceGovernance::ResourceGovernorService>(context);
            const auto authorizationRequired = options.authorizationRequired;
            const auto auditEnabled = static_cast<bool>(options.auditSink);
            const auto idempotencyEnabled =
                static_cast<bool>(options.invocationJournal);
            _service = new RuntimeServiceImpl(
                std::move(options), directory, governor);

            _providerListener = context->registry().createListener(
                "pdr.serviceInvocation.provider.kind == \"runtime\"",
                Poco::delegate(this,
                    &ServiceClientRuntimeBundleActivator::onProviderRegistered),
                Poco::delegate(this,
                    &ServiceClientRuntimeBundleActivator::onProviderUnregistered));

            Poco::OSP::Properties properties;
            properties.set("pdr.bundle", context->thisBundle()->symbolicName());
            properties.set("pdr.service", "serviceClientRuntime");
            properties.set("pdr.serviceClient.remoteInvocation",
                           "provider-required");
            properties.set("pdr.serviceClient.execution",
                           "resource-governed-async");
            properties.set("pdr.serviceClient.authorization",
                           authorizationRequired
                               ? "capability-runtime-required"
                               : "disabled");
            properties.set("pdr.serviceClient.audit",
                           auditEnabled
                               ? "business-trace"
                               : "disabled");
            properties.set("pdr.serviceClient.idempotency",
                           idempotencyEnabled
                               ? "sqlite-wal-full"
                               : "disabled");
            _serviceRef = context->registry().registerService(
                ServiceClientRuntimeService::SERVICE_NAME, _service, properties);

            Poco::OSP::Properties healthProperties;
            healthProperties.set("pdr.bundle",
                                 context->thisBundle()->symbolicName());
            healthProperties.set("pdr.healthContributor", "true");
            healthProperties.set("pdr.healthContributor.component",
                                 "service-client");
            _healthRef = context->registry().registerService(
                "pdr.healthContributor.serviceClient", _service,
                healthProperties);
            context->logger().information(
                "Service Client Runtime started with dynamic invocation Providers, "
                "per-instance circuits, ResourceGovernor owner lane " +
                std::string(OWNER) + ", and invocation authorization " +
                (authorizationRequired ? "enabled" : "disabled") +
                ", audit " + (auditEnabled ? "enabled" : "disabled") +
                ", idempotency " +
                (idempotencyEnabled ? "sqlite-wal-full" : "disabled"));
        }
        catch (...)
        {
            stop(context);
            throw;
        }
    }

    void stop(Poco::OSP::BundleContext::Ptr context) override
    {
        _providerListener = nullptr;
        if (_healthRef)
        {
            try { context->registry().unregisterService(_healthRef); }
            catch (...) {}
        }
        _healthRef = nullptr;
        if (_serviceRef)
        {
            try { context->registry().unregisterService(_serviceRef); }
            catch (...) {}
        }
        _serviceRef = nullptr;
        if (_service) _service->shutdown();
        {
            std::lock_guard<std::mutex> lock(_providerMutex);
            _providers.clear();
        }
        _service = nullptr;
        _context = nullptr;
        _audit.reset();
    }

private:
    struct ProviderRef
    {
        Poco::OSP::ServiceRef::Ptr reference;
        std::string providerId;
    };

    void onProviderRegistered(const Poco::OSP::ServiceRef::Ptr& reference)
    {
        if (!_service) return;
        {
            std::lock_guard<std::mutex> lock(_providerMutex);
            if (std::any_of(_providers.begin(), _providers.end(),
                    [&](const auto& item) {
                        return item.reference->name() == reference->name();
                    }))
                return;
        }
        auto provider = reference->castedInstance<ServiceInvocationProvider>();
        const auto propertyId = reference->properties().get(
            ServiceInvocationProvider::PROPERTY_ID, "");
        const auto propertyProtocol = reference->properties().get(
            ServiceInvocationProvider::PROPERTY_PROTOCOL, "");
        if (propertyId != provider->providerId() ||
            propertyProtocol != provider->protocol())
            throw Poco::InvalidArgumentException(
                "Invocation Provider properties do not match its identity",
                reference->name());
        const auto attached = _service->attach(provider);
        if (!attached)
            throw Poco::ExistsException(
                "Invocation Provider attach rejected", attached.detail);
        std::lock_guard<std::mutex> lock(_providerMutex);
        _providers.push_back({reference, attached.providerId});
        if (_context)
            _context->logger().information(
                "Invocation Provider " + attached.providerId +
                " attached for protocol " + attached.protocol);
    }

    void onProviderUnregistered(const Poco::OSP::ServiceRef::Ptr& reference)
    {
        if (!_service) return;
        std::string providerId;
        {
            std::lock_guard<std::mutex> lock(_providerMutex);
            const auto found = std::find_if(
                _providers.begin(), _providers.end(), [&](const auto& item) {
                    return item.reference->name() == reference->name();
                });
            if (found == _providers.end()) return;
            providerId = found->providerId;
            _providers.erase(found);
        }
        _service->detach(providerId);
    }

    Poco::OSP::BundleContext::Ptr _context;
    std::shared_ptr<InvocationTraceAdapter> _audit;
    Poco::AutoPtr<RuntimeServiceImpl> _service;
    Poco::OSP::ServiceRef::Ptr _serviceRef;
    Poco::OSP::ServiceRef::Ptr _healthRef;
    Poco::OSP::ServiceListener::Ptr _providerListener;
    std::mutex _providerMutex;
    std::vector<ProviderRef> _providers;
};
} // namespace PocoDDS::ServiceClient

POCO_BEGIN_MANIFEST(Poco::OSP::BundleActivator)
    POCO_EXPORT_CLASS(PocoDDS::ServiceClient::ServiceClientRuntimeBundleActivator)
POCO_END_MANIFEST

POCO_BEGIN_NAMED_MANIFEST(WebServer, Poco::OSP::Web::WebRequestHandlerFactory)
    POCO_EXPORT_CLASS(PocoDDS::ServiceClient::ServiceClientHandlerFactory)
POCO_END_MANIFEST
