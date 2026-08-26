#include "PocoDDS/Health/Health.h"
#include "PocoDDS/ManagementAuth/IdentityService.h"
#include "PocoDDS/ServiceDependency/ServiceDependencyRuntimeService.h"

#include <Poco/ClassLibrary.h>
#include <Poco/Delegate.h>
#include <Poco/Exception.h>
#include <Poco/JSON/Array.h>
#include <Poco/JSON/Object.h>
#include <Poco/JSON/Parser.h>
#include <Poco/Net/HTTPRequest.h>
#include <Poco/Net/HTTPResponse.h>
#include <Poco/Net/HTTPRequestHandler.h>
#include <Poco/Net/HTTPServerRequest.h>
#include <Poco/Net/HTTPServerResponse.h>
#include <Poco/OSP/Bundle.h>
#include <Poco/OSP/BundleActivator.h>
#include <Poco/OSP/BundleContext.h>
#include <Poco/OSP/BundleEvent.h>
#include <Poco/OSP/BundleEvents.h>
#include <Poco/OSP/BundleLifecycleGuard.h>
#include <Poco/OSP/Properties.h>
#include <Poco/OSP/ServiceFinder.h>
#include <Poco/OSP/ServiceListener.h>
#include <Poco/OSP/ServiceRef.h>
#include <Poco/OSP/ServiceRegistry.h>
#include <Poco/OSP/Web/WebRequestHandlerFactory.h>
#include <Poco/URI.h>

#include <algorithm>
#include <atomic>
#include <cctype>
#include <iterator>
#include <memory>
#include <mutex>
#include <optional>
#include <set>
#include <sstream>
#include <string>
#include <tuple>
#include <unordered_map>
#include <utility>
#include <vector>

namespace PocoDDS::ServiceDependency
{
namespace
{
constexpr const char* CONTRACT_RESOURCE = "service-contracts.json";
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
                  "SERVICE_DEPENDENCY_IDENTITY_UNAVAILABLE",
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
        response.set("WWW-Authenticate",
                     "Bearer realm=\"pdr-service-dependencies\"");
        sendError(response, Poco::Net::HTTPResponse::HTTP_UNAUTHORIZED,
                  "SERVICE_DEPENDENCY_AUTHENTICATION_REQUIRED",
                  "A valid management Bearer token is required");
        return std::nullopt;
    }
    if (!matched->authorized(READ_PERMISSION))
    {
        sendError(response, Poco::Net::HTTPResponse::HTTP_FORBIDDEN,
                  "SERVICE_DEPENDENCY_PERMISSION_DENIED",
                  "Authenticated principal lacks resource.read");
        return std::nullopt;
    }
    response.set("X-PDR-Management-Principal", matched->id);
    return Authorization{matched->id};
}

void requireKnownFields(const Poco::JSON::Object::Ptr& object,
                        const std::set<std::string>& allowed,
                        const std::string& location)
{
    for (const auto& name : object->getNames())
        if (allowed.count(name) == 0)
            throw Poco::InvalidArgumentException(
                location + " contains unknown field", name);
}

ProviderState providerState(const std::string& value)
{
    if (value == "ready") return ProviderState::ready;
    if (value == "degraded") return ProviderState::degraded;
    if (value == "unavailable") return ProviderState::unavailable;
    throw Poco::InvalidArgumentException("invalid pdr.service.readiness", value);
}

std::string bounded(std::string value, std::size_t maximum)
{
    if (value.size() > maximum) value.resize(maximum);
    return value;
}

bool validFilter(const std::string& value)
{
    return !value.empty() && value.size() <= 128 &&
           std::all_of(value.begin(), value.end(), [](unsigned char ch) {
               return std::isalnum(ch) || ch == '.' || ch == '_' || ch == '-' || ch == ':';
           });
}

class RuntimeServiceImpl final : public ServiceDependencyRuntimeService,
                                 public Health::IHealthContributor
{
public:
    explicit RuntimeServiceImpl(Poco::OSP::BundleContext::Ptr context)
        : _context(std::move(context))
    {
    }

    Snapshot snapshot() const override { return _catalog.snapshot(); }

    LifecycleDecision analyzeStart(const std::string& owner) const override
    {
        return PocoDDS::ServiceDependency::analyzeStart(snapshot(), owner);
    }

    LifecycleDecision analyzeStop(const std::string& owner) const override
    {
        return PocoDDS::ServiceDependency::analyzeStop(snapshot(), owner);
    }

    void refresh() override
    {
        std::lock_guard<std::mutex> refreshLock(_refreshMutex);
        if (_stopping.load() || !_context) return;
        std::vector<Poco::OSP::Bundle::Ptr> bundles;
        _context->listBundles(bundles);
        const auto serviceReferences = _context->registry().find("name");
        std::unordered_map<std::string, Poco::OSP::ServiceRef::Ptr> services;
        for (const auto& reference : serviceReferences)
            services.emplace(reference->name(), reference);

        std::vector<ProviderDescriptor> providers;
        std::vector<RequirementDescriptor> requirements;
        std::vector<DeclarationIssue> issues;
        std::set<std::tuple<std::string, std::string, std::string>> providerKeys;
        std::set<std::pair<std::string, std::string>> requirementKeys;
        for (const auto& bundle : bundles)
        {
            std::unique_ptr<std::istream> stream(bundle->getResource(CONTRACT_RESOURCE));
            if (!stream) continue;
            const auto owner = bundle->symbolicName();
            try
            {
                std::vector<ProviderDescriptor> bundleProviders;
                std::vector<RequirementDescriptor> bundleRequirements;
                std::set<std::tuple<std::string, std::string, std::string>>
                    bundleProviderKeys;
                std::set<std::pair<std::string, std::string>> bundleRequirementKeys;
                const auto root = Poco::JSON::Parser().parse(*stream)
                                      .extract<Poco::JSON::Object::Ptr>();
                if (!root || root->optValue<int>("schemaVersion", 0) != 1)
                    throw Poco::InvalidArgumentException(
                        "schemaVersion must equal 1");
                requireKnownFields(root, {"schemaVersion", "provides", "requires"},
                                   "contract document");
                if (!root->has("provides") || !root->has("requires"))
                    throw Poco::InvalidArgumentException(
                        "contract document requires provides and requires arrays");
                const auto provided = root->getArray("provides");
                const auto required = root->getArray("requires");
                if (!provided || !required)
                    throw Poco::InvalidArgumentException(
                        "provides and requires must be arrays");
                if (provided && provided->size() > 128)
                    throw Poco::InvalidArgumentException(
                        "provides must not exceed 128 entries");
                if (required && required->size() > 128)
                    throw Poco::InvalidArgumentException(
                        "requires must not exceed 128 entries");

                if (provided)
                {
                    for (std::size_t index = 0; index < provided->size(); ++index)
                    {
                        const auto item = provided->getObject(
                            static_cast<unsigned>(index));
                        if (!item) throw Poco::InvalidArgumentException(
                            "provider entry must be an object");
                        requireKnownFields(item,
                                           {"contract", "version", "serviceName"},
                                           "provider entry");
                        ProviderDescriptor descriptor;
                        descriptor.contract = item->optValue<std::string>(
                            "contract", "");
                        descriptor.version = item->optValue<std::string>(
                            "version", "");
                        descriptor.owner = owner;
                        descriptor.serviceName = item->optValue<std::string>(
                            "serviceName", "");
                        descriptor.state = ProviderState::unavailable;
                        descriptor.detail = "provider Bundle is not active";
                        const auto found = services.find(descriptor.serviceName);
                        if (bundle->state() == Poco::OSP::Bundle::BUNDLE_ACTIVE &&
                            found != services.end())
                        {
                            const auto registeredOwner = found->second->properties().get(
                                "pdr.bundle", "");
                            if (registeredOwner == owner)
                            {
                                descriptor.state = providerState(
                                    found->second->properties().get(
                                        "pdr.service.readiness", "ready"));
                                descriptor.detail = found->second->properties().get(
                                    "pdr.service.readiness.detail", "service registered");
                            }
                            else
                            {
                                descriptor.detail = "service registration owner mismatch";
                            }
                        }
                        else if (bundle->state() == Poco::OSP::Bundle::BUNDLE_ACTIVE)
                        {
                            descriptor.detail = "declared service is not registered";
                        }
                        const auto validation = validateProvider(descriptor);
                        if (!validation)
                            throw Poco::InvalidArgumentException(
                                "invalid provider entry", validation.message);
                        const auto key = std::make_tuple(
                            descriptor.owner, descriptor.contract,
                            descriptor.serviceName);
                        if (!bundleProviderKeys.insert(key).second)
                            throw Poco::InvalidArgumentException(
                                "duplicate provider declaration", descriptor.contract);
                        bundleProviders.push_back(std::move(descriptor));
                    }
                }

                if (required)
                {
                    for (std::size_t index = 0; index < required->size(); ++index)
                    {
                        const auto item = required->getObject(
                            static_cast<unsigned>(index));
                        if (!item) throw Poco::InvalidArgumentException(
                            "requirement entry must be an object");
                        requireKnownFields(
                            item,
                            {"contract", "versionRange", "required",
                             "minimumProviders"},
                            "requirement entry");
                        RequirementDescriptor descriptor;
                        descriptor.contract = item->optValue<std::string>(
                            "contract", "");
                        descriptor.versionRange = item->optValue<std::string>(
                            "versionRange", "");
                        descriptor.owner = owner;
                        descriptor.required = item->optValue<bool>("required", true);
                        const auto minimum = item->optValue<int>(
                            "minimumProviders", 1);
                        descriptor.minimumProviders = minimum > 0
                            ? static_cast<std::size_t>(minimum)
                            : 0;
                        descriptor.ownerActive =
                            bundle->state() == Poco::OSP::Bundle::BUNDLE_ACTIVE;
                        const auto validation = validateRequirement(descriptor);
                        if (!validation)
                            throw Poco::InvalidArgumentException(
                                "invalid requirement entry", validation.message);
                        const auto key = std::make_pair(
                            descriptor.owner, descriptor.contract);
                        if (!bundleRequirementKeys.insert(key).second)
                            throw Poco::InvalidArgumentException(
                                "duplicate requirement declaration", descriptor.contract);
                        bundleRequirements.push_back(std::move(descriptor));
                    }
                }

                auto nextProviderKeys = providerKeys;
                for (const auto& key : bundleProviderKeys)
                    if (!nextProviderKeys.insert(key).second)
                        throw Poco::InvalidArgumentException(
                            "provider declaration conflicts with another loaded Bundle");
                auto nextRequirementKeys = requirementKeys;
                for (const auto& key : bundleRequirementKeys)
                    if (!nextRequirementKeys.insert(key).second)
                        throw Poco::InvalidArgumentException(
                            "requirement declaration conflicts with another loaded Bundle");
                providerKeys = std::move(nextProviderKeys);
                requirementKeys = std::move(nextRequirementKeys);
                providers.insert(providers.end(),
                                 std::make_move_iterator(bundleProviders.begin()),
                                 std::make_move_iterator(bundleProviders.end()));
                requirements.insert(requirements.end(),
                                    std::make_move_iterator(bundleRequirements.begin()),
                                    std::make_move_iterator(bundleRequirements.end()));
            }
            catch (const Poco::Exception& exception)
            {
                issues.push_back({owner, bounded(exception.displayText(), 1024)});
            }
            catch (const std::exception& exception)
            {
                issues.push_back({owner, bounded(exception.what(), 1024)});
            }
        }
        try
        {
            if (_catalog.replace(std::move(providers), std::move(requirements),
                                 std::move(issues)))
            {
                const auto value = _catalog.snapshot();
                _context->logger().information(
                    "Service dependency model refreshed at generation " +
                    std::to_string(value.generation) + ": " +
                    std::to_string(value.providers.size()) + " provider(s), " +
                    std::to_string(value.requirements.size()) + " requirement(s), " +
                    std::to_string(value.requiredBlocked) + " required blocked.");
            }
        }
        catch (const std::exception& exception)
        {
            _context->logger().error(
                "Service dependency model replacement failed: " +
                std::string(exception.what()));
            try
            {
                _catalog.replace(
                    {}, {},
                    {{"pdr.service.serviceDependencyRuntime",
                      bounded("dependency model replacement failed: " +
                                  std::string(exception.what()),
                              1024)}});
            }
            catch (...)
            {
                _context->logger().critical(
                    "Service dependency fail-closed snapshot replacement failed");
            }
        }
    }

    Health::Report health() const override
    {
        const auto value = snapshot();
        std::vector<std::string> affected;
        for (const auto& requirement : value.requirements)
            if (requirement.descriptor.ownerActive &&
                requirement.descriptor.required && !requirement.satisfied())
                affected.push_back(requirement.descriptor.owner + ":" +
                                   requirement.descriptor.contract);
        for (const auto& issue : value.issues) affected.push_back(issue.owner);
        Health::Report report;
        report.component = "service-dependencies";
        report.status = value.ready ? Health::Status::up : Health::Status::degraded;
        report.detail = std::to_string(value.activeRequirements -
                                       value.requiredBlocked -
                                       value.optionalUnsatisfied) + "/" +
                        std::to_string(value.activeRequirements) +
                        " active requirements satisfied; " +
                        std::to_string(value.requiredBlocked) +
                        " required blocked; " +
                        std::to_string(value.optionalUnsatisfied) +
                        " optional unavailable; " +
                        std::to_string(value.inactiveRequirements) +
                        " inactive; " +
                        std::to_string(value.declarationErrors) +
                        " declaration errors";
        if (!value.ready)
        {
            report.code = value.declarationErrors > 0
                ? "PDR-HEALTH-SERVICE-CONTRACT_INVALID"
                : "PDR-HEALTH-SERVICE-DEPENDENCY_UNSATISFIED";
            report.remediation = value.declarationErrors > 0
                ? "Fix the affected Bundle service-contracts.json and restart that Bundle."
                : "Inspect provider Bundle state, service registration and contract version.";
        }
        report.affected = std::move(affected);
        return report;
    }

    void stop() noexcept
    {
        _stopping.store(true);
        std::lock_guard<std::mutex> lock(_refreshMutex);
        _context = nullptr;
    }

private:
    mutable Catalog _catalog;
    Poco::OSP::BundleContext::Ptr _context;
    std::atomic<bool> _stopping{false};
    std::mutex _refreshMutex;
};

Poco::JSON::Object::Ptr providerJson(const ProviderDescriptor& provider)
{
    Poco::JSON::Object::Ptr item = new Poco::JSON::Object;
    item->set("contract", provider.contract);
    item->set("version", provider.version);
    item->set("owner", provider.owner);
    item->set("serviceName", provider.serviceName);
    item->set("state", toString(provider.state));
    item->set("detail", provider.detail);
    return item;
}

Poco::JSON::Object::Ptr requirementJson(const RequirementSnapshot& requirement)
{
    Poco::JSON::Object::Ptr item = new Poco::JSON::Object;
    item->set("contract", requirement.descriptor.contract);
    item->set("versionRange", requirement.descriptor.versionRange);
    item->set("owner", requirement.descriptor.owner);
    item->set("required", requirement.descriptor.required);
    item->set("consumerActive", requirement.descriptor.ownerActive);
    item->set("minimumProviders",
              static_cast<Poco::UInt64>(requirement.descriptor.minimumProviders));
    item->set("status", toString(requirement.status));
    item->set("declaredProviders",
              static_cast<Poco::UInt64>(requirement.declaredProviders));
    item->set("matchingProviders",
              static_cast<Poco::UInt64>(requirement.matchingProviders));
    item->set("readyProviders",
              static_cast<Poco::UInt64>(requirement.readyProviders));
    item->set("detail", requirement.detail);
    Poco::JSON::Array::Ptr matches = new Poco::JSON::Array;
    for (const auto& match : requirement.matchedProviderServices) matches->add(match);
    item->set("matchedProviderServices", matches);
    Poco::JSON::Array::Ptr versions = new Poco::JSON::Array;
    for (const auto& version : requirement.availableVersions) versions->add(version);
    item->set("availableVersions", versions);
    return item;
}

Poco::JSON::Object::Ptr findingJson(const LifecycleFinding& finding)
{
    Poco::JSON::Object::Ptr item = new Poco::JSON::Object;
    item->set("code", finding.code);
    item->set("consumer", finding.consumer);
    item->set("contract", finding.contract);
    item->set("status", toString(finding.status));
    item->set("detail", finding.detail);
    return item;
}

Poco::JSON::Object::Ptr lifecycleJson(const LifecycleDecision& decision,
                                      const std::string& principal)
{
    Poco::JSON::Object::Ptr body = new Poco::JSON::Object;
    body->set("schemaVersion", 1);
    body->set("principal", principal);
    body->set("scope", "runtime-process/bundle-service-contracts");
    body->set("action", decision.action);
    body->set("target", decision.target);
    body->set("allowed", decision.allowed);
    body->set("detail", decision.detail);
    Poco::JSON::Array::Ptr blockers = new Poco::JSON::Array;
    for (const auto& finding : decision.blockers)
        blockers->add(findingJson(finding));
    body->set("blockerCount", static_cast<Poco::UInt64>(blockers->size()));
    body->set("blockers", blockers);
    Poco::JSON::Array::Ptr warnings = new Poco::JSON::Array;
    for (const auto& finding : decision.warnings)
        warnings->add(findingJson(finding));
    body->set("warningCount", static_cast<Poco::UInt64>(warnings->size()));
    body->set("warnings", warnings);
    Poco::JSON::Array::Ptr affected = new Poco::JSON::Array;
    for (const auto& consumer : decision.affectedConsumers) affected->add(consumer);
    body->set("affectedConsumers", affected);
    return body;
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
        const Poco::URI uri(request.getURI());
        const bool impact =
            uri.getPath() == "/api/v1/service-dependencies/impact";
        if (uri.getPath() != "/api/v1/service-dependencies" && !impact)
        {
            sendError(response, Poco::Net::HTTPResponse::HTTP_NOT_FOUND,
                      "SERVICE_DEPENDENCY_ENDPOINT_NOT_FOUND",
                      "Unknown service dependency endpoint");
            return;
        }
        if (request.getMethod() != Poco::Net::HTTPRequest::HTTP_GET)
        {
            response.set("Allow", "GET");
            sendError(response, Poco::Net::HTTPResponse::HTTP_METHOD_NOT_ALLOWED,
                      "SERVICE_DEPENDENCY_METHOD_NOT_ALLOWED",
                      "Service dependency endpoint only supports GET");
            return;
        }
        const auto authorization = authorize(_context, request, response);
        if (!authorization) return;
        try
        {
            const auto service = Poco::OSP::ServiceFinder::find<
                ServiceDependencyRuntimeService>(_context);
            if (impact)
            {
                std::string action;
                std::string target;
                bool actionSeen = false;
                bool targetSeen = false;
                for (const auto& parameter : uri.getQueryParameters())
                {
                    if (parameter.first == "action" && !actionSeen &&
                        (parameter.second == "start" || parameter.second == "stop"))
                    {
                        action = parameter.second;
                        actionSeen = true;
                    }
                    else if (parameter.first == "target" && !targetSeen &&
                             validFilter(parameter.second))
                    {
                        target = parameter.second;
                        targetSeen = true;
                    }
                    else
                    {
                        sendError(response,
                                  Poco::Net::HTTPResponse::HTTP_BAD_REQUEST,
                                  "SERVICE_DEPENDENCY_IMPACT_QUERY_INVALID",
                                  "Impact query requires one action=start|stop and one target");
                        return;
                    }
                }
                if (!actionSeen || !targetSeen)
                {
                    sendError(response, Poco::Net::HTTPResponse::HTTP_BAD_REQUEST,
                              "SERVICE_DEPENDENCY_IMPACT_QUERY_INVALID",
                              "Impact query requires one action=start|stop and one target");
                    return;
                }
                const auto decision = action == "start"
                    ? service->analyzeStart(target)
                    : service->analyzeStop(target);
                send(response, Poco::Net::HTTPResponse::HTTP_OK,
                     *lifecycleJson(decision, authorization->principal));
                return;
            }
            std::string owner;
            std::string contract;
            bool ownerSeen = false;
            bool contractSeen = false;
            for (const auto& parameter : uri.getQueryParameters())
            {
                if (parameter.first == "owner" && !ownerSeen &&
                    validFilter(parameter.second))
                {
                    owner = parameter.second;
                    ownerSeen = true;
                }
                else if (parameter.first == "contract" && !contractSeen &&
                         validFilter(parameter.second))
                {
                    contract = parameter.second;
                    contractSeen = true;
                }
                else
                {
                    sendError(response, Poco::Net::HTTPResponse::HTTP_BAD_REQUEST,
                              "SERVICE_DEPENDENCY_QUERY_INVALID",
                              "Only owner and contract query filters are supported");
                    return;
                }
            }
            const auto value = service->snapshot();
            Poco::JSON::Array::Ptr providers = new Poco::JSON::Array;
            for (const auto& provider : value.providers)
                if ((owner.empty() || provider.owner == owner) &&
                    (contract.empty() || provider.contract == contract))
                    providers->add(providerJson(provider));
            Poco::JSON::Array::Ptr requirements = new Poco::JSON::Array;
            for (const auto& requirement : value.requirements)
                if ((owner.empty() || requirement.descriptor.owner == owner) &&
                    (contract.empty() || requirement.descriptor.contract == contract))
                    requirements->add(requirementJson(requirement));
            Poco::JSON::Array::Ptr issues = new Poco::JSON::Array;
            for (const auto& issue : value.issues)
            {
                if (!owner.empty() && issue.owner != owner) continue;
                Poco::JSON::Object::Ptr item = new Poco::JSON::Object;
                item->set("owner", issue.owner);
                item->set("detail", issue.detail);
                issues->add(item);
            }
            Poco::JSON::Object body;
            body.set("schemaVersion", 1);
            body.set("principal", authorization->principal);
            body.set("scope", "runtime-process/bundle-service-contracts");
            body.set("generation", value.generation);
            body.set("ready", value.ready);
            body.set("requiredBlocked",
                     static_cast<Poco::UInt64>(value.requiredBlocked));
            body.set("optionalUnsatisfied",
                     static_cast<Poco::UInt64>(value.optionalUnsatisfied));
            body.set("declarationErrors",
                     static_cast<Poco::UInt64>(value.declarationErrors));
            body.set("activeRequirements",
                     static_cast<Poco::UInt64>(value.activeRequirements));
            body.set("inactiveRequirements",
                     static_cast<Poco::UInt64>(value.inactiveRequirements));
            body.set("providerCount", static_cast<Poco::UInt64>(providers->size()));
            body.set("requirementCount",
                     static_cast<Poco::UInt64>(requirements->size()));
            body.set("providers", providers);
            body.set("requirements", requirements);
            body.set("issues", issues);
            Poco::JSON::Object::Ptr filters = new Poco::JSON::Object;
            if (!owner.empty()) filters->set("owner", owner);
            if (!contract.empty()) filters->set("contract", contract);
            body.set("filters", filters);
            send(response, Poco::Net::HTTPResponse::HTTP_OK, body);
        }
        catch (const Poco::Exception& exception)
        {
            _context->logger().error(
                "Service dependency status failed for principal " +
                authorization->principal + ": " + exception.displayText());
            sendError(response, Poco::Net::HTTPResponse::HTTP_SERVICE_UNAVAILABLE,
                      "SERVICE_DEPENDENCY_STATUS_UNAVAILABLE",
                      "Service dependency status is unavailable");
        }
        catch (const std::exception& exception)
        {
            _context->logger().error(
                "Service dependency status failed for principal " +
                authorization->principal + ": " + exception.what());
            sendError(response, Poco::Net::HTTPResponse::HTTP_BAD_REQUEST,
                      "SERVICE_DEPENDENCY_REQUEST_INVALID",
                      "Invalid service dependency request");
        }
    }

private:
    Poco::OSP::BundleContext::Ptr _context;
};

Poco::OSP::BundleLifecycleDecision guardDecision(
    const LifecycleDecision& decision, const std::string& blockedCode)
{
    Poco::OSP::BundleLifecycleDecision result;
    result.allowed = decision.allowed;
    if (!decision.allowed) result.code = blockedCode;
    result.detail = decision.detail;
    result.affectedBundles = decision.affectedConsumers;
    return result;
}

class LifecycleGuardImpl final : public Poco::OSP::BundleLifecycleGuard
{
public:
    LifecycleGuardImpl(Poco::AutoPtr<RuntimeServiceImpl> runtime,
                       std::string owner)
        : _runtime(std::move(runtime)), _owner(std::move(owner))
    {
    }

    Poco::OSP::BundleLifecycleDecision evaluateStart(
        const std::string& symbolicName) const override
    {
        return guardDecision(
            _runtime->analyzeStart(symbolicName),
            "PDR-BUNDLE-DEPENDENCY-START_BLOCKED");
    }

    Poco::OSP::BundleLifecycleDecision evaluateStop(
        const std::string& symbolicName) const override
    {
        if (symbolicName == _owner) return {};
        return guardDecision(
            _runtime->analyzeStop(symbolicName),
            "PDR-BUNDLE-DEPENDENCY-STOP_BLOCKED");
    }

private:
    Poco::AutoPtr<RuntimeServiceImpl> _runtime;
    std::string _owner;
};
} // namespace

class ServiceDependencyHandlerFactory final :
    public Poco::OSP::Web::WebRequestHandlerFactory
{
public:
    Poco::Net::HTTPRequestHandler* createRequestHandler(
        const Poco::Net::HTTPServerRequest&) override
    {
        return new Handler(context());
    }
};

class ServiceDependencyRuntimeBundleActivator final :
    public Poco::OSP::BundleActivator
{
public:
    void start(Poco::OSP::BundleContext::Ptr context) override
    {
        try
        {
            _context = context;
            _service = new RuntimeServiceImpl(context);
            subscribeBundleEvents(context->events());
            _serviceListener = context->registry().createListener(
                "name",
                Poco::delegate(this,
                    &ServiceDependencyRuntimeBundleActivator::onServiceChanged),
                Poco::delegate(this,
                    &ServiceDependencyRuntimeBundleActivator::onServiceChanged));

            Poco::OSP::Properties properties;
            properties.set("pdr.service", "serviceDependencyRuntime");
            properties.set("pdr.service.contractDiscovery", CONTRACT_RESOURCE);
            properties.set("pdr.bundle", context->thisBundle()->symbolicName());
            _serviceRef = context->registry().registerService(
                ServiceDependencyRuntimeService::SERVICE_NAME, _service, properties);

            Poco::OSP::Properties healthProperties;
            healthProperties.set("pdr.healthContributor", "true");
            healthProperties.set("pdr.healthContributor.component",
                                 "service-dependencies");
            healthProperties.set("pdr.bundle",
                                 context->thisBundle()->symbolicName());
            _healthRef = context->registry().registerService(
                "pdr.healthContributor.serviceDependencies", _service,
                healthProperties);
            _service->refresh();

            _guard = new LifecycleGuardImpl(
                _service, context->thisBundle()->symbolicName());
            Poco::OSP::Properties guardProperties;
            guardProperties.set("pdr.bundle",
                                context->thisBundle()->symbolicName());
            guardProperties.set("pdr.lifecycle.guard", "service-dependencies");
            _guardRef = context->registry().registerService(
                Poco::OSP::BundleLifecycleGuard::SERVICE_NAME,
                _guard, guardProperties);
            context->logger().information(
                "Service dependency runtime started with Bundle-local contract discovery "
                "and lifecycle admission.");
        }
        catch (...)
        {
            stop(context);
            throw;
        }
    }

    void stop(Poco::OSP::BundleContext::Ptr context) override
    {
        _serviceListener = nullptr;
        if (_subscribed) unsubscribeBundleEvents(context->events());
        if (_guardRef)
        {
            try { context->registry().unregisterService(_guardRef); }
            catch (...) {}
        }
        _guardRef = nullptr;
        _guard = nullptr;
        if (_service) _service->stop();
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
        _service = nullptr;
        _context = nullptr;
    }

private:
    void subscribeBundleEvents(Poco::OSP::BundleEvents& events)
    {
        events.bundleInstalled += Poco::delegate(this,
            &ServiceDependencyRuntimeBundleActivator::onBundleChanged);
        events.bundleStarted += Poco::delegate(this,
            &ServiceDependencyRuntimeBundleActivator::onBundleChanged);
        events.bundleStopped += Poco::delegate(this,
            &ServiceDependencyRuntimeBundleActivator::onBundleChanged);
        events.bundleFailed += Poco::delegate(this,
            &ServiceDependencyRuntimeBundleActivator::onBundleChanged);
        events.bundleUninstalled += Poco::delegate(this,
            &ServiceDependencyRuntimeBundleActivator::onBundleChanged);
        _subscribed = true;
    }

    void unsubscribeBundleEvents(Poco::OSP::BundleEvents& events) noexcept
    {
        try
        {
            events.bundleInstalled -= Poco::delegate(this,
                &ServiceDependencyRuntimeBundleActivator::onBundleChanged);
            events.bundleStarted -= Poco::delegate(this,
                &ServiceDependencyRuntimeBundleActivator::onBundleChanged);
            events.bundleStopped -= Poco::delegate(this,
                &ServiceDependencyRuntimeBundleActivator::onBundleChanged);
            events.bundleFailed -= Poco::delegate(this,
                &ServiceDependencyRuntimeBundleActivator::onBundleChanged);
            events.bundleUninstalled -= Poco::delegate(this,
                &ServiceDependencyRuntimeBundleActivator::onBundleChanged);
        }
        catch (...) {}
        _subscribed = false;
    }

    void onBundleChanged(const void*, Poco::OSP::BundleEvent&)
    {
        if (_service) _service->refresh();
    }

    void onServiceChanged(const Poco::OSP::ServiceRef::Ptr&)
    {
        if (_service) _service->refresh();
    }

    Poco::OSP::BundleContext::Ptr _context;
    Poco::AutoPtr<RuntimeServiceImpl> _service;
    Poco::OSP::ServiceRef::Ptr _serviceRef;
    Poco::OSP::ServiceRef::Ptr _healthRef;
    Poco::AutoPtr<LifecycleGuardImpl> _guard;
    Poco::OSP::ServiceRef::Ptr _guardRef;
    Poco::OSP::ServiceListener::Ptr _serviceListener;
    bool _subscribed{false};
};
} // namespace PocoDDS::ServiceDependency

POCO_BEGIN_MANIFEST(Poco::OSP::BundleActivator)
    POCO_EXPORT_CLASS(
        PocoDDS::ServiceDependency::ServiceDependencyRuntimeBundleActivator)
POCO_END_MANIFEST

POCO_BEGIN_NAMED_MANIFEST(WebServer, Poco::OSP::Web::WebRequestHandlerFactory)
    POCO_EXPORT_CLASS(PocoDDS::ServiceDependency::ServiceDependencyHandlerFactory)
POCO_END_MANIFEST
