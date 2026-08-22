#include "PocoDDS/RuntimeCore/InProcessTransport.h"

#include <iostream>
#include <memory>
#include <stdexcept>

int main()
{
    using namespace PocoDDS::RuntimeCore;

    InProcessTransport transport;
    const TopicSpec topic{"orders.created", "example.OrderCreated", "1", Delivery::reliable, false};
    auto payload = std::make_shared<const Payload>(Payload{1, 2, 3, 4});
    Message message{"example.OrderCreated", "1", payload, {{"trace-id", "trace-1"}}};
    std::size_t observed = 0;
    auto first = transport.subscribe(
        topic,
        [&](const TopicSpec& receivedTopic, const Message& received)
        {
            if (receivedTopic.name != topic.name || received.payload != payload)
                throw std::runtime_error("in-process delivery copied or rerouted the payload");
            ++observed;
        });
    auto faulty = transport.subscribe(topic, [](const TopicSpec&, const Message&)
                                      { throw std::runtime_error("injected subscriber failure"); });

    const auto result = transport.publish(topic, message);
    if (result.accepted != 2 || result.delivered != 1 || result.failed != 1 ||
        result.dropped != 0 || observed != 1)
        return 1;
    if (!transport.capabilities().inProcess || !transport.capabilities().zeroCopyPayload ||
        transport.capabilities().distributed)
        return 2;
    faulty.reset();
    first.reset();
    if (transport.subscriptionCount() != 0)
        return 3;

    try
    {
        transport.publish(topic, Message{"wrong.Type", "1", payload, {}});
        return 4;
    }
    catch (const std::invalid_argument&)
    {
    }

    std::cout << "PDR_RUNTIME_CORE_INPROC_PASS delivered=" << result.delivered
              << " isolatedFailures=" << result.failed << '\n';
    return 0;
}
