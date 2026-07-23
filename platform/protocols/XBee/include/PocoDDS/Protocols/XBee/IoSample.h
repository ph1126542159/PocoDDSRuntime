#pragma once

#include "PocoDDS/Protocols/XBee/XBeeFrame.h"

#include <array>
#include <cstdint>
#include <string>

namespace PocoDDS::Protocols::XBee
{
struct IoSample
{
    std::uint64_t sourceAddress{0};
    std::uint16_t networkAddress{0};
    std::uint8_t receiveOptions{0};
    std::uint16_t digitalChannelMask{0};
    std::uint8_t analogChannelMask{0};
    std::uint16_t digitalSamples{0};
    std::array<std::uint16_t, 8> analogSamples{};

    bool hasDigital(unsigned channel) const noexcept;
    bool digital(unsigned channel) const;
    bool hasAnalog(unsigned channel) const noexcept;
    std::uint16_t analog(unsigned channel) const;
    std::string addressString() const;
    static IoSample decode(const XBeeFrame& frame);
};
} // namespace PocoDDS::Protocols::XBee
