#include "PocoDDS/RuntimeCore/Codec.h"

#include <algorithm>
#include <chrono>
#include <limits>
#include <string>
#include <utility>

namespace PocoDDS::RuntimeCore
{
namespace
{
constexpr std::uint8_t wireVersion = 1;
constexpr std::int64_t noDeadline = std::numeric_limits<std::int64_t>::min();

RuntimeError codecError(RuntimeErrorCode code, std::string message)
{
    return {code, std::move(message), false};
}

void appendU8(std::vector<std::uint8_t>& output, std::uint8_t value) { output.push_back(value); }

void appendU32(std::vector<std::uint8_t>& output, std::uint32_t value)
{
    for (unsigned shift = 0; shift < 32; shift += 8)
        output.push_back(static_cast<std::uint8_t>((value >> shift) & 0xffU));
}

void appendI64(std::vector<std::uint8_t>& output, std::int64_t value)
{
    const auto bits = static_cast<std::uint64_t>(value);
    for (unsigned shift = 0; shift < 64; shift += 8)
        output.push_back(static_cast<std::uint8_t>((bits >> shift) & 0xffU));
}

Outcome<void> appendString(std::vector<std::uint8_t>& output, const std::string& value,
                           const MessageCodecLimits& limits)
{
    if (value.size() > limits.maximumStringBytes ||
        value.size() > std::numeric_limits<std::uint32_t>::max())
        return Outcome<void>::failure(
            codecError(RuntimeErrorCode::invalidArgument, "message string exceeds codec limit"));
    appendU32(output, static_cast<std::uint32_t>(value.size()));
    output.insert(output.end(), value.begin(), value.end());
    return Outcome<void>::success();
}

class Reader
{
  public:
    Reader(const std::vector<std::uint8_t>& input, const MessageCodecLimits& limits)
        : _input(input), _limits(limits)
    {
    }

    Outcome<std::uint8_t> u8()
    {
        if (!require(1))
            return Outcome<std::uint8_t>::failure(_error);
        return Outcome<std::uint8_t>::success(_input[_offset++]);
    }

    Outcome<std::uint32_t> u32()
    {
        if (!require(4))
            return Outcome<std::uint32_t>::failure(_error);
        std::uint32_t value = 0;
        for (unsigned shift = 0; shift < 32; shift += 8)
            value |= static_cast<std::uint32_t>(_input[_offset++]) << shift;
        return Outcome<std::uint32_t>::success(value);
    }

    Outcome<std::int64_t> i64()
    {
        if (!require(8))
            return Outcome<std::int64_t>::failure(_error);
        std::uint64_t value = 0;
        for (unsigned shift = 0; shift < 64; shift += 8)
            value |= static_cast<std::uint64_t>(_input[_offset++]) << shift;
        return Outcome<std::int64_t>::success(static_cast<std::int64_t>(value));
    }

    Outcome<std::string> string()
    {
        const auto size = u32();
        if (!size)
            return Outcome<std::string>::failure(size.error());
        if (size.value() > _limits.maximumStringBytes || !require(size.value()))
            return Outcome<std::string>::failure(
                size.value() > _limits.maximumStringBytes
                    ? codecError(RuntimeErrorCode::protocolError,
                                 "message string exceeds codec limit")
                    : _error);
        std::string value(reinterpret_cast<const char*>(_input.data() + _offset), size.value());
        _offset += size.value();
        return Outcome<std::string>::success(std::move(value));
    }

    Outcome<std::shared_ptr<const Payload>> payload()
    {
        const auto size = u32();
        if (!size)
            return Outcome<std::shared_ptr<const Payload>>::failure(size.error());
        if (!require(size.value()))
            return Outcome<std::shared_ptr<const Payload>>::failure(_error);
        auto value = std::make_shared<Payload>(
            _input.begin() + static_cast<std::ptrdiff_t>(_offset),
            _input.begin() + static_cast<std::ptrdiff_t>(_offset + size.value()));
        _offset += size.value();
        return Outcome<std::shared_ptr<const Payload>>::success(std::move(value));
    }

    bool complete() const noexcept { return _offset == _input.size(); }

  private:
    bool require(std::size_t size)
    {
        if (size <= _input.size() - _offset)
            return true;
        _error = codecError(RuntimeErrorCode::protocolError, "message frame is truncated");
        return false;
    }

    const std::vector<std::uint8_t>& _input;
    const MessageCodecLimits& _limits;
    std::size_t _offset{0};
    RuntimeError _error;
};

template <typename T> bool take(Outcome<T> value, T& destination, RuntimeError& error)
{
    if (!value)
    {
        error = value.error();
        return false;
    }
    destination = std::move(value).value();
    return true;
}
} // namespace

Outcome<std::vector<std::uint8_t>>
encodeMessageFrame(const TopicSpec& topic, const Message& message, const MessageCodecLimits& limits)
{
    if (limits.maximumFrameBytes < 32 || limits.maximumStringBytes == 0 ||
        limits.maximumHeaderCount == 0)
        return Outcome<std::vector<std::uint8_t>>::failure(
            codecError(RuntimeErrorCode::invalidArgument, "message codec limits are invalid"));
    if (topic.name.empty())
        return Outcome<std::vector<std::uint8_t>>::failure(
            codecError(RuntimeErrorCode::invalidArgument, "message topic name cannot be empty"));
    if (!topic.messageType.empty() && !message.type.empty() && topic.messageType != message.type)
        return Outcome<std::vector<std::uint8_t>>::failure(codecError(
            RuntimeErrorCode::invalidArgument, "message type does not match topic contract"));
    if (!topic.schemaVersion.empty() && !message.schemaVersion.empty() &&
        topic.schemaVersion != message.schemaVersion)
        return Outcome<std::vector<std::uint8_t>>::failure(
            codecError(RuntimeErrorCode::invalidArgument,
                       "message schema version does not match topic contract"));
    if (message.headers.size() > limits.maximumHeaderCount)
        return Outcome<std::vector<std::uint8_t>>::failure(codecError(
            RuntimeErrorCode::invalidArgument, "message header count exceeds codec limit"));

    std::vector<std::uint8_t> output{'P', 'D', 'R', 'M', wireVersion};
    output.reserve((message.payload ? message.payload->size() : 0U) + 256U);
    const auto append = [&](const std::string& value)
    { return appendString(output, value, limits); };
    for (const auto* value :
         {&topic.name, &topic.messageType, &topic.schemaVersion, &message.type,
          &message.schemaVersion, &message.context.messageId, &message.context.correlationId,
          &message.context.causationId, &message.context.traceParent})
    {
        const auto result = append(*value);
        if (!result)
            return Outcome<std::vector<std::uint8_t>>::failure(result.error());
    }
    appendU8(output, topic.delivery == Delivery::reliable ? 1 : 0);
    appendU8(output, topic.durable ? 1 : 0);
    appendU8(output, message.context.priority);
    std::int64_t remainingMilliseconds = noDeadline;
    if (message.context.deadline != std::chrono::steady_clock::time_point{})
    {
        const auto remaining = message.context.deadline - std::chrono::steady_clock::now();
        remainingMilliseconds =
            std::chrono::duration_cast<std::chrono::milliseconds>(remaining).count();
        if (remaining > std::chrono::steady_clock::duration::zero() && remainingMilliseconds == 0)
            remainingMilliseconds = 1;
    }
    appendI64(output, remainingMilliseconds);

    std::vector<std::pair<std::string, std::string>> headers(message.headers.begin(),
                                                             message.headers.end());
    std::sort(headers.begin(), headers.end());
    appendU32(output, static_cast<std::uint32_t>(headers.size()));
    for (const auto& [name, value] : headers)
    {
        const auto nameResult = append(name);
        const auto valueResult = append(value);
        if (!nameResult || !valueResult)
            return Outcome<std::vector<std::uint8_t>>::failure(!nameResult ? nameResult.error()
                                                                           : valueResult.error());
    }
    const auto payloadSize = message.payload ? message.payload->size() : 0U;
    if (payloadSize > std::numeric_limits<std::uint32_t>::max())
        return Outcome<std::vector<std::uint8_t>>::failure(codecError(
            RuntimeErrorCode::invalidArgument, "message payload exceeds protocol limit"));
    appendU32(output, static_cast<std::uint32_t>(payloadSize));
    if (message.payload)
        output.insert(output.end(), message.payload->begin(), message.payload->end());
    if (output.size() > limits.maximumFrameBytes)
        return Outcome<std::vector<std::uint8_t>>::failure(
            codecError(RuntimeErrorCode::invalidArgument, "message frame exceeds codec limit"));
    return Outcome<std::vector<std::uint8_t>>::success(std::move(output));
}

Outcome<DecodedMessageFrame> decodeMessageFrame(const std::vector<std::uint8_t>& frame,
                                                const MessageCodecLimits& limits)
{
    if (frame.size() > limits.maximumFrameBytes)
        return Outcome<DecodedMessageFrame>::failure(
            codecError(RuntimeErrorCode::protocolError, "message frame exceeds codec limit"));
    Reader reader(frame, limits);
    RuntimeError error;
    std::uint8_t magic[5]{};
    for (auto& value : magic)
    {
        if (!take(reader.u8(), value, error))
            return Outcome<DecodedMessageFrame>::failure(error);
    }
    if (magic[0] != 'P' || magic[1] != 'D' || magic[2] != 'R' || magic[3] != 'M' ||
        magic[4] != wireVersion)
        return Outcome<DecodedMessageFrame>::failure(codecError(
            RuntimeErrorCode::protocolError, "unsupported message frame signature or version"));

    DecodedMessageFrame decoded;
    for (auto* value :
         {&decoded.topic.name, &decoded.topic.messageType, &decoded.topic.schemaVersion,
          &decoded.message.type, &decoded.message.schemaVersion, &decoded.message.context.messageId,
          &decoded.message.context.correlationId, &decoded.message.context.causationId,
          &decoded.message.context.traceParent})
    {
        if (!take(reader.string(), *value, error))
            return Outcome<DecodedMessageFrame>::failure(error);
    }
    std::uint8_t delivery = 0;
    std::uint8_t durable = 0;
    if (!take(reader.u8(), delivery, error) || !take(reader.u8(), durable, error) ||
        !take(reader.u8(), decoded.message.context.priority, error))
        return Outcome<DecodedMessageFrame>::failure(error);
    if (delivery > 1 || durable > 1)
        return Outcome<DecodedMessageFrame>::failure(codecError(
            RuntimeErrorCode::protocolError, "message frame contains invalid topic flags"));
    decoded.topic.delivery = delivery ? Delivery::reliable : Delivery::bestEffort;
    decoded.topic.durable = durable != 0;
    std::int64_t remainingMilliseconds = 0;
    if (!take(reader.i64(), remainingMilliseconds, error))
        return Outcome<DecodedMessageFrame>::failure(error);
    if (remainingMilliseconds != noDeadline)
        decoded.message.context.deadline =
            std::chrono::steady_clock::now() + std::chrono::milliseconds(remainingMilliseconds);

    std::uint32_t headerCount = 0;
    if (!take(reader.u32(), headerCount, error))
        return Outcome<DecodedMessageFrame>::failure(error);
    if (headerCount > limits.maximumHeaderCount)
        return Outcome<DecodedMessageFrame>::failure(codecError(
            RuntimeErrorCode::protocolError, "message header count exceeds codec limit"));
    for (std::uint32_t index = 0; index < headerCount; ++index)
    {
        std::string name;
        std::string value;
        if (!take(reader.string(), name, error) || !take(reader.string(), value, error))
            return Outcome<DecodedMessageFrame>::failure(error);
        if (!decoded.message.headers.emplace(std::move(name), std::move(value)).second)
            return Outcome<DecodedMessageFrame>::failure(codecError(
                RuntimeErrorCode::protocolError, "message frame contains duplicate headers"));
    }
    if (!take(reader.payload(), decoded.message.payload, error))
        return Outcome<DecodedMessageFrame>::failure(error);
    if (!reader.complete())
        return Outcome<DecodedMessageFrame>::failure(
            codecError(RuntimeErrorCode::protocolError, "message frame contains trailing bytes"));
    if (decoded.topic.name.empty())
        return Outcome<DecodedMessageFrame>::failure(
            codecError(RuntimeErrorCode::protocolError, "decoded topic name cannot be empty"));
    if (!decoded.topic.messageType.empty() && !decoded.message.type.empty() &&
        decoded.topic.messageType != decoded.message.type)
        return Outcome<DecodedMessageFrame>::failure(codecError(
            RuntimeErrorCode::protocolError, "decoded message type does not match topic contract"));
    if (!decoded.topic.schemaVersion.empty() && !decoded.message.schemaVersion.empty() &&
        decoded.topic.schemaVersion != decoded.message.schemaVersion)
        return Outcome<DecodedMessageFrame>::failure(
            codecError(RuntimeErrorCode::protocolError,
                       "decoded message schema does not match topic contract"));
    return Outcome<DecodedMessageFrame>::success(std::move(decoded));
}

} // namespace PocoDDS::RuntimeCore
