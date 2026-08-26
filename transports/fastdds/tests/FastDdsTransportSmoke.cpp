#include "PocoDDS/FastDdsTransport/FastDdsTransport.h"
#include "PocoDDS/FastDdsTransport/Registration.h"
#include "PocoDDS/RuntimeCore/Testing/TransportConformance.h"

#include <atomic>
#include <chrono>
#include <future>
#include <iostream>
#include <memory>
#include <string>
#include <thread>

int main()
{
    using namespace PocoDDS::FastDdsTransport;
    using namespace PocoDDS::RuntimeCore;
    using namespace PocoDDS::RuntimeCore::Testing;

    const auto domainId = static_cast<std::uint32_t>(
        170 + (std::chrono::steady_clock::now().time_since_epoch().count() % 50));
    FastDdsTransportOptions subscriberOptions;
    subscriberOptions.domainId = domainId;
    subscriberOptions.participantName = "pdr-transport-subscriber";
    FastDdsTransport subscriber(subscriberOptions);

    TopicSpec remoteTopic{"fastdds.remote", "example.Remote", "1", Delivery::reliable, false};
    std::promise<std::string> receivedMessageId;
    auto receivedFuture = receivedMessageId.get_future();
    std::atomic<bool> delivered{false};
    auto remoteSubscription = subscriber.subscribe(
        remoteTopic,
        [&receivedMessageId, &delivered](const TopicSpec&, const Message& message)
        {
            bool expected = false;
            if (delivered.compare_exchange_strong(expected, true))
                receivedMessageId.set_value(message.context.messageId);
        });
    if (!subscriber.start())
        return 1;

    FastDdsTransportOptions publisherOptions;
    publisherOptions.domainId = domainId;
    publisherOptions.participantName = "pdr-transport-publisher";
    FastDdsTransport publisher(publisherOptions);
    if (!publisher.start())
        return 2;

    Message message;
    message.type = remoteTopic.messageType;
    message.schemaVersion = remoteTopic.schemaVersion;
    message.payload = std::make_shared<const Payload>(Payload{0xde, 0xad, 0xbe, 0xef});
    message.context.messageId = "from-fastdds-peer";
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(5);
    PublishResult aggregate;
    while (receivedFuture.wait_for(std::chrono::milliseconds(0)) != std::future_status::ready &&
           std::chrono::steady_clock::now() < deadline)
    {
        const auto result = publisher.publish(remoteTopic, message);
        aggregate.accepted += result.accepted;
        aggregate.failed += result.failed;
        aggregate.dropped += result.dropped;
        std::this_thread::sleep_for(std::chrono::milliseconds(50));
    }
    if (receivedFuture.wait_for(std::chrono::milliseconds(0)) != std::future_status::ready ||
        receivedFuture.get() != "from-fastdds-peer")
    {
        std::cerr << "FAST_DDS_TRANSPORT_FAIL peer timeout accepted=" << aggregate.accepted
                  << " failed=" << aggregate.failed << " dropped=" << aggregate.dropped << '\n';
        publisher.stop();
        subscriber.stop();
        return 3;
    }
    remoteSubscription.reset();

    const auto conformance =
        runTransportConformance(publisher, {"fastdds", {false, false, true, false, false, false}});
    TopicSpec oversizedTopic{"fastdds.oversized", "example.Large", "1"};
    Message oversized;
    oversized.type = oversizedTopic.messageType;
    oversized.payload =
        std::make_shared<const Payload>(181U * 1024U, static_cast<std::uint8_t>(0xaa));
    const auto oversizedResult = publisher.publish(oversizedTopic, oversized);
    publisher.stop();
    subscriber.stop();
    if (!conformance || conformance.value().passedChecks.size() != 7 ||
        oversizedResult.dropped != 1)
    {
        std::cerr << "FAST_DDS_TRANSPORT_FAIL conformance="
                  << (conformance ? "incomplete" : conformance.error().message) << '\n';
        return 4;
    }

    TransportRegistry registry;
    auto registration = registerFastDdsTransport(registry);
    if (!registration || registry.descriptors().size() != 1 ||
        registry.descriptors().front().id != "fastdds" ||
        registry.descriptors().front().configurationKeys.size() != 4)
        return 5;
    const auto invalid = registry.create("fastdds", {{"domainId", "233"}});
    if (invalid || invalid.error().code != RuntimeErrorCode::invalidArgument)
        return 6;
    const auto unknownKey = registry.create("fastdds", {{"discovreyMode", "simple"}});
    const auto invalidMaximum =
        registry.create("fastdds", {{"maximumFrameBytes", "184321"}});
    if (unknownKey || invalidMaximum)
        return 7;

    std::cout << "PDR_FASTDDS_TRANSPORT_PASS codec=PDRM/1 peer=bidirectional conformance=7 "
                 "registry=verified strictConfig=verified\n";
    return 0;
}
