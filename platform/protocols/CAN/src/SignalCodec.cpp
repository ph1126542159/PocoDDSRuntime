#include "PocoDDS/Protocols/CAN/SignalCodec.h"

#include <stdexcept>

namespace PocoDDS::Protocols::CAN
{
std::uint64_t SignalCodec::decodeUnsigned(
    const CanFrame& frame, std::size_t bitOffset,
    std::size_t bitLength, BitOrder order)
{
    if (bitLength == 0 || bitLength > 64 ||
        bitOffset + bitLength > static_cast<std::size_t>(frame.length) * 8)
        throw std::out_of_range("CAN signal exceeds frame payload");

    std::uint64_t value = 0;
    if (order == BitOrder::littleEndian)
    {
        for (std::size_t i = 0; i < bitLength; ++i)
        {
            const auto absolute = bitOffset + i;
            const auto bit = (frame.data[absolute / 8] >> (absolute % 8)) & 1U;
            value |= static_cast<std::uint64_t>(bit) << i;
        }
    }
    else
    {
        std::size_t byte = bitOffset / 8;
        int bit = static_cast<int>(bitOffset % 8);
        for (std::size_t i = 0; i < bitLength; ++i)
        {
            value = (value << 1U) |
                    ((frame.data[byte] >> static_cast<unsigned>(bit)) & 1U);
            if (bit == 0)
            {
                ++byte;
                bit = 7;
            }
            else
                --bit;
        }
    }
    return value;
}

std::int64_t SignalCodec::decodeSigned(
    const CanFrame& frame, std::size_t bitOffset,
    std::size_t bitLength, BitOrder order)
{
    const auto raw = decodeUnsigned(frame, bitOffset, bitLength, order);
    if (bitLength == 64)
        return static_cast<std::int64_t>(raw);
    const auto sign = std::uint64_t{1} << (bitLength - 1);
    return static_cast<std::int64_t>((raw ^ sign) - sign);
}

double SignalCodec::decodeScaled(
    const CanFrame& frame, std::size_t bitOffset,
    std::size_t bitLength, BitOrder order, bool isSigned,
    double factor, double offset)
{
    const double raw = isSigned
        ? static_cast<double>(decodeSigned(frame, bitOffset, bitLength, order))
        : static_cast<double>(decodeUnsigned(frame, bitOffset, bitLength, order));
    return raw * factor + offset;
}
} // namespace PocoDDS::Protocols::CAN
