#include "PocoDDS/DDS/Envelope.h"
#include "PocoDDS/DDS/Runtime.h"
#include "PocoDDS/Health/Health.h"
#include "PocoDDS/Membership/IncarnationStore.h"
#include "PocoDDS/Membership/MembershipRuntimeService.h"

#include <Poco/AutoPtr.h>
#include <Poco/ClassLibrary.h>
#include <Poco/Data/SQLite/Connector.h>
#include <Poco/Environment.h>
#include <Poco/Exception.h>
#include <Poco/File.h>
#include <Poco/JSON/Array.h>
#include <Poco/JSON/Object.h>
#include <Poco/JSON/Parser.h>
#include <Poco/OSP/Bundle.h>
#include <Poco/OSP/BundleActivator.h>
#include <Poco/OSP/BundleContext.h>
#include <Poco/OSP/PreferencesService.h>
#include <Poco/OSP/Properties.h>
#include <Poco/OSP/ServiceFinder.h>
#include <Poco/OSP/ServiceRef.h>
#include <Poco/OSP/ServiceRegistry.h>
#include <Poco/Path.h>
#include <Poco/Process.h>
#include <Poco/String.h>
#include <Poco/Timestamp.h>
#include <Poco/Util/AbstractConfiguration.h>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <memory>
#include <mutex>
#include <sstream>
#include <string>
#include <thread>
#include <utility>
#include <vector>

namespace PocoDDS::Membership
{
namespace
{
constexpr int PROTOCOL_VERSION = 1;
constexpr const char* DEFAULT_TOPIC = "pdr.runtime.membership.v1";

std::vector<std::string> capabilities(const std::string& encoded)
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

Poco::JSON::Object::Ptr messageJson(const Heartbeat& heartbeat,
                                    const std::string& messageType)
{
    Poco::JSON::Object::Ptr object = new Poco::JSON::Object;
    object->set("protocolVersion", PROTOCOL_VERSION);
    object->set("messageType", messageType);
    object->set("instanceId", heartbeat.instanceId);
    object->set("incarnation", static_cast<Poco::UInt64>(heartbeat.incarnation));
    object->set("sequence", static_cast<Poco::UInt64>(heartbeat.sequence));
    object->set("role", heartbeat.role);
    object->set("endpoint", heartbeat.endpoint);
    Poco::JSON::Array::Ptr items = new Poco::JSON::Array;
    for (const auto& capability : heartbeat.capabilities) items->add(capability);
    object->set("capabilities", items);
    return object;
}

std::string encode(const Heartbeat& heartbeat, const std::string& messageType)
{
    std::ostringstream encoded;
    messageJson(heartbeat, messageType)->stringify(encoded);
    return encoded.str();
}

struct DecodedMessage
{
    std::string type;
    Heartbeat heartbeat;
};

DecodedMessage decode(const std::string& encoded)
{
    if (encoded.empty() || encoded.size() > 65536)
        throw Poco::InvalidArgumentException(
            "Membership message must contain 1..65536 bytes");
    auto object = Poco::JSON::Parser().parse(encoded)
                      .extract<Poco::JSON::Object::Ptr>();
    if (!object || object->optValue<int>("protocolVersion", 0) != PROTOCOL_VERSION)
        throw Poco::InvalidArgumentException(
            "Unsupported membership protocol version");
    DecodedMessage result;
    result.type = object->optValue<std::string>("messageType", "");
    if (result.type != "heartbeat" && result.type != "leave")
        throw Poco::InvalidArgumentException(
            "Membership messageType must be heartbeat or leave");
    result.heartbeat.instanceId =
        object->optValue<std::string>("instanceId", "");
    result.heartbeat.incarnation =
        object->optValue<Poco::UInt64>("incarnation", 0);
    result.heartbeat.sequence = object->optValue<Poco::UInt64>("sequence", 0);
    result.heartbeat.role = object->optValue<std::string>("role", "");
    result.heartbeat.endpoint = object->optValue<std::string>("endpoint", "");
    const auto items = object->getArray("capabilities");
    if (!items || items->size() > 128)
        throw Poco::InvalidArgumentException(
            "Membership capabilities array is required and bounded to 128 entries");
    result.heartbeat.capabilities.reserve(items->size());
    for (std::size_t index = 0; index < items->size(); ++index)
        result.heartbeat.capabilities.push_back(
            items->getElement<std::string>(static_cast<unsigned>(index)));
    return result;
}

void ensureDatabaseParent(const std::string& database)
{
    Poco::Path parent(database);
    parent.makeParent();
    if (!parent.toString().empty()) Poco::File(parent).createDirectories();
}
} // namespace

class RuntimeServiceImpl final : public MembershipRuntimeService,
                                 public Health::IHealthContributor
{
public:
    RuntimeServiceImpl(Options options,
                       Heartbeat self,
                       std::chrono::milliseconds heartbeatInterval,
                       std::uint32_t domainId,
                       std::string topic,
                       const std::string& database)
        : _registry(options),
          _self(std::move(self)),
          _heartbeatInterval(heartbeatInterval),
          _topic(std::move(topic))
    {
        if (_heartbeatInterval < std::chrono::milliseconds{100} ||
            _heartbeatInterval > std::chrono::minutes{1})
            throw Poco::InvalidArgumentException(
                "Membership heartbeat interval must contain 100..60000 milliseconds");
        if (options.heartbeatTtl < _heartbeatInterval * 2)
            throw Poco::InvalidArgumentException(
                "Membership heartbeat TTL must be at least twice the publish interval");
        if (_topic.empty() || _topic.size() > 128)
            throw Poco::InvalidArgumentException(
                "Membership topic must contain 1..128 characters");
        ensureDatabaseParent(database);
        SqliteIncarnationStore store(database);
        _self.incarnation = store.next(_self.instanceId);
        _runtime = std::make_unique<PocoDDS::FastDDS::Runtime>(
            domainId, "pdr-membership-" + _self.instanceId);
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
            publishHeartbeat();
            _publisher = std::thread([this] { publishLoop(); });
        }
        catch (...)
        {
            _running = false;
            _runtime->stop();
            throw;
        }
    }

    ObservationResult observe(Heartbeat heartbeat) override
    {
        return _registry.observe(std::move(heartbeat));
    }

    bool leave(const std::string& instanceId, std::uint64_t incarnation,
               std::uint64_t finalSequence) override
    {
        return _registry.leave(instanceId, incarnation, finalSequence);
    }

    Snapshot snapshot() const override { return _registry.snapshot(); }

    Health::Report health() const override
    {
        if (!_runtime || !_runtime->started())
            return {"runtime-membership", Health::Status::down,
                    "Fast DDS membership transport is stopped",
                    "PDR-HEALTH-MEMBERSHIP-TRANSPORT-DOWN",
                    "Restart the MembershipRuntime Bundle after repairing the DDS transport.",
                    {_topic}};
        const auto current = _registry.snapshot();
        const auto self = std::find_if(
            current.members.begin(), current.members.end(), [&](const auto& member) {
                return member.heartbeat.instanceId == _self.instanceId &&
                       member.heartbeat.incarnation == _self.incarnation;
            });
        if (self == current.members.end() || self->state != MemberState::alive)
            return {"runtime-membership", Health::Status::down,
                    "The local Runtime is absent from its receiver-clock membership view",
                    "PDR-HEALTH-MEMBERSHIP-SELF-EXPIRED",
                    "Inspect the membership publisher thread and heartbeat interval/TTL settings.",
                    {_self.instanceId}};
        std::lock_guard<std::mutex> lock(_healthMutex);
        if (!_lastPublishFailure.empty())
            return {"runtime-membership", Health::Status::degraded,
                    "The latest heartbeat publish failed: " + _lastPublishFailure,
                    "PDR-HEALTH-MEMBERSHIP-PUBLISH-FAILED",
                    "Verify Fast DDS peers, interfaces and transport resources.",
                    {_topic}};
        return {"runtime-membership", Health::Status::up,
                "Local member is alive; remote expiration uses receiver monotonic time",
                "PDR-HEALTH-MEMBERSHIP-UP", "", {_self.instanceId}};
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
        try
        {
            Heartbeat final = _self;
            final.sequence = ++_sequence;
            PocoDDS::FastDDS::Envelope envelope;
            envelope.sequence = final.sequence;
            envelope.timestampMicroseconds = Poco::Timestamp().epochMicroseconds();
            envelope.kind = "runtime-membership";
            envelope.deviceId = final.instanceId;
            envelope.operation = "leave";
            envelope.payload = encode(final, "leave");
            _runtime->publish(_topic, envelope);
            _registry.leave(final.instanceId, final.incarnation, final.sequence);
        }
        catch (...) {}
        _runtime->stop();
    }

private:
    void publishHeartbeat()
    {
        Heartbeat heartbeat = _self;
        heartbeat.sequence = ++_sequence;
        const auto observed = _registry.observe(heartbeat);
        if (!observed)
            throw Poco::IllegalStateException(
                "Local membership heartbeat was rejected", observed.detail);
        PocoDDS::FastDDS::Envelope envelope;
        envelope.sequence = heartbeat.sequence;
        envelope.timestampMicroseconds = Poco::Timestamp().epochMicroseconds();
        envelope.kind = "runtime-membership";
        envelope.deviceId = heartbeat.instanceId;
        envelope.operation = "heartbeat";
        envelope.payload = encode(heartbeat, "heartbeat");
        _runtime->publish(_topic, envelope);
        std::lock_guard<std::mutex> lock(_healthMutex);
        _lastPublishFailure.clear();
    }

    void publishLoop() noexcept
    {
        while (_running)
        {
            std::unique_lock<std::mutex> lock(_waitMutex);
            if (_wake.wait_for(lock, _heartbeatInterval,
                               [this] { return !_running.load(); }))
                break;
            lock.unlock();
            try { publishHeartbeat(); }
            catch (const std::exception& exception)
            {
                std::lock_guard<std::mutex> healthLock(_healthMutex);
                _lastPublishFailure = exception.what();
            }
            catch (...)
            {
                std::lock_guard<std::mutex> healthLock(_healthMutex);
                _lastPublishFailure = "unknown publish failure";
            }
        }
    }

    void receive(const PocoDDS::FastDDS::Envelope& envelope) noexcept
    {
        if (!_running || envelope.kind != "runtime-membership") return;
        try
        {
            const auto message = decode(envelope.payload);
            if (envelope.deviceId != message.heartbeat.instanceId ||
                envelope.sequence != message.heartbeat.sequence ||
                envelope.operation != message.type)
                throw Poco::InvalidArgumentException(
                    "Membership envelope and payload identity mismatch");
            if (message.type == "heartbeat")
                _registry.observe(message.heartbeat);
            else
                _registry.leave(message.heartbeat.instanceId,
                                message.heartbeat.incarnation,
                                message.heartbeat.sequence);
        }
        catch (...) { ++_malformedMessages; }
    }

    Registry _registry;
    Heartbeat _self;
    std::chrono::milliseconds _heartbeatInterval;
    std::string _topic;
    std::unique_ptr<PocoDDS::FastDDS::Runtime> _runtime;
    std::atomic<bool> _running{false};
    std::atomic<std::uint64_t> _malformedMessages{0};
    std::uint64_t _sequence{0};
    std::thread _publisher;
    std::mutex _waitMutex;
    std::condition_variable _wake;
    mutable std::mutex _healthMutex;
    std::string _lastPublishFailure;
};

class MembershipRuntimeBundleActivator final : public Poco::OSP::BundleActivator
{
public:
    void start(Poco::OSP::BundleContext::Ptr context) override
    {
        try
        {
            // Native OSP Bundles can resolve their own PocoData module image on
            // Windows. Register in this Bundle's image as well; SessionFactory
            // reference-counts duplicate registrations and stop balances ours.
            Poco::Data::SQLite::Connector::registerConnector();
            _sqliteRegistered = true;
            auto preferences = Poco::OSP::ServiceFinder::find<
                Poco::OSP::PreferencesService>(context);
            auto configuration = preferences->configuration();
            const auto interval = std::chrono::milliseconds(
                configuration->getInt(
                    "pdr.membership.heartbeatIntervalMilliseconds", 1000));
            Options options;
            options.heartbeatTtl = std::chrono::milliseconds(
                configuration->getInt(
                    "pdr.membership.heartbeatTtlMilliseconds", 5000));
            options.tombstoneRetention = std::chrono::milliseconds(
                configuration->getInt(
                    "pdr.membership.tombstoneRetentionMilliseconds", 30000));
            const auto maximumMembers = configuration->getInt(
                "pdr.membership.maximumMembers", 1024);
            if (maximumMembers <= 0)
                throw Poco::InvalidArgumentException(
                    "pdr.membership.maximumMembers must be positive");
            options.maximumMembers = static_cast<std::size_t>(maximumMembers);

            Heartbeat self;
            self.instanceId = configuration->getString(
                "pdr.membership.instanceId", Poco::Environment::nodeName() + ":runtime");
            self.role = configuration->getString("pdr.membership.role", "runtime");
            self.endpoint = configuration->getString("pdr.membership.endpoint", "");
            self.capabilities = capabilities(configuration->getString(
                "pdr.membership.capabilities", "health,service-registry"));
            Poco::Path defaultDatabase(context->persistentDirectory());
            defaultDatabase.append("incarnations.sqlite");
            const auto database = configuration->getString(
                "pdr.membership.database", defaultDatabase.toString());
            const auto topic = configuration->getString(
                "pdr.membership.topic", DEFAULT_TOPIC);
            const auto domainId = static_cast<std::uint32_t>(configuration->getUInt(
                "pdr.fastdds.domainId", 0));

            _service = new RuntimeServiceImpl(
                options, std::move(self), interval, domainId, topic, database);
            _service->start();
            Poco::OSP::Properties properties;
            properties.set("pdr.bundle", context->thisBundle()->symbolicName());
            properties.set("pdr.service", "membershipRuntime");
            properties.set("pdr.membership.protocolVersion", "1");
            properties.set("pdr.membership.scope", "runtime-instance-health");
            _serviceRef = context->registry().registerService(
                MembershipRuntimeService::SERVICE_NAME, _service, properties);

            Poco::OSP::Properties healthProperties;
            healthProperties.set("pdr.bundle", context->thisBundle()->symbolicName());
            healthProperties.set("pdr.healthContributor", "true");
            healthProperties.set("pdr.healthContributor.component", "runtime-membership");
            _healthRef = context->registry().registerService(
                "pdr.healthContributor.runtimeMembership", _service, healthProperties);
            context->logger().information(
                "Runtime membership started on DDS domain " +
                std::to_string(domainId) + " topic " + topic +
                "; scope is liveness discovery, not quorum or leader election.");
        }
        catch (...)
        {
            stop(context);
            throw;
        }
    }

    void stop(Poco::OSP::BundleContext::Ptr context) override
    {
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
        _service = nullptr;
        if (_sqliteRegistered)
        {
            try { Poco::Data::SQLite::Connector::unregisterConnector(); }
            catch (...) {}
            _sqliteRegistered = false;
        }
    }

private:
    Poco::AutoPtr<RuntimeServiceImpl> _service;
    Poco::OSP::ServiceRef::Ptr _serviceRef;
    Poco::OSP::ServiceRef::Ptr _healthRef;
    bool _sqliteRegistered{false};
};
} // namespace PocoDDS::Membership

POCO_BEGIN_MANIFEST(Poco::OSP::BundleActivator)
    POCO_EXPORT_CLASS(PocoDDS::Membership::MembershipRuntimeBundleActivator)
POCO_END_MANIFEST
