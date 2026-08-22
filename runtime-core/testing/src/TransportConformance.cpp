#include "PocoDDS/RuntimeCore/Testing/TransportConformance.h"

#include <atomic>
#include <chrono>
#include <memory>
#include <stdexcept>

namespace PocoDDS::RuntimeCore::Testing
{
namespace
{
Outcome<TransportConformanceReport> failed(const std::string& id, std::string message)
{
    return Outcome<TransportConformanceReport>::failure(
        {RuntimeErrorCode::protocolError,
         "transport '" + id + "' conformance failure: " + std::move(message), false});
}

bool contains(const TransportCapabilities& actual, const TransportCapabilities& required)
{
    return (!required.inProcess || actual.inProcess) &&
           (!required.interProcess || actual.interProcess) &&
           (!required.distributed || actual.distributed) &&
           (!required.requestReply || actual.requestReply) &&
           (!required.durable || actual.durable) &&
           (!required.zeroCopyPayload || actual.zeroCopyPayload);
}
} // namespace

Outcome<TransportConformanceReport>
runTransportConformance(IMessageTransport& transport,
                        const TransportConformanceExpectations& expectations)
{
    TransportConformanceReport report;
    report.transportId = transport.id();
    if (report.transportId != expectations.id)
        return failed(report.transportId, "id does not match registered descriptor");
    report.passedChecks.push_back("identity");
    if (!contains(transport.capabilities(), expectations.requiredCapabilities))
        return failed(report.transportId, "required capability is not advertised");
    report.passedChecks.push_back("capabilities");

    static std::atomic<std::uint64_t> sequence{1};
    const auto suffix = std::to_string(sequence.fetch_add(1, std::memory_order_relaxed));
    const TopicSpec topic{"pdr.conformance." + suffix, "pdr.conformance.Message", "1",
                          Delivery::reliable, false};
    const auto payload = std::make_shared<const Payload>(Payload{1, 2, 3, 4});
    Message message{"pdr.conformance.Message", "1", payload, {}};
    message.context.messageId = "message-" + suffix;
    std::size_t observed = 0;
    bool zeroCopy = false;
    auto healthy = transport.subscribe(
        topic,
        [&](const TopicSpec& receivedTopic, const Message& receivedMessage)
        {
            if (receivedTopic.name != topic.name ||
                receivedMessage.context.messageId != message.context.messageId)
                throw std::runtime_error("topic or message context changed in transit");
            zeroCopy = receivedMessage.payload == payload;
            ++observed;
        });
    auto faulty = transport.subscribe(
        topic, [](const TopicSpec&, const Message&)
        { throw std::runtime_error("conformance injected subscriber failure"); });
    const auto published = transport.publish(topic, message);
    if (observed != 1 || published.accepted < 2 || published.delivered < 1 || published.failed < 1)
        return failed(report.transportId, "delivery or subscriber failure isolation is incorrect");
    if (expectations.requiredCapabilities.zeroCopyPayload && !zeroCopy)
        return failed(report.transportId, "zero-copy payload capability is not honored");
    report.passedChecks.push_back("delivery-and-failure-isolation");

    faulty.reset();
    healthy.reset();
    transport.publish(topic, message);
    if (observed != 1)
        return failed(report.transportId, "subscription cancellation did not stop delivery");
    report.passedChecks.push_back("subscription-lifetime");

    bool rejectedType = false;
    try
    {
        transport.publish(topic, Message{"pdr.conformance.Wrong", "1", payload, {}});
    }
    catch (const std::invalid_argument&)
    {
        rejectedType = true;
    }
    if (!rejectedType)
        return failed(report.transportId, "message type mismatch was not rejected");
    report.passedChecks.push_back("type-contract");

    bool rejectedDeadline = false;
    auto expired = message;
    expired.context.deadline = std::chrono::steady_clock::now() - std::chrono::milliseconds(1);
    try
    {
        transport.publish(topic, expired);
    }
    catch (const std::runtime_error&)
    {
        rejectedDeadline = true;
    }
    if (!rejectedDeadline)
        return failed(report.transportId, "expired message deadline was not rejected");
    report.passedChecks.push_back("deadline");

    bool rejectedHandler = false;
    try
    {
        transport.subscribe(topic, {});
    }
    catch (const std::invalid_argument&)
    {
        rejectedHandler = true;
    }
    if (!rejectedHandler)
        return failed(report.transportId, "empty subscription handler was not rejected");
    report.passedChecks.push_back("argument-validation");
    return Outcome<TransportConformanceReport>::success(std::move(report));
}

} // namespace PocoDDS::RuntimeCore::Testing
