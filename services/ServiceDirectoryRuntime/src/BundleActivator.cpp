#include "PocoDDS/DDS/Envelope.h"
#include "PocoDDS/DDS/Runtime.h"
#include "PocoDDS/Health/Health.h"
#include "PocoDDS/ManagementAuth/IdentityService.h"
#include "PocoDDS/Membership/MembershipRuntimeService.h"
#include "PocoDDS/ServiceDirectory/ServiceAdvertisementProvider.h"
#include "PocoDDS/ServiceDirectory/ServiceDirectoryRuntimeService.h"

#include <Poco/AutoPtr.h>
#include <Poco/ClassLibrary.h>
#include <Poco/Delegate.h>
#include <Poco/Environment.h>
#include <Poco/Exception.h>
#include <Poco/JSON/Array.h>
#include <Poco/JSON/Object.h>
#include <Poco/JSON/Parser.h>
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
#include <Poco/String.h>
#include <Poco/Timestamp.h>
#include <Poco/URI.h>
#include <Poco/Util/AbstractConfiguration.h>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <map>
#include <memory>
#include <mutex>
#include <optional>
#include <set>
#include <sstream>
#include <string>
#include <thread>
#include <tuple>
#include <utility>
#include <vector>

namespace PocoDDS::ServiceDirectory
{
namespace
{
constexpr int PROTOCOL_VERSION = 1;
constexpr const char* DEFAULT_TOPIC = "pdr.runtime.service-directory.v1";
constexpr const char* READ_PERMISSION = "resource.read";

std::vector<std::string> splitSorted(const std::string& encoded)
{
    std::vector<std::string> result;
    std::size_t begin = 0;
    while (begin <= encoded.size())
    {
        const auto end = encoded.find(',', begin);
        auto value = encoded.substr(
            begin, end == std::string::npos ? std::string::npos : end - begin);
        Poco::trimInPlace(value);
        if (!value.empty()) result.push_back(std::move(value));
        if (end == std::string::npos) break;
        begin = end + 1;
    }
    std::sort(result.begin(), result.end());
    result.erase(std::unique(result.begin(), result.end()), result.end());
    return result;
}

bool sameDescriptor(const Advertisement& current,
                    const ServiceDescriptor& desired)
{
    return current.serviceName == desired.serviceName &&
           current.instanceId == desired.instanceId &&
           current.endpoint == desired.endpoint &&
           current.protocol == desired.protocol &&
           current.zone == desired.zone && current.tags == desired.tags &&
           current.state == desired.state;
}

Poco::JSON::Array::Ptr tagsJson(const std::vector<std::string>& tags)
{
    Poco::JSON::Array::Ptr result = new Poco::JSON::Array;
    for (const auto& tag : tags) result->add(tag);
    return result;
}

Poco::JSON::Object::Ptr advertisementJson(const Advertisement& value,
                                          const std::string& messageType)
{
    Poco::JSON::Object::Ptr object = new Poco::JSON::Object;
    object->set("protocolVersion", PROTOCOL_VERSION);
    object->set("messageType", messageType);
    object->set("serviceName", value.serviceName);
    object->set("instanceId", value.instanceId);
    object->set("runtimeId", value.runtimeId);
    object->set("runtimeIncarnation",
                static_cast<Poco::UInt64>(value.runtimeIncarnation));
    object->set("revision", static_cast<Poco::UInt64>(value.revision));
    object->set("endpoint", value.endpoint);
    object->set("protocol", value.protocol);
    object->set("zone", value.zone);
    object->set("tags", tagsJson(value.tags));
    object->set("state", toString(value.state));
    return object;
}

std::string encode(const Advertisement& value, const std::string& messageType)
{
    std::ostringstream output;
    advertisementJson(value, messageType)->stringify(output);
    return output.str();
}

struct DecodedMessage
{
    std::string type;
    Advertisement advertisement;
};

DecodedMessage decode(const std::string& encoded)
{
    if (encoded.empty() || encoded.size() > 65536)
        throw Poco::InvalidArgumentException(
            "Service Directory message must contain 1..65536 bytes");
    auto object = Poco::JSON::Parser().parse(encoded)
                      .extract<Poco::JSON::Object::Ptr>();
    if (!object || object->optValue<int>("protocolVersion", 0) != PROTOCOL_VERSION)
        throw Poco::InvalidArgumentException(
            "Unsupported Service Directory protocol version");
    DecodedMessage result;
    result.type = object->optValue<std::string>("messageType", "");
    if (result.type != "advertise" && result.type != "withdraw")
        throw Poco::InvalidArgumentException(
            "Service Directory messageType must be advertise or withdraw");
    auto& value = result.advertisement;
    value.serviceName = object->optValue<std::string>("serviceName", "");
    value.instanceId = object->optValue<std::string>("instanceId", "");
    value.runtimeId = object->optValue<std::string>("runtimeId", "");
    value.runtimeIncarnation =
        object->optValue<Poco::UInt64>("runtimeIncarnation", 0);
    value.revision = object->optValue<Poco::UInt64>("revision", 0);
    value.endpoint = object->optValue<std::string>("endpoint", "");
    value.protocol = object->optValue<std::string>("protocol", "");
    value.zone = object->optValue<std::string>("zone", "");
    const auto state = object->optValue<std::string>("state", "");
    if (state == "ready") value.state = AdvertisedState::ready;
    else if (state == "draining") value.state = AdvertisedState::draining;
    else throw Poco::InvalidArgumentException("Invalid advertised state");
    const auto tags = object->getArray("tags");
    if (!tags || tags->size() > 64)
        throw Poco::InvalidArgumentException(
            "Service Directory tags array is required and bounded to 64 entries");
    value.tags.reserve(tags->size());
    for (std::size_t index = 0; index < tags->size(); ++index)
        value.tags.push_back(
            tags->getElement<std::string>(static_cast<unsigned>(index)));
    return result;
}

Poco::JSON::Object::Ptr instanceJson(const InstanceSnapshot& value)
{
    auto object = advertisementJson(value.advertisement, "snapshot");
    object->remove("messageType");
    object->remove("protocolVersion");
    object->set("state", toString(value.state));
    object->set("ageMilliseconds", static_cast<Poco::UInt64>(value.age.count()));
    return object;
}

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
        PocoDDS::ManagementAuth::IdentityService::SERVICE_NAME);
    if (!reference)
    {
        sendError(response, Poco::Net::HTTPResponse::HTTP_SERVICE_UNAVAILABLE,
                  "SERVICE_DIRECTORY_IDENTITY_UNAVAILABLE",
                  "Management identity service is unavailable");
        return std::nullopt;
    }
    const auto identity = reference->castedInstance<
        PocoDDS::ManagementAuth::IdentityService>();
    const auto matched = identity->authenticateAuthorizationHeader(
        request.get("Authorization", ""));
    if (!matched)
    {
        if (!identity->snapshot().required) return "development-anonymous";
        response.set("WWW-Authenticate",
                     "Bearer realm=\"pdr-service-directory\"");
        sendError(response, Poco::Net::HTTPResponse::HTTP_UNAUTHORIZED,
                  "SERVICE_DIRECTORY_AUTHENTICATION_REQUIRED",
                  "A valid management Bearer token is required");
        return std::nullopt;
    }
    if (!matched->authorized(READ_PERMISSION))
    {
        sendError(response, Poco::Net::HTTPResponse::HTTP_FORBIDDEN,
                  "SERVICE_DIRECTORY_PERMISSION_DENIED",
                  "Authenticated principal lacks resource.read");
        return std::nullopt;
    }
    response.set("X-PDR-Management-Principal", matched->id);
    return matched->id;
}

RoutingPolicy parsePolicy(const std::string& value)
{
    if (value.empty() || value == "round-robin") return RoutingPolicy::roundRobin;
    if (value == "rendezvous-hash") return RoutingPolicy::rendezvousHash;
    if (value == "prefer-local") return RoutingPolicy::preferLocal;
    throw Poco::InvalidArgumentException("Unknown routing policy", value);
}
} // namespace

class ConfiguredProvider final : public ServiceAdvertisementProvider
{
public:
    explicit ConfiguredProvider(std::vector<ServiceDescriptor> values)
        : _descriptors(std::move(values))
    {
    }

    std::string providerId() const override { return "pdr.configured-services"; }
    std::vector<ServiceDescriptor> descriptors() const override
    {
        return _descriptors;
    }

private:
    std::vector<ServiceDescriptor> _descriptors;
};

class RuntimeServiceImpl final : public ServiceDirectoryRuntimeService,
                                 public Health::IHealthContributor
{
public:
    RuntimeServiceImpl(Options options,
                       std::chrono::milliseconds publishInterval,
                       std::uint32_t domainId,
                       std::string topic,
                       std::string localRuntimeId,
                       Poco::AutoPtr<Membership::MembershipRuntimeService> membership)
        : _directory(options),
          _publishInterval(publishInterval),
          _topic(std::move(topic)),
          _localRuntimeId(std::move(localRuntimeId)),
          _membership(std::move(membership))
    {
        if (_publishInterval < std::chrono::milliseconds{100} ||
            _publishInterval > std::chrono::minutes{1})
            throw Poco::InvalidArgumentException(
                "Service Directory publish interval must contain 100..60000 milliseconds");
        if (options.advertisementTtl < _publishInterval * 2)
            throw Poco::InvalidArgumentException(
                "Service Directory TTL must be at least twice the publish interval");
        if (_topic.empty() || _topic.size() > 128)
            throw Poco::InvalidArgumentException(
                "Service Directory topic must contain 1..128 characters");
        if (_localRuntimeId.empty() || !_membership)
            throw Poco::InvalidArgumentException(
                "Service Directory requires local Runtime identity and Membership service");
        _runtime = std::make_unique<PocoDDS::FastDDS::Runtime>(
            domainId, "pdr-service-directory-" + _localRuntimeId);
    }

    void start()
    {
        _runtime->start();
        _runtime->subscribe(_topic, [this](const auto& envelope) {
            receive(envelope);
        });
        _runtime->preparePublisher(_topic);
        _running = true;
        try
        {
            publishCycle();
            _publisher = std::thread([this] { publishLoop(); });
        }
        catch (...)
        {
            _running = false;
            _runtime->stop();
            throw;
        }
    }

    void addProvider(const Poco::OSP::ServiceRef::Ptr& reference,
                     const std::string& id)
    {
        std::lock_guard<std::mutex> lock(_providerMutex);
        const auto found = std::find_if(
            _providers.begin(), _providers.end(), [&](const auto& entry) {
                return entry.reference->name() == reference->name();
            });
        if (found == _providers.end()) _providers.push_back({reference, id});
        _wake.notify_all();
    }

    void removeProvider(const Poco::OSP::ServiceRef::Ptr& reference)
    {
        std::lock_guard<std::mutex> lock(_providerMutex);
        _providers.erase(
            std::remove_if(_providers.begin(), _providers.end(), [&](const auto& entry) {
                return entry.reference->name() == reference->name();
            }),
            _providers.end());
        _wake.notify_all();
    }

    ObservationResult observe(Advertisement advertisement) override
    {
        return _directory.observe(std::move(advertisement));
    }

    bool withdraw(const std::string& serviceName,
                  const std::string& instanceId,
                  const std::string& runtimeId,
                  std::uint64_t runtimeIncarnation,
                  std::uint64_t finalRevision) override
    {
        return _directory.withdraw(serviceName, instanceId, runtimeId,
                                   runtimeIncarnation, finalRevision);
    }

    Snapshot snapshot() const override { return _directory.snapshot(); }

    RouteResult route(const RouteRequest& request) override
    {
        const auto membership = _membership->snapshot();
        std::set<std::pair<std::string, std::uint64_t>> alive;
        for (const auto& member : membership.members)
            if (member.state == Membership::MemberState::alive)
                alive.emplace(member.heartbeat.instanceId,
                              member.heartbeat.incarnation);
        return _router.select(_directory.snapshot(), request,
                              [&](const auto& advertisement) {
                                  return alive.count({advertisement.runtimeId,
                                                      advertisement.runtimeIncarnation}) != 0;
                              });
    }

    Health::Report health() const override
    {
        if (!_runtime || !_runtime->started())
            return {"service-directory", Health::Status::down,
                    "Fast DDS Service Directory transport is stopped",
                    "PDR-HEALTH-SERVICE-DIRECTORY-TRANSPORT-DOWN",
                    "Restart the ServiceDirectoryRuntime Bundle after repairing DDS.",
                    {_topic}};
        try { (void) localMember(); }
        catch (const std::exception& exception)
        {
            return {"service-directory", Health::Status::down,
                    exception.what(),
                    "PDR-HEALTH-SERVICE-DIRECTORY-MEMBER-MISSING",
                    "Restore the local Membership heartbeat before routing services.",
                    {_localRuntimeId}};
        }
        std::lock_guard<std::mutex> lock(_healthMutex);
        if (!_lastPublishFailure.empty() || !_providerFailure.empty())
        {
            const auto detail = !_lastPublishFailure.empty()
                ? _lastPublishFailure : _providerFailure;
            return {"service-directory", Health::Status::degraded,
                    detail, "PDR-HEALTH-SERVICE-DIRECTORY-DEGRADED",
                    "Inspect DDS publishing and advertisement Provider descriptors.",
                    {_topic}};
        }
        const auto value = _directory.snapshot();
        return {"service-directory", Health::Status::up,
                std::to_string(value.ready) + " ready, " +
                    std::to_string(value.draining) + " draining, " +
                    std::to_string(value.expired) + " expired instance(s)",
                "PDR-HEALTH-SERVICE-DIRECTORY-UP", "", {_topic}};
    }

    void shutdown() noexcept
    {
        if (!_running.exchange(false))
        {
            if (_runtime) _runtime->stop();
            return;
        }
        _wake.notify_all();
        if (_publisher.joinable()) _publisher.join();
        std::vector<Advertisement> active;
        {
            std::lock_guard<std::mutex> lock(_localMutex);
            for (auto& [key, entry] : _local)
            {
                (void) key;
                ++entry.advertisement.revision;
                active.push_back(entry.advertisement);
            }
            _local.clear();
        }
        for (const auto& advertisement : active)
        {
            try
            {
                publish(advertisement, "withdraw");
                _directory.withdraw(
                    advertisement.serviceName, advertisement.instanceId,
                    advertisement.runtimeId, advertisement.runtimeIncarnation,
                    advertisement.revision);
            }
            catch (...) {}
        }
        _runtime->stop();
    }

private:
    struct ProviderEntry
    {
        Poco::OSP::ServiceRef::Ptr reference;
        std::string id;
    };

    struct LocalEntry
    {
        Advertisement advertisement;
        std::string providerId;
    };

    Membership::MemberSnapshot localMember() const
    {
        const auto snapshot = _membership->snapshot();
        const auto found = std::find_if(
            snapshot.members.begin(), snapshot.members.end(), [&](const auto& member) {
                return member.heartbeat.instanceId == _localRuntimeId &&
                       member.state == Membership::MemberState::alive;
            });
        if (found == snapshot.members.end())
            throw Poco::IllegalStateException(
                "Local Runtime is absent from the Membership view", _localRuntimeId);
        return *found;
    }

    void publish(const Advertisement& advertisement, const std::string& operation)
    {
        PocoDDS::FastDDS::Envelope envelope;
        envelope.sequence = ++_envelopeSequence;
        envelope.timestampMicroseconds = Poco::Timestamp().epochMicroseconds();
        envelope.kind = "service-directory";
        envelope.deviceId = advertisement.runtimeId;
        envelope.operation = operation;
        envelope.payload = encode(advertisement, operation);
        _runtime->publish(_topic, envelope);
    }

    void publishCycle()
    {
        const auto member = localMember();
        std::vector<ProviderEntry> providers;
        {
            std::lock_guard<std::mutex> lock(_providerMutex);
            providers = _providers;
        }
        using Desired = std::pair<ServiceDescriptor, std::string>;
        std::map<std::pair<std::string, std::string>, Desired> desired;
        std::string providerFailure;
        for (const auto& entry : providers)
        {
            try
            {
                std::map<std::pair<std::string, std::string>, ServiceDescriptor>
                    providerDesired;
                const auto provider = entry.reference->castedInstance<
                    ServiceAdvertisementProvider>();
                if (provider->providerId() != entry.id)
                    throw Poco::InvalidArgumentException(
                        "Service advertisement Provider ID changed", entry.id);
                for (auto descriptor : provider->descriptors())
                {
                    std::sort(descriptor.tags.begin(), descriptor.tags.end());
                    descriptor.tags.erase(
                        std::unique(descriptor.tags.begin(), descriptor.tags.end()),
                        descriptor.tags.end());
                    const auto key = std::make_pair(
                        descriptor.serviceName, descriptor.instanceId);
                    if (!providerDesired.emplace(key, std::move(descriptor)).second)
                        throw Poco::ExistsException(
                            "Duplicate service instance identity in Provider",
                            key.first + "/" + key.second);
                }
                for (const auto& [key, descriptor] : providerDesired)
                    if (desired.count(key) != 0)
                        throw Poco::ExistsException(
                            "Service instance identity is owned by multiple Providers",
                            key.first + "/" + key.second);
                for (auto& [key, descriptor] : providerDesired)
                    desired.emplace(key, Desired{std::move(descriptor), entry.id});
            }
            catch (const std::exception& exception)
            {
                providerFailure = "Advertisement Provider " + entry.id +
                                  " failed: " + exception.what();
            }
        }

        std::vector<std::pair<Advertisement, std::string>> messages;
        {
            std::lock_guard<std::mutex> lock(_localMutex);
            for (auto& [key, value] : desired)
            {
                auto current = _local.find(key);
                Advertisement advertisement;
                if (current == _local.end() ||
                    current->second.advertisement.runtimeIncarnation !=
                        member.heartbeat.incarnation)
                {
                    static_cast<ServiceDescriptor&>(advertisement) = value.first;
                    advertisement.runtimeId = _localRuntimeId;
                    advertisement.runtimeIncarnation =
                        member.heartbeat.incarnation;
                    advertisement.revision = 1;
                }
                else
                {
                    advertisement = current->second.advertisement;
                    if (!sameDescriptor(advertisement, value.first))
                        static_cast<ServiceDescriptor&>(advertisement) = value.first;
                    ++advertisement.revision;
                }
                _local[key] = {advertisement, value.second};
                messages.push_back({advertisement, "advertise"});
            }
            for (auto iterator = _local.begin(); iterator != _local.end();)
            {
                if (desired.count(iterator->first) != 0)
                {
                    ++iterator;
                    continue;
                }
                ++iterator->second.advertisement.revision;
                messages.push_back(
                    {iterator->second.advertisement, "withdraw"});
                iterator = _local.erase(iterator);
            }
        }

        for (const auto& [advertisement, operation] : messages)
        {
            if (operation == "advertise")
            {
                const auto observed = _directory.observe(advertisement);
                if (!observed)
                    throw Poco::IllegalStateException(
                        "Local Service Directory advertisement rejected",
                        observed.detail);
            }
            else
                _directory.withdraw(
                    advertisement.serviceName, advertisement.instanceId,
                    advertisement.runtimeId, advertisement.runtimeIncarnation,
                    advertisement.revision);
            publish(advertisement, operation);
        }
        std::lock_guard<std::mutex> lock(_healthMutex);
        _lastPublishFailure.clear();
        _providerFailure = std::move(providerFailure);
    }

    void publishLoop() noexcept
    {
        while (_running)
        {
            std::unique_lock<std::mutex> lock(_waitMutex);
            _wake.wait_for(lock, _publishInterval);
            if (!_running) break;
            lock.unlock();
            try { publishCycle(); }
            catch (const std::exception& exception)
            {
                std::lock_guard<std::mutex> healthLock(_healthMutex);
                _lastPublishFailure = exception.what();
            }
            catch (...)
            {
                std::lock_guard<std::mutex> healthLock(_healthMutex);
                _lastPublishFailure = "Unknown Service Directory publish failure";
            }
        }
    }

    void receive(const PocoDDS::FastDDS::Envelope& envelope) noexcept
    {
        if (!_running || envelope.kind != "service-directory") return;
        try
        {
            const auto message = decode(envelope.payload);
            if (envelope.deviceId != message.advertisement.runtimeId ||
                envelope.operation != message.type)
                throw Poco::InvalidArgumentException(
                    "Service Directory envelope and payload identity mismatch");
            if (message.type == "advertise")
                _directory.observe(message.advertisement);
            else
                _directory.withdraw(
                    message.advertisement.serviceName,
                    message.advertisement.instanceId,
                    message.advertisement.runtimeId,
                    message.advertisement.runtimeIncarnation,
                    message.advertisement.revision);
        }
        catch (...) { ++_malformedMessages; }
    }

    Directory _directory;
    Router _router;
    std::chrono::milliseconds _publishInterval;
    std::string _topic;
    std::string _localRuntimeId;
    Poco::AutoPtr<Membership::MembershipRuntimeService> _membership;
    std::unique_ptr<PocoDDS::FastDDS::Runtime> _runtime;
    std::atomic<bool> _running{false};
    std::atomic<std::uint64_t> _envelopeSequence{0};
    std::atomic<std::uint64_t> _malformedMessages{0};
    std::thread _publisher;
    std::mutex _waitMutex;
    std::condition_variable _wake;
    mutable std::mutex _providerMutex;
    std::vector<ProviderEntry> _providers;
    mutable std::mutex _localMutex;
    std::map<std::pair<std::string, std::string>, LocalEntry> _local;
    mutable std::mutex _healthMutex;
    std::string _lastPublishFailure;
    std::string _providerFailure;
};

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
        const bool routeRequest =
            uri.getPath() == "/api/v1/service-directory/route";
        if (uri.getPath() != "/api/v1/service-directory" && !routeRequest)
        {
            sendError(response, Poco::Net::HTTPResponse::HTTP_NOT_FOUND,
                      "SERVICE_DIRECTORY_ENDPOINT_NOT_FOUND",
                      "Unknown Service Directory endpoint");
            return;
        }
        if (request.getMethod() != Poco::Net::HTTPRequest::HTTP_GET)
        {
            response.set("Allow", "GET");
            sendError(response, Poco::Net::HTTPResponse::HTTP_METHOD_NOT_ALLOWED,
                      "SERVICE_DIRECTORY_METHOD_NOT_ALLOWED",
                      "Service Directory endpoints only support GET");
            return;
        }
        const auto principal = authorize(_context, request, response);
        if (!principal) return;
        try
        {
            auto service = Poco::OSP::ServiceFinder::find<
                ServiceDirectoryRuntimeService>(_context);
            std::map<std::string, std::string> parameters;
            for (const auto& parameter : uri.getQueryParameters())
                if (!parameters.emplace(parameter.first, parameter.second).second)
                    throw Poco::InvalidArgumentException(
                        "Duplicate Service Directory query parameter",
                        parameter.first);
            if (routeRequest)
            {
                const std::set<std::string> allowed{
                    "serviceName", "policy", "routingKey", "localRuntimeId", "tags"};
                for (const auto& [name, value] : parameters)
                {
                    (void) value;
                    if (allowed.count(name) == 0)
                        throw Poco::InvalidArgumentException(
                            "Unknown route query parameter", name);
                }
                RouteRequest route;
                route.serviceName = parameters["serviceName"];
                route.policy = parsePolicy(parameters["policy"]);
                route.routingKey = parameters["routingKey"];
                route.localRuntimeId = parameters["localRuntimeId"];
                route.requiredTags = splitSorted(parameters["tags"]);
                const auto result = service->route(route);
                Poco::JSON::Object body;
                body.set("schemaVersion", 1);
                body.set("principal", *principal);
                body.set("scope", "runtime-fleet/service-instance-routing");
                body.set("status", toString(result.status));
                body.set("policy", toString(route.policy));
                body.set("candidates", static_cast<Poco::UInt64>(result.candidates));
                body.set("detail", result.detail);
                if (result.instance) body.set("instance", instanceJson(*result.instance));
                const auto status = result
                    ? Poco::Net::HTTPResponse::HTTP_OK
                    : result.status == SelectionStatus::invalid ||
                              result.status == SelectionStatus::routingKeyRequired
                          ? Poco::Net::HTTPResponse::HTTP_BAD_REQUEST
                          : Poco::Net::HTTPResponse::HTTP_SERVICE_UNAVAILABLE;
                send(response, status, body);
                return;
            }

            if (parameters.size() > 1 ||
                (!parameters.empty() && parameters.count("serviceName") == 0))
                throw Poco::InvalidArgumentException(
                    "Snapshot supports only one serviceName filter");
            const auto filter = parameters["serviceName"];
            const auto value = service->snapshot();
            Poco::JSON::Array::Ptr instances = new Poco::JSON::Array;
            for (const auto& instance : value.instances)
                if (filter.empty() || instance.advertisement.serviceName == filter)
                    instances->add(instanceJson(instance));
            Poco::JSON::Object body;
            body.set("schemaVersion", 1);
            body.set("principal", *principal);
            body.set("scope", "runtime-fleet/service-instance-directory");
            body.set("generation", static_cast<Poco::UInt64>(value.generation));
            body.set("serviceCount", static_cast<Poco::UInt64>(value.serviceCount));
            body.set("ready", static_cast<Poco::UInt64>(value.ready));
            body.set("draining", static_cast<Poco::UInt64>(value.draining));
            body.set("expired", static_cast<Poco::UInt64>(value.expired));
            body.set("instanceCount", static_cast<Poco::UInt64>(instances->size()));
            body.set("instances", instances);
            send(response, Poco::Net::HTTPResponse::HTTP_OK, body);
        }
        catch (const std::exception& exception)
        {
            sendError(response, Poco::Net::HTTPResponse::HTTP_BAD_REQUEST,
                      "SERVICE_DIRECTORY_REQUEST_INVALID", exception.what());
        }
    }

private:
    Poco::OSP::BundleContext::Ptr _context;
};
class ServiceDirectoryHandlerFactory final :
    public Poco::OSP::Web::WebRequestHandlerFactory
{
public:
    Poco::Net::HTTPRequestHandler* createRequestHandler(
        const Poco::Net::HTTPServerRequest&) override
    {
        return new Handler(context());
    }
};

class ServiceDirectoryRuntimeBundleActivator final :
    public Poco::OSP::BundleActivator
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
            Options options;
            const auto interval = std::chrono::milliseconds(
                configuration->getInt(
                    "pdr.serviceDirectory.publishIntervalMilliseconds", 1000));
            options.advertisementTtl = std::chrono::milliseconds(
                configuration->getInt("pdr.serviceDirectory.ttlMilliseconds", 5000));
            options.tombstoneRetention = std::chrono::milliseconds(
                configuration->getInt(
                    "pdr.serviceDirectory.tombstoneRetentionMilliseconds", 30000));
            const auto maximumInstances = configuration->getInt(
                "pdr.serviceDirectory.maximumInstances", 4096);
            const auto maximumPerService = configuration->getInt(
                "pdr.serviceDirectory.maximumInstancesPerService", 256);
            if (maximumInstances <= 0 || maximumPerService <= 0)
                throw Poco::InvalidArgumentException(
                    "Service Directory capacities must be positive");
            options.maximumInstances = static_cast<std::size_t>(maximumInstances);
            options.maximumInstancesPerService =
                static_cast<std::size_t>(maximumPerService);
            const auto localRuntimeId = configuration->getString(
                "pdr.membership.instanceId", Poco::Environment::nodeName() + ":runtime");
            const auto topic = configuration->getString(
                "pdr.serviceDirectory.topic", DEFAULT_TOPIC);
            const auto domainId = static_cast<std::uint32_t>(configuration->getUInt(
                "pdr.fastdds.domainId", 0));
            auto membership = Poco::OSP::ServiceFinder::find<
                Membership::MembershipRuntimeService>(context);
            _service = new RuntimeServiceImpl(
                options, interval, domainId, topic, localRuntimeId, membership);

            _providerListener = context->registry().createListener(
                "pdr.serviceAdvertisement.provider.kind == \"directory\"",
                Poco::delegate(this,
                    &ServiceDirectoryRuntimeBundleActivator::onProviderRegistered),
                Poco::delegate(this,
                    &ServiceDirectoryRuntimeBundleActivator::onProviderUnregistered));

            auto configured = configuredDescriptors(*configuration);
            if (!configured.empty())
            {
                _configuredProvider = new ConfiguredProvider(std::move(configured));
                Poco::OSP::Properties providerProperties;
                providerProperties.set(
                    ServiceAdvertisementProvider::PROPERTY_KIND,
                    ServiceAdvertisementProvider::KIND);
                providerProperties.set(
                    ServiceAdvertisementProvider::PROPERTY_ID,
                    _configuredProvider->providerId());
                providerProperties.set("pdr.bundle",
                                       context->thisBundle()->symbolicName());
                _configuredProviderRef = context->registry().registerService(
                    "pdr.serviceAdvertisement.configured", _configuredProvider,
                    providerProperties);
            }
            _service->start();

            Poco::OSP::Properties properties;
            properties.set("pdr.bundle", context->thisBundle()->symbolicName());
            properties.set("pdr.service", "serviceDirectoryRuntime");
            properties.set("pdr.serviceDirectory.protocolVersion", "1");
            properties.set("pdr.serviceDirectory.remoteInvocation", "not-provided");
            _serviceRef = context->registry().registerService(
                ServiceDirectoryRuntimeService::SERVICE_NAME, _service, properties);

            Poco::OSP::Properties healthProperties;
            healthProperties.set("pdr.bundle", context->thisBundle()->symbolicName());
            healthProperties.set("pdr.healthContributor", "true");
            healthProperties.set("pdr.healthContributor.component",
                                 "service-directory");
            _healthRef = context->registry().registerService(
                "pdr.healthContributor.serviceDirectory", _service,
                healthProperties);
            context->logger().information(
                "Service Directory started on DDS domain " +
                std::to_string(domainId) + " topic " + topic +
                "; only explicit advertisement Providers are remotely discoverable.");
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
        if (_configuredProviderRef)
        {
            try { context->registry().unregisterService(_configuredProviderRef); }
            catch (...) {}
        }
        _configuredProviderRef = nullptr;
        _configuredProvider = nullptr;
        _service = nullptr;
        _context = nullptr;
    }

private:
    static std::vector<ServiceDescriptor> configuredDescriptors(
        Poco::Util::AbstractConfiguration& configuration)
    {
        const auto count = configuration.getInt(
            "pdr.serviceDirectory.advertisements.count", 0);
        if (count < 0 || count > 64)
            throw Poco::InvalidArgumentException(
                "Configured Service Directory advertisement count must be 0..64");
        std::vector<ServiceDescriptor> result;
        result.reserve(static_cast<std::size_t>(count));
        for (int index = 0; index < count; ++index)
        {
            const auto prefix = "pdr.serviceDirectory.advertisements." +
                                std::to_string(index) + ".";
            ServiceDescriptor descriptor;
            descriptor.serviceName = configuration.getString(
                prefix + "serviceName", "");
            descriptor.instanceId = configuration.getString(
                prefix + "instanceId", "");
            descriptor.endpoint = configuration.getString(
                prefix + "endpoint", "");
            descriptor.protocol = configuration.getString(
                prefix + "protocol", "");
            descriptor.zone = configuration.getString(prefix + "zone", "");
            descriptor.tags = splitSorted(
                configuration.getString(prefix + "tags", ""));
            const auto state = configuration.getString(prefix + "state", "ready");
            if (state == "ready") descriptor.state = AdvertisedState::ready;
            else if (state == "draining")
                descriptor.state = AdvertisedState::draining;
            else throw Poco::InvalidArgumentException(
                "Configured advertisement state must be ready or draining", state);
            result.push_back(std::move(descriptor));
        }
        return result;
    }

    void onProviderRegistered(const Poco::OSP::ServiceRef::Ptr& reference)
    {
        if (!_service) return;
        const auto provider = reference->castedInstance<
            ServiceAdvertisementProvider>();
        const auto id = provider->providerId();
        const auto propertyId = reference->properties().get(
            ServiceAdvertisementProvider::PROPERTY_ID, "");
        if (id.empty() || id != propertyId)
            throw Poco::InvalidArgumentException(
                "Service advertisement Provider property/id mismatch",
                reference->name());
        _service->addProvider(reference, id);
    }

    void onProviderUnregistered(const Poco::OSP::ServiceRef::Ptr& reference)
    {
        if (_service) _service->removeProvider(reference);
    }

    Poco::OSP::BundleContext::Ptr _context;
    Poco::AutoPtr<RuntimeServiceImpl> _service;
    Poco::AutoPtr<ConfiguredProvider> _configuredProvider;
    Poco::OSP::ServiceListener::Ptr _providerListener;
    Poco::OSP::ServiceRef::Ptr _configuredProviderRef;
    Poco::OSP::ServiceRef::Ptr _serviceRef;
    Poco::OSP::ServiceRef::Ptr _healthRef;
};
} // namespace PocoDDS::ServiceDirectory

POCO_BEGIN_MANIFEST(Poco::OSP::BundleActivator)
    POCO_EXPORT_CLASS(PocoDDS::ServiceDirectory::ServiceDirectoryRuntimeBundleActivator)
POCO_END_MANIFEST

POCO_BEGIN_NAMED_MANIFEST(WebServer, Poco::OSP::Web::WebRequestHandlerFactory)
    POCO_EXPORT_CLASS(PocoDDS::ServiceDirectory::ServiceDirectoryHandlerFactory)
POCO_END_MANIFEST
