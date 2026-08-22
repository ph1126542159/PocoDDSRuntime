#include "PocoDDS/RuntimeCore/InProcessTransport.h"

#include <atomic>
#include <mutex>
#include <stdexcept>
#include <unordered_map>
#include <utility>

namespace PocoDDS::RuntimeCore
{

struct InProcessTransport::State
{
    struct Registration
    {
        std::string messageType;
        Handler handler;
    };

    mutable std::mutex mutex;
    std::atomic<std::uint64_t> nextId{1};
    std::unordered_map<std::string, std::unordered_map<std::uint64_t, Registration>> topics;
};

InProcessTransport::InProcessTransport():
    _state(std::make_shared<State>())
{
}

InProcessTransport::~InProcessTransport() = default;

std::string InProcessTransport::id() const
{
    return "inproc";
}

TransportCapabilities InProcessTransport::capabilities() const noexcept
{
    return {true, false, false, false, false, true};
}

Subscription InProcessTransport::subscribe(const TopicSpec& topic, Handler handler)
{
    if (topic.name.empty())
        throw std::invalid_argument("in-process transport topic name cannot be empty");
    if (!handler)
        throw std::invalid_argument("in-process transport handler cannot be empty");

    const auto registrationId = _state->nextId.fetch_add(1, std::memory_order_relaxed);
    {
        std::lock_guard<std::mutex> lock(_state->mutex);
        _state->topics[topic.name].emplace(
            registrationId, State::Registration{topic.messageType, std::move(handler)});
    }
    std::weak_ptr<State> weak = _state;
    const std::string name = topic.name;
    return Subscription([weak, name, registrationId] {
        const auto state = weak.lock();
        if (!state)
            return;
        std::lock_guard<std::mutex> lock(state->mutex);
        const auto topicIterator = state->topics.find(name);
        if (topicIterator == state->topics.end())
            return;
        topicIterator->second.erase(registrationId);
        if (topicIterator->second.empty())
            state->topics.erase(topicIterator);
    });
}

PublishResult InProcessTransport::publish(const TopicSpec& topic, const Message& message)
{
    if (topic.name.empty())
        throw std::invalid_argument("in-process transport topic name cannot be empty");
    if (!topic.messageType.empty() && !message.type.empty() &&
        topic.messageType != message.type)
        throw std::invalid_argument("message type does not match topic contract");

    std::vector<State::Registration> handlers;
    {
        std::lock_guard<std::mutex> lock(_state->mutex);
        const auto topicIterator = _state->topics.find(topic.name);
        if (topicIterator == _state->topics.end())
            return {};
        handlers.reserve(topicIterator->second.size());
        for (const auto& [_, registration] : topicIterator->second)
        {
            if (registration.messageType.empty() || message.type.empty() ||
                registration.messageType == message.type)
                handlers.push_back(registration);
        }
    }

    PublishResult result;
    for (const auto& registration : handlers)
    {
        try
        {
            registration.handler(topic, message);
            ++result.delivered;
        }
        catch (...)
        {
            ++result.failed;
        }
    }
    return result;
}

std::size_t InProcessTransport::subscriptionCount() const noexcept
{
    std::lock_guard<std::mutex> lock(_state->mutex);
    std::size_t count = 0;
    for (const auto& [_, registrations] : _state->topics)
        count += registrations.size();
    return count;
}

} // namespace PocoDDS::RuntimeCore
