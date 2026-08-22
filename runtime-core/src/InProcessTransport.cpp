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

namespace
{
class DeadlineExpired final : public std::runtime_error
{
  public:
    DeadlineExpired() : std::runtime_error("message deadline expired before publication") {}
};

RuntimeError asyncError(std::exception_ptr error)
{
    try
    {
        if (error)
            std::rethrow_exception(error);
    }
    catch (const DeadlineExpired& exception)
    {
        return {RuntimeErrorCode::timeout, exception.what(), false};
    }
    catch (const std::invalid_argument& exception)
    {
        return {RuntimeErrorCode::invalidArgument, exception.what(), false};
    }
    catch (const std::exception& exception)
    {
        return {RuntimeErrorCode::internalError, exception.what(), false};
    }
    catch (...)
    {
        return {RuntimeErrorCode::internalError, "unknown asynchronous publish failure", false};
    }
    return {RuntimeErrorCode::internalError, "unknown asynchronous publish failure", false};
}
} // namespace

PublishResult InProcessTransport::dispatch(const std::shared_ptr<State>& state,
                                           const TopicSpec& topic, const Message& message)
{
    if (topic.name.empty())
        throw std::invalid_argument("in-process transport topic name cannot be empty");
    if (!topic.messageType.empty() && !message.type.empty() && topic.messageType != message.type)
        throw std::invalid_argument("message type does not match topic contract");
    if (!topic.schemaVersion.empty() && !message.schemaVersion.empty() &&
        topic.schemaVersion != message.schemaVersion)
        throw std::invalid_argument("message schema version does not match topic contract");
    if (message.context.expired())
        throw DeadlineExpired();

    std::vector<State::Registration> handlers;
    {
        std::lock_guard<std::mutex> lock(state->mutex);
        const auto topicIterator = state->topics.find(topic.name);
        if (topicIterator == state->topics.end())
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
    result.accepted = handlers.size();
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

InProcessTransport::InProcessTransport() : InProcessTransport(std::make_shared<InlineExecutor>()) {}

InProcessTransport::InProcessTransport(std::shared_ptr<IExecutor> executor)
    : _state(std::make_shared<State>()), _executor(std::move(executor))
{
    if (!_executor)
        throw std::invalid_argument("in-process transport executor cannot be null");
}

InProcessTransport::~InProcessTransport() = default;

std::string InProcessTransport::id() const { return "inproc"; }

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
    return Subscription(
        [weak, name, registrationId]
        {
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
    return dispatch(_state, topic, message);
}

AsyncPublishTicket InProcessTransport::publishAsync(const TopicSpec& topic, const Message& message)
{
    auto promise = std::make_shared<std::promise<Outcome<PublishResult>>>();
    auto completion = promise->get_future();
    const auto state = _state;
    ExecutorTask task;
    task.run = [promise, state, topic, message]
    {
        try
        {
            promise->set_value(Outcome<PublishResult>::success(dispatch(state, topic, message)));
        }
        catch (...)
        {
            promise->set_value(
                Outcome<PublishResult>::failure(asyncError(std::current_exception())));
        }
    };
    task.cancel = [promise](RuntimeError error)
    {
        try
        {
            promise->set_value(Outcome<PublishResult>::failure(std::move(error)));
        }
        catch (...)
        {
        }
    };
    const auto submission = _executor->submit(std::move(task));
    return {submission, std::move(completion)};
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
