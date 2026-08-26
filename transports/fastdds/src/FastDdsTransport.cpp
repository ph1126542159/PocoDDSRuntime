#include "PocoDDS/FastDdsTransport/FastDdsTransport.h"

#include "PocoDDS/DDS/Envelope.h"
#include "PocoDDS/DDS/Runtime.h"

#include <atomic>
#include <chrono>
#include <mutex>
#include <optional>
#include <stdexcept>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>

namespace PocoDDS::FastDdsTransport
{
using namespace PocoDDS::RuntimeCore;
namespace
{
constexpr const char* originHeader = "pdr.transport.origin";
constexpr std::size_t maximumEnvelopeFrameBytes = 180U * 1024U;
constexpr char base64Alphabet[] =
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

std::string encodeBase64(const std::vector<std::uint8_t>& input)
{
    std::string output;
    output.reserve(((input.size() + 2) / 3) * 4);
    for (std::size_t offset = 0; offset < input.size(); offset += 3)
    {
        const auto first = input[offset];
        const auto second = offset + 1 < input.size() ? input[offset + 1] : 0;
        const auto third = offset + 2 < input.size() ? input[offset + 2] : 0;
        const auto value = (static_cast<std::uint32_t>(first) << 16) |
                           (static_cast<std::uint32_t>(second) << 8) | third;
        output.push_back(base64Alphabet[(value >> 18) & 0x3fU]);
        output.push_back(base64Alphabet[(value >> 12) & 0x3fU]);
        output.push_back(offset + 1 < input.size() ? base64Alphabet[(value >> 6) & 0x3fU] : '=');
        output.push_back(offset + 2 < input.size() ? base64Alphabet[value & 0x3fU] : '=');
    }
    return output;
}

int base64Value(char value)
{
    if (value >= 'A' && value <= 'Z')
        return value - 'A';
    if (value >= 'a' && value <= 'z')
        return value - 'a' + 26;
    if (value >= '0' && value <= '9')
        return value - '0' + 52;
    if (value == '+')
        return 62;
    if (value == '/')
        return 63;
    return -1;
}

std::optional<std::vector<std::uint8_t>> decodeBase64(const std::string& input)
{
    if (input.size() % 4 != 0)
        return std::nullopt;
    std::vector<std::uint8_t> output;
    output.reserve((input.size() / 4) * 3);
    for (std::size_t offset = 0; offset < input.size(); offset += 4)
    {
        const bool last = offset + 4 == input.size();
        const int first = base64Value(input[offset]);
        const int second = base64Value(input[offset + 1]);
        const int third = input[offset + 2] == '=' ? 0 : base64Value(input[offset + 2]);
        const int fourth = input[offset + 3] == '=' ? 0 : base64Value(input[offset + 3]);
        if (first < 0 || second < 0 || third < 0 || fourth < 0 ||
            ((!last) && (input[offset + 2] == '=' || input[offset + 3] == '=')) ||
            (input[offset + 2] == '=' && input[offset + 3] != '='))
            return std::nullopt;
        const auto value =
            (static_cast<std::uint32_t>(first) << 18) | (static_cast<std::uint32_t>(second) << 12) |
            (static_cast<std::uint32_t>(third) << 6) | static_cast<std::uint32_t>(fourth);
        output.push_back(static_cast<std::uint8_t>((value >> 16) & 0xffU));
        if (input[offset + 2] != '=')
            output.push_back(static_cast<std::uint8_t>((value >> 8) & 0xffU));
        if (input[offset + 3] != '=')
            output.push_back(static_cast<std::uint8_t>(value & 0xffU));
    }
    return output;
}

std::string instanceId(const FastDdsTransportOptions& options)
{
    static std::atomic<std::uint64_t> sequence{1};
    return options.participantName + "-" +
           std::to_string(sequence.fetch_add(1, std::memory_order_relaxed)) + "-" +
           std::to_string(std::chrono::steady_clock::now().time_since_epoch().count());
}

} // namespace

struct FastDdsTransport::State : public std::enable_shared_from_this<State>
{
    struct SubscriptionState
    {
        TopicSpec topic;
        std::size_t count{0};
    };

    explicit State(FastDdsTransportOptions value)
        : options(std::move(value)), origin(instanceId(options)),
          runtime(options.domainId, options.participantName)
    {
        if (options.participantName.empty())
            throw std::invalid_argument("Fast DDS participant name cannot be empty");
        if (options.codecLimits.maximumFrameBytes == 0 ||
            options.codecLimits.maximumFrameBytes > maximumEnvelopeFrameBytes)
            throw std::invalid_argument(
                "Fast DDS transport maximumFrameBytes must be in range 1..184320");
    }

    FastDdsTransportOptions options;
    std::string origin;
    InProcessTransport local;
    PocoDDS::FastDDS::Runtime runtime;
    mutable std::mutex mutex;
    std::mutex operationMutex;
    std::unordered_map<std::string, SubscriptionState> subscriptions;
    std::unordered_set<std::string> wireSubscriptions;
    std::atomic<std::uint64_t> sequence{1};
    bool started{false};

    std::string physicalTopic(const std::string& logicalTopic) const
    {
        return options.topicPrefix + logicalTopic;
    }

    void installWireSubscription(const TopicSpec& topic)
    {
        std::weak_ptr<State> weak = shared_from_this();
        runtime.subscribe(
            physicalTopic(topic.name),
            [weak,
             expectedTopic = physicalTopic(topic.name)](const PocoDDS::FastDDS::Envelope& wire)
            {
                const auto state = weak.lock();
                if (!state || wire.kind != "pdr.runtime.message")
                    return;
                const auto bytes = decodeBase64(wire.payload);
                if (!bytes)
                    return;
                const auto decoded = decodeMessageFrame(*bytes, state->options.codecLimits);
                if (!decoded || state->physicalTopic(decoded.value().topic.name) != expectedTopic)
                    return;
                auto message = decoded.value().message;
                const auto origin = message.headers.find(originHeader);
                if (origin != message.headers.end() && origin->second == state->origin)
                    return;
                message.headers.erase(originHeader);
                state->local.publish(decoded.value().topic, message);
            });
    }
};

FastDdsTransport::FastDdsTransport(FastDdsTransportOptions options)
    : _state(std::make_shared<State>(std::move(options)))
{
}

FastDdsTransport::~FastDdsTransport() { stop(); }

Outcome<void> FastDdsTransport::start()
{
    std::lock_guard<std::mutex> operationLock(_state->operationMutex);
    {
        std::lock_guard<std::mutex> lock(_state->mutex);
        if (_state->started && _state->runtime.started())
            return Outcome<void>::success();
        _state->started = false;
        _state->wireSubscriptions.clear();
    }
    try
    {
        _state->runtime.start();
        std::vector<TopicSpec> topics;
        {
            std::lock_guard<std::mutex> lock(_state->mutex);
            topics.reserve(_state->subscriptions.size());
            for (const auto& [_, subscription] : _state->subscriptions)
            {
                if (subscription.count != 0)
                    topics.push_back(subscription.topic);
            }
        }
        for (const auto& topic : topics)
        {
            _state->installWireSubscription(topic);
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
        _state->runtime.stop();
        std::lock_guard<std::mutex> lock(_state->mutex);
        _state->wireSubscriptions.clear();
        return Outcome<void>::failure({RuntimeErrorCode::unavailable, exception.what(), true});
    }
}

void FastDdsTransport::stop() noexcept
{
    std::lock_guard<std::mutex> operationLock(_state->operationMutex);
    {
        std::lock_guard<std::mutex> lock(_state->mutex);
        _state->started = false;
        _state->wireSubscriptions.clear();
    }
    _state->runtime.stop();
}

bool FastDdsTransport::running() const noexcept
{
    std::lock_guard<std::mutex> lock(_state->mutex);
    return _state->started && _state->runtime.started();
}

std::string FastDdsTransport::id() const { return "fastdds"; }

TransportCapabilities FastDdsTransport::capabilities() const noexcept
{
    return {false, false, true, false, false, false};
}

Subscription FastDdsTransport::subscribe(const TopicSpec& topic, Handler handler)
{
    if (topic.name.empty())
        throw std::invalid_argument("Fast DDS transport topic name cannot be empty");
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
                    "Fast DDS transport topic already has a different contract");
            }
            ++found->second.count;
            subscribeWire = _state->started && _state->wireSubscriptions.count(topic.name) == 0;
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
            _state->installWireSubscription(topic);
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
            std::lock_guard<std::mutex> lock(state->mutex);
            const auto found = state->subscriptions.find(topicName);
            if (found != state->subscriptions.end() && --found->second.count == 0)
                state->subscriptions.erase(found);
        });
}

PublishResult FastDdsTransport::publish(const TopicSpec& topic, const Message& message)
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
        PocoDDS::FastDDS::Envelope envelope;
        envelope.sequence = _state->sequence.fetch_add(1, std::memory_order_relaxed);
        envelope.timestampMicroseconds = std::chrono::duration_cast<std::chrono::microseconds>(
                                             std::chrono::system_clock::now().time_since_epoch())
                                             .count();
        envelope.kind = "pdr.runtime.message";
        envelope.operation = "publish";
        envelope.payload = encodeBase64(encoded.value());
        envelope.correlationId = message.context.correlationId;
        envelope.traceParent = message.context.traceParent;
        _state->runtime.publish(_state->physicalTopic(topic.name), envelope);
        ++result.accepted;
    }
    catch (...)
    {
        ++result.failed;
    }
    return result;
}

} // namespace PocoDDS::FastDdsTransport
