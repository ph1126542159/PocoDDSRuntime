#include "PocoDDS/FastDdsTransport/FastDdsTransport.h"

#include <chrono>
#include <cstdint>
#include <functional>
#include <iostream>
#include <memory>
#include <mutex>
#include <set>
#include <string>
#include <thread>
#include <utility>

namespace
{
bool publishUntil(
    PocoDDS::FastDdsTransport::FastDdsTransport& publisher,
    const PocoDDS::RuntimeCore::TopicSpec& topic,
    const PocoDDS::RuntimeCore::Message& message,
    const std::function<bool()>& delivered,
    std::chrono::steady_clock::duration timeout)
{
    const auto deadline = std::chrono::steady_clock::now() + timeout;
    while (!delivered() && std::chrono::steady_clock::now() < deadline)
    {
        publisher.publish(topic, message);
        std::this_thread::sleep_for(std::chrono::milliseconds(50));
    }
    return delivered();
}
} // namespace

int main()
{
    using namespace PocoDDS::FastDdsTransport;
    using namespace PocoDDS::RuntimeCore;

    const auto domainId = static_cast<std::uint32_t>(
        220 + (std::chrono::steady_clock::now().time_since_epoch().count() % 10));
    FastDdsTransportOptions publisherOptions;
    publisherOptions.domainId = domainId;
    publisherOptions.participantName = "pdr-recovery-publisher";
    FastDdsTransport publisher(publisherOptions);
    if (!publisher.start())
        return 1;

    FastDdsTransportOptions subscriberOptions;
    subscriberOptions.domainId = domainId;
    subscriberOptions.participantName = "pdr-recovery-subscriber";
    FastDdsTransport subscriber(subscriberOptions);
    const TopicSpec topic{"fastdds.peer-recovery", "example.Recovery", "1",
                          Delivery::reliable, false};
    std::mutex mutex;
    std::set<std::string> received;
    auto subscription = subscriber.subscribe(
        topic, [&](const TopicSpec&, const Message& message)
        {
            std::lock_guard<std::mutex> lock(mutex);
            received.insert(message.context.messageId);
        });
    if (!subscriber.start())
    {
        publisher.stop();
        return 2;
    }

    const auto makeMessage = [&topic](std::string id, std::uint8_t value)
    {
        Message message;
        message.type = topic.messageType;
        message.schemaVersion = topic.schemaVersion;
        message.context.messageId = std::move(id);
        message.payload = std::make_shared<const Payload>(Payload{value});
        return message;
    };
    const auto beforeRestart = makeMessage("before-restart", 0x10);
    const auto afterRestart = makeMessage("after-restart", 0x20);
    const auto hasMessage = [&](const std::string& id)
    {
        std::lock_guard<std::mutex> lock(mutex);
        return received.count(id) != 0;
    };

    const bool firstDelivered = publishUntil(
        publisher, topic, beforeRestart,
        [&] { return hasMessage("before-restart"); }, std::chrono::seconds(6));
    subscriber.stop();
    const bool participantStopped = !subscriber.running();
    const bool publisherContinuousBefore = publisher.running();
    const auto restarted = subscriber.start();
    const bool participantRestarted = restarted && subscriber.running();
    const bool secondDelivered = participantRestarted && publishUntil(
        publisher, topic, afterRestart,
        [&] { return hasMessage("after-restart"); }, std::chrono::seconds(6));
    const bool publisherContinuous = publisherContinuousBefore && publisher.running();

    subscription.reset();
    subscriber.stop();
    publisher.stop();
    std::size_t uniqueDeliveries = 0;
    {
        std::lock_guard<std::mutex> lock(mutex);
        uniqueDeliveries = received.size();
    }
    if (!firstDelivered || !participantStopped || !participantRestarted ||
        !secondDelivered || !publisherContinuous || uniqueDeliveries != 2)
    {
        std::cerr << "FAST_DDS_TRANSPORT_RECOVERY_FAIL first=" << firstDelivered
                  << " stopped=" << participantStopped
                  << " restarted=" << participantRestarted
                  << " second=" << secondDelivered
                  << " publisherContinuous=" << publisherContinuous
                  << " delivery=" << uniqueDeliveries << '\n';
        return 3;
    }
    std::cout << "PDR_FASTDDS_TRANSPORT_RECOVERY_PASS peerRestart=1 "
                 "subscriptionRestored=1 publisherContinuous=1 delivery=2\n";
    return 0;
}
