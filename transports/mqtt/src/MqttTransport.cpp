#include "PocoDDS/MqttTransport/MqttTransport.h"

#include "PocoDDS/Protocols/MQTT/MqttClient.h"

#include <atomic>
#include <chrono>
#include <mutex>
#include <stdexcept>
#include <unordered_map>
#include <unordered_set>
#include <utility>

namespace PocoDDS::MqttTransport
{
using namespace PocoDDS::RuntimeCore;
namespace
{
constexpr const char* originHeader = "pdr.transport.origin";

PocoDDS::Protocols::MQTT::MqttClient::Options clientOptions(const MqttTransportOptions& options)
{
    PocoDDS::Protocols::MQTT::MqttClient::Options result;
    result.serverUri = options.serverUri;
    result.clientId = options.clientId;
    result.username = options.username;
    result.password = options.password;
    result.trustStore = options.trustStore;
    result.keyStore = options.keyStore;
    result.privateKey = options.privateKey;
    result.privateKeyPassword = options.privateKeyPassword;
    result.enabledCipherSuites = options.enabledCipherSuites;
    result.verifyServerCertificate = options.verifyServerCertificate;
    result.verifyHostname = options.verifyHostname;
    result.cleanSession = options.cleanSession;
    result.keepAliveSeconds = options.keepAliveSeconds;
    result.connectTimeoutSeconds = options.connectTimeoutSeconds;
    return result;
}

std::string instanceId(const MqttTransportOptions& options)
{
    static std::atomic<std::uint64_t> sequence{1};
    return options.clientId + "-" +
           std::to_string(sequence.fetch_add(1, std::memory_order_relaxed)) + "-" +
           std::to_string(std::chrono::steady_clock::now().time_since_epoch().count());
}

PocoDDS::Protocols::MQTT::QoS qos(const TopicSpec& topic)
{
    return topic.delivery == Delivery::reliable ? PocoDDS::Protocols::MQTT::QoS::atLeastOnce
                                                : PocoDDS::Protocols::MQTT::QoS::atMostOnce;
}
} // namespace

struct MqttTransport::State : public std::enable_shared_from_this<State>
{
    struct SubscriptionState
    {
        TopicSpec topic;
        std::size_t count{0};
    };

    explicit State(MqttTransportOptions value)
        : options(std::move(value)), origin(instanceId(options)),
          client(std::make_unique<PocoDDS::Protocols::MQTT::MqttClient>(clientOptions(options)))
    {
        if (options.topicPrefix.empty())
            options.topicPrefix = "pdr/";
        if (options.topicPrefix.back() != '/')
            options.topicPrefix.push_back('/');
    }

    MqttTransportOptions options;
    std::string origin;
    InProcessTransport local;
    std::unique_ptr<PocoDDS::Protocols::MQTT::MqttClient> client;
    mutable std::mutex mutex;
    std::mutex operationMutex;
    std::unordered_map<std::string, SubscriptionState> subscriptions;
    std::unordered_set<std::string> wireSubscriptions;
    bool started{false};

    std::string physicalTopic(const std::string& logicalTopic) const
    {
        return options.topicPrefix + logicalTopic;
    }

    void receive(const PocoDDS::Protocols::MQTT::Message& wire)
    {
        const std::vector<std::uint8_t> bytes(wire.payload.begin(), wire.payload.end());
        const auto decoded = decodeMessageFrame(bytes, options.codecLimits);
        if (!decoded || physicalTopic(decoded.value().topic.name) != wire.topic)
            return;
        auto message = decoded.value().message;
        const auto originIterator = message.headers.find(originHeader);
        if (originIterator != message.headers.end() && originIterator->second == origin)
            return;
        message.headers.erase(originHeader);
        local.publish(decoded.value().topic, message);
    }
};

MqttTransport::MqttTransport(MqttTransportOptions options)
    : _state(std::make_shared<State>(std::move(options)))
{
    std::weak_ptr<State> weak = _state;
    _state->client->setMessageHandler(
        [weak](const auto& message)
        {
            if (const auto state = weak.lock())
                state->receive(message);
        });
}

MqttTransport::~MqttTransport() { stop(); }

Outcome<void> MqttTransport::start()
{
    std::lock_guard<std::mutex> operationLock(_state->operationMutex);
    {
        std::lock_guard<std::mutex> lock(_state->mutex);
        if (_state->started && _state->client->isOpen())
            return Outcome<void>::success();
        _state->started = false;
    }
    try
    {
        _state->client->open();
        std::vector<TopicSpec> topics;
        {
            std::lock_guard<std::mutex> lock(_state->mutex);
            topics.reserve(_state->subscriptions.size());
            for (const auto& [name, subscription] : _state->subscriptions)
            {
                if (subscription.count != 0 && _state->wireSubscriptions.count(name) == 0)
                    topics.push_back(subscription.topic);
            }
        }
        for (const auto& topic : topics)
        {
            _state->client->subscribe(_state->physicalTopic(topic.name), qos(topic));
            std::lock_guard<std::mutex> lock(_state->mutex);
            _state->wireSubscriptions.insert(topic.name);
        }
        {
            std::lock_guard<std::mutex> lock(_state->mutex);
            _state->started = true;
        }
        return Outcome<void>::success();
    }
    catch (const std::exception& exception)
    {
        _state->client->close();
        return Outcome<void>::failure({RuntimeErrorCode::unavailable, exception.what(), true});
    }
}

void MqttTransport::stop() noexcept
{
    std::lock_guard<std::mutex> operationLock(_state->operationMutex);
    {
        std::lock_guard<std::mutex> lock(_state->mutex);
        if (!_state->started)
            return;
        _state->started = false;
    }
    _state->client->close();
}

bool MqttTransport::running() const noexcept
{
    std::lock_guard<std::mutex> lock(_state->mutex);
    return _state->started && _state->client->isOpen();
}

std::string MqttTransport::id() const { return "mqtt"; }

TransportCapabilities MqttTransport::capabilities() const noexcept
{
    return {false, false, true, false, true, false};
}

Subscription MqttTransport::subscribe(const TopicSpec& topic, Handler handler)
{
    if (topic.name.empty())
        throw std::invalid_argument("MQTT transport topic name cannot be empty");
    auto localSubscription =
        std::make_shared<Subscription>(_state->local.subscribe(topic, std::move(handler)));
    std::lock_guard<std::mutex> operationLock(_state->operationMutex);
    bool subscribeWire = false;
    {
        std::lock_guard<std::mutex> lock(_state->mutex);
        const auto found = _state->subscriptions.find(topic.name);
        if (found != _state->subscriptions.end())
        {
            const auto& existing = found->second.topic;
            if (existing.messageType != topic.messageType ||
                existing.schemaVersion != topic.schemaVersion ||
                existing.delivery != topic.delivery || existing.durable != topic.durable)
            {
                localSubscription->reset();
                throw std::invalid_argument(
                    "MQTT transport topic already has a different contract");
            }
            subscribeWire = found->second.count++ == 0 && _state->started;
        }
        else
        {
            _state->subscriptions.emplace(topic.name, State::SubscriptionState{topic, 1});
            subscribeWire = _state->started;
        }
    }
    try
    {
        if (subscribeWire)
        {
            _state->client->subscribe(_state->physicalTopic(topic.name), qos(topic));
            std::lock_guard<std::mutex> lock(_state->mutex);
            _state->wireSubscriptions.insert(topic.name);
        }
    }
    catch (...)
    {
        localSubscription->reset();
        std::lock_guard<std::mutex> lock(_state->mutex);
        const auto found = _state->subscriptions.find(topic.name);
        if (found != _state->subscriptions.end() && --found->second.count == 0)
            _state->subscriptions.erase(found);
        throw;
    }

    std::weak_ptr<State> weak = _state;
    const auto topicName = topic.name;
    return Subscription(
        [weak, topicName, localSubscription]
        {
            localSubscription->reset();
            const auto state = weak.lock();
            if (!state)
                return;
            std::lock_guard<std::mutex> operationLock(state->operationMutex);
            bool unsubscribeWire = false;
            {
                std::lock_guard<std::mutex> lock(state->mutex);
                const auto found = state->subscriptions.find(topicName);
                if (found == state->subscriptions.end())
                    return;
                if (--found->second.count == 0)
                {
                    // MqttClient keeps the desired subscriptions across reconnects. Always
                    // remove the final subscription there, including while the transport is
                    // stopped, so a later start() cannot restore stale wire state.
                    unsubscribeWire = true;
                    state->subscriptions.erase(found);
                    state->wireSubscriptions.erase(topicName);
                }
            }
            if (unsubscribeWire)
            {
                try
                {
                    state->client->unsubscribe(state->physicalTopic(topicName));
                }
                catch (...)
                {
                }
            }
        });
}

PublishResult MqttTransport::publish(const TopicSpec& topic, const Message& message)
{
    auto result = _state->local.publish(topic, message);
    Message wireMessage = message;
    wireMessage.headers[originHeader] = _state->origin;
    const auto encoded = encodeMessageFrame(topic, wireMessage, _state->options.codecLimits);
    if (!encoded)
    {
        ++result.dropped;
        return result;
    }
    std::lock_guard<std::mutex> operationLock(_state->operationMutex);
    {
        std::lock_guard<std::mutex> lock(_state->mutex);
        if (!_state->started)
        {
            ++result.failed;
            return result;
        }
    }
    try
    {
        const std::string payload(encoded.value().begin(), encoded.value().end());
        _state->client->publish(_state->physicalTopic(topic.name), payload, qos(topic),
                                topic.durable);
        ++result.accepted;
    }
    catch (...)
    {
        ++result.failed;
    }
    return result;
}

} // namespace PocoDDS::MqttTransport
