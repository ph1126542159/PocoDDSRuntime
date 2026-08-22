#include "PocoDDS/RuntimeCore/Codec.h"

#include <chrono>
#include <iostream>
#include <memory>

int main()
{
    using namespace PocoDDS::RuntimeCore;

    const TopicSpec topic{"orders.created", "example.OrderCreated", "2", Delivery::reliable, true};
    Message message{"example.OrderCreated",
                    "2",
                    std::make_shared<const Payload>(Payload{0, 1, 2, 0, 255}),
                    {{"z-header", "last"}, {"a-header", "first"}}};
    message.context.messageId = "message-1";
    message.context.correlationId = "correlation-1";
    message.context.causationId = "causation-1";
    message.context.traceParent = "00-0123456789abcdef0123456789abcdef-0123456789abcdef-01";
    message.context.priority = 7;

    const auto encoded = encodeMessageFrame(topic, message);
    const auto encodedAgain = encodeMessageFrame(topic, message);
    if (!encoded || !encodedAgain || encoded.value() != encodedAgain.value())
        return 1;
    const auto decoded = decodeMessageFrame(encoded.value());
    if (!decoded || decoded.value().topic.name != topic.name ||
        decoded.value().topic.delivery != Delivery::reliable || !decoded.value().topic.durable ||
        decoded.value().message.type != message.type ||
        decoded.value().message.headers != message.headers || !decoded.value().message.payload ||
        *decoded.value().message.payload != *message.payload ||
        decoded.value().message.context.messageId != message.context.messageId ||
        decoded.value().message.context.priority != 7 ||
        decoded.value().message.context.deadline != std::chrono::steady_clock::time_point{})
        return 2;

    auto deadlineMessage = message;
    deadlineMessage.context.deadline = std::chrono::steady_clock::now() + std::chrono::seconds(5);
    const auto deadlineEncoded = encodeMessageFrame(topic, deadlineMessage);
    const auto deadlineDecoded =
        deadlineEncoded ? decodeMessageFrame(deadlineEncoded.value())
                        : Outcome<DecodedMessageFrame>::failure(deadlineEncoded.error());
    if (!deadlineDecoded ||
        deadlineDecoded.value().message.context.deadline <= std::chrono::steady_clock::now())
        return 7;

    auto corrupted = encoded.value();
    corrupted[4] = 99;
    const auto invalidVersion = decodeMessageFrame(corrupted);
    if (invalidVersion || invalidVersion.error().code != RuntimeErrorCode::protocolError)
        return 3;
    corrupted = encoded.value();
    corrupted.pop_back();
    const auto truncated = decodeMessageFrame(corrupted);
    if (truncated || truncated.error().code != RuntimeErrorCode::protocolError)
        return 4;
    MessageCodecLimits small;
    small.maximumFrameBytes = 64;
    const auto oversized = encodeMessageFrame(topic, message, small);
    if (oversized || oversized.error().code != RuntimeErrorCode::invalidArgument)
        return 5;
    const auto wrongType =
        encodeMessageFrame(topic, Message{"example.Wrong", "2", message.payload, {}});
    if (wrongType || wrongType.error().code != RuntimeErrorCode::invalidArgument)
        return 6;

    std::cout
        << "PDR_MESSAGE_CODEC_PASS deterministic=true binaryPayload=true corruption=rejected\n";
    return 0;
}
