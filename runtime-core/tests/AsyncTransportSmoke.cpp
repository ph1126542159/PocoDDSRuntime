#include "PocoDDS/RuntimeCore/InProcessTransport.h"

#include <chrono>
#include <future>
#include <iostream>
#include <memory>

namespace
{
PocoDDS::RuntimeCore::Message makeMessage(const std::string& id)
{
    using namespace PocoDDS::RuntimeCore;
    Message message{"example.Event", "1", std::make_shared<const Payload>(Payload{1}), {}};
    message.context.messageId = id;
    return message;
}
} // namespace

int main()
{
    using namespace PocoDDS::RuntimeCore;

    ThreadPoolExecutor::Options options;
    options.workerCount = 1;
    options.queueCapacity = 1;
    options.overflowPolicy = OverflowPolicy::dropOldest;
    auto executor = std::make_shared<ThreadPoolExecutor>(options);
    InProcessTransport transport(executor);
    const TopicSpec topic{"events", "example.Event", "1", Delivery::reliable, false};

    auto release = std::make_shared<std::promise<void>>();
    auto releaseFuture = release->get_future().share();
    auto started = std::make_shared<std::promise<void>>();
    auto startedFuture = started->get_future();
    auto subscription =
        transport.subscribe(topic,
                            [started, releaseFuture](const TopicSpec&, const Message& message)
                            {
                                if (message.context.messageId == "first")
                                {
                                    started->set_value();
                                    releaseFuture.wait();
                                }
                            });

    auto first = transport.publishAsync(topic, makeMessage("first"));
    if (!first.accepted())
        return 1;
    startedFuture.wait();
    auto displaced = transport.publishAsync(topic, makeMessage("displaced"));
    auto newest = transport.publishAsync(topic, makeMessage("newest"));
    if (!displaced.accepted() || newest.submission != SubmitStatus::acceptedAfterDroppingOldest)
        return 2;

    const auto displacedOutcome = displaced.completion.get();
    if (displacedOutcome || displacedOutcome.error().code != RuntimeErrorCode::queueFull)
        return 3;
    release->set_value();
    const auto firstOutcome = first.completion.get();
    const auto newestOutcome = newest.completion.get();
    if (!firstOutcome || !newestOutcome || firstOutcome.value().delivered != 1 ||
        newestOutcome.value().delivered != 1)
        return 4;

    Message expired = makeMessage("expired");
    expired.context.deadline = std::chrono::steady_clock::now() - std::chrono::milliseconds(1);
    auto expiredTicket = transport.publishAsync(topic, expired);
    const auto expiredOutcome = expiredTicket.completion.get();
    if (expiredOutcome || expiredOutcome.error().code != RuntimeErrorCode::timeout)
        return 5;

    executor->shutdown(ShutdownMode::drain);
    std::cout << "PDR_RUNTIME_CORE_ASYNC_PASS dropped=1 deadline=timeout\n";
    return 0;
}
