#pragma once

#include <cstddef>
#include <cstdint>
#include <vector>

namespace PocoDDS::Protocols::XBee
{
enum class FrameType : std::uint8_t
{
    transmitRequest64 = 0x00,
    transmitRequest16 = 0x01,
    atCommand = 0x08,
    zigbeeTransmitRequest = 0x10,
    remoteAtCommandRequest = 0x17,
    receivePacket64 = 0x80,
    receivePacket16 = 0x81,
    atCommandResponse = 0x88,
    modemStatus = 0x8A,
    zigbeeTransmitStatus = 0x8B,
    zigbeeReceivePacket = 0x90,
    zigbeeIoSample = 0x92,
    nodeIdentification = 0x95,
    remoteAtCommandResponse = 0x97,
    invalid = 0xFF
};

enum class ParseStatus
{
    ok,
    notEnoughData,
    notFound,
    badChecksum
};

class XBeeFrame
{
public:
    static constexpr std::size_t MaxFrameLength = 1024;
    static constexpr std::uint8_t StartDelimiter = 0x7E;

    XBeeFrame();
    XBeeFrame(FrameType type, std::vector<std::uint8_t> data);

    FrameType type() const noexcept;
    const std::vector<std::uint8_t>& data() const noexcept;
    std::vector<std::uint8_t> encode(bool escaped = false) const;

    static ParseStatus parse(XBeeFrame& frame,
                             const std::uint8_t* bytes,
                             std::size_t size,
                             std::size_t& consumed,
                             bool escaped = false);

private:
    static std::vector<std::uint8_t> unescape(const std::uint8_t* bytes, std::size_t size);

    FrameType _type{FrameType::invalid};
    std::vector<std::uint8_t> _data;
};
} // namespace PocoDDS::Protocols::XBee
