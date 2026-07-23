#pragma once

#include "PocoDDS/Protocols/CAN/CanEndpoint.h"

#include <cstddef>
#include <cstdint>

namespace PocoDDS::Protocols::CAN
{
enum class BitOrder { littleEndian, bigEndian };

class SignalCodec
{
public:
    static std::uint64_t decodeUnsigned(
        const CanFrame& frame, std::size_t bitOffset,
        std::size_t bitLength, BitOrder order);
    static std::int64_t decodeSigned(
        const CanFrame& frame, std::size_t bitOffset,
        std::size_t bitLength, BitOrder order);
    static double decodeScaled(
        const CanFrame& frame, std::size_t bitOffset,
        std::size_t bitLength, BitOrder order, bool isSigned,
        double factor, double offset);
};
} // namespace PocoDDS::Protocols::CAN
