#pragma once

#include <cstdint>
#include <string>

namespace PocoDDS::FastDDS
{
struct Envelope
{
    std::uint64_t sequence{0};
    std::int64_t timestampMicroseconds{0};
    std::string kind;
    std::string deviceId;
    std::string operation;
    std::string payload;
    std::string correlationId;
    std::string traceParent;
    std::string traceState;
    std::string businessName;
    std::string businessInstanceId;
    std::int32_t status{0};
};
} // namespace PocoDDS::FastDDS
