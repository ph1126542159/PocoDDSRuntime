#include "PocoDDS/Protocols/XBee/IoSample.h"

#include <iomanip>
#include <sstream>
#include <stdexcept>

namespace PocoDDS::Protocols::XBee
{
namespace
{
std::uint16_t readU16(const std::vector<std::uint8_t>& data, std::size_t& offset)
{
    if (offset + 2 > data.size())
        throw std::invalid_argument("truncated XBee IO sample");
    const auto value = static_cast<std::uint16_t>(
        (static_cast<std::uint16_t>(data[offset]) << 8U) | data[offset + 1]);
    offset += 2;
    return value;
}
}

bool IoSample::hasDigital(unsigned channel) const noexcept
{
    return channel < 16 && (digitalChannelMask & (1U << channel)) != 0;
}

bool IoSample::digital(unsigned channel) const
{
    if (!hasDigital(channel))
        throw std::out_of_range("XBee digital channel is not present");
    return (digitalSamples & (1U << channel)) != 0;
}

bool IoSample::hasAnalog(unsigned channel) const noexcept
{
    return channel < analogSamples.size() && (analogChannelMask & (1U << channel)) != 0;
}

std::uint16_t IoSample::analog(unsigned channel) const
{
    if (!hasAnalog(channel))
        throw std::out_of_range("XBee analog channel is not present");
    return analogSamples[channel];
}

std::string IoSample::addressString() const
{
    std::ostringstream stream;
    stream << std::uppercase << std::hex << std::setw(16) << std::setfill('0')
           << sourceAddress;
    return stream.str();
}

IoSample IoSample::decode(const XBeeFrame& frame)
{
    if (frame.type() != FrameType::zigbeeIoSample)
        throw std::invalid_argument("XBee frame is not a Zigbee IO sample");
    const auto& data = frame.data();
    if (data.size() < 15)
        throw std::invalid_argument("truncated XBee IO sample header");

    IoSample sample;
    std::size_t offset = 0;
    for (int i = 0; i < 8; ++i)
        sample.sourceAddress = (sample.sourceAddress << 8U) | data[offset++];
    sample.networkAddress = readU16(data, offset);
    sample.receiveOptions = data[offset++];
    if (data[offset++] != 1)
        throw std::invalid_argument("only single XBee IO samples are supported");
    sample.digitalChannelMask = readU16(data, offset);
    sample.analogChannelMask = data[offset++];
    if (sample.digitalChannelMask != 0)
        sample.digitalSamples = readU16(data, offset);
    for (unsigned channel = 0; channel < sample.analogSamples.size(); ++channel)
        if (sample.hasAnalog(channel))
            sample.analogSamples[channel] = readU16(data, offset);
    if (offset != data.size())
        throw std::invalid_argument("unexpected bytes after XBee IO sample");
    return sample;
}
} // namespace PocoDDS::Protocols::XBee
