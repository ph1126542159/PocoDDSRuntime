#pragma once

#include "PocoDDS/RuntimeCore/Contract.h"
#include "PocoDDS/RuntimeCore/Export.h"
#include "PocoDDS/RuntimeCore/Transport.h"

#include <cstddef>
#include <cstdint>
#include <vector>

namespace PocoDDS::RuntimeCore
{

struct MessageCodecLimits
{
    std::size_t maximumFrameBytes{16U * 1024U * 1024U};
    std::size_t maximumStringBytes{1024U * 1024U};
    std::size_t maximumHeaderCount{1024};
};

struct DecodedMessageFrame
{
    TopicSpec topic;
    Message message;
};

PDR_RUNTIME_CORE_API Outcome<std::vector<std::uint8_t>>
encodeMessageFrame(const TopicSpec& topic, const Message& message,
                   const MessageCodecLimits& limits = {});

PDR_RUNTIME_CORE_API Outcome<DecodedMessageFrame>
decodeMessageFrame(const std::vector<std::uint8_t>& frame, const MessageCodecLimits& limits = {});

} // namespace PocoDDS::RuntimeCore
