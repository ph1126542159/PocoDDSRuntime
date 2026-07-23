#include "PocoDDS/Protocols/XBee/XBeeFrame.h"

#include <algorithm>
#include <stdexcept>
#include <utility>

namespace PocoDDS::Protocols::XBee
{
namespace
{
bool requiresEscape(std::uint8_t byte)
{
    return byte == 0x7E || byte == 0x7D || byte == 0x11 || byte == 0x13;
}
} // namespace

XBeeFrame::XBeeFrame() = default;

XBeeFrame::XBeeFrame(FrameType type, std::vector<std::uint8_t> data)
    : _type(type), _data(std::move(data))
{
    if (_data.size() + 5 > MaxFrameLength)
        throw std::out_of_range("XBee frame exceeds maximum size");
}

FrameType XBeeFrame::type() const noexcept
{
    return _type;
}

const std::vector<std::uint8_t>& XBeeFrame::data() const noexcept
{
    return _data;
}

std::vector<std::uint8_t> XBeeFrame::encode(bool escaped) const
{
    const auto length = _data.size() + 1;
    std::vector<std::uint8_t> raw{
        StartDelimiter,
        static_cast<std::uint8_t>(length >> 8),
        static_cast<std::uint8_t>(length),
        static_cast<std::uint8_t>(_type)};
    raw.insert(raw.end(), _data.begin(), _data.end());
    std::uint32_t sum = static_cast<std::uint8_t>(_type);
    for (const auto byte : _data)
        sum += byte;
    raw.push_back(static_cast<std::uint8_t>(0xFF - (sum & 0xFF)));
    if (!escaped)
        return raw;

    std::vector<std::uint8_t> result;
    result.reserve(raw.size() * 2);
    result.push_back(raw.front());
    for (auto iterator = raw.begin() + 1; iterator != raw.end(); ++iterator)
    {
        if (requiresEscape(*iterator))
        {
            result.push_back(0x7D);
            result.push_back(*iterator ^ 0x20);
        }
        else
        {
            result.push_back(*iterator);
        }
    }
    return result;
}

ParseStatus XBeeFrame::parse(XBeeFrame& frame,
                             const std::uint8_t* bytes,
                             std::size_t size,
                             std::size_t& consumed,
                             bool escaped)
{
    consumed = 0;
    if (!bytes || size == 0)
        return ParseStatus::notEnoughData;
    std::vector<std::uint8_t> decoded;
    if (escaped)
    {
        decoded = unescape(bytes, size);
        bytes = decoded.data();
        size = decoded.size();
    }

    const auto start = std::find(bytes, bytes + size, StartDelimiter);
    if (start == bytes + size)
    {
        consumed = size;
        return ParseStatus::notFound;
    }
    const std::size_t offset = static_cast<std::size_t>(start - bytes);
    if (size - offset < 4)
        return ParseStatus::notEnoughData;
    const std::size_t length =
        (static_cast<std::size_t>(start[1]) << 8) | start[2];
    if (length == 0 || length + 4 > MaxFrameLength)
    {
        consumed = offset + 1;
        return ParseStatus::notFound;
    }
    const std::size_t total = 3 + length + 1;
    if (size - offset < total)
        return ParseStatus::notEnoughData;

    std::uint32_t sum = 0;
    for (std::size_t i = 3; i < total; ++i)
        sum += start[i];
    consumed = offset + total;
    if ((sum & 0xFF) != 0xFF)
        return ParseStatus::badChecksum;

    frame = XBeeFrame(static_cast<FrameType>(start[3]),
                      std::vector<std::uint8_t>(start + 4, start + 3 + length));
    return ParseStatus::ok;
}

std::vector<std::uint8_t> XBeeFrame::unescape(const std::uint8_t* bytes, std::size_t size)
{
    std::vector<std::uint8_t> result;
    result.reserve(size);
    bool escape = false;
    for (std::size_t i = 0; i < size; ++i)
    {
        if (i == 0)
        {
            result.push_back(bytes[i]);
            continue;
        }
        if (escape)
        {
            result.push_back(bytes[i] ^ 0x20);
            escape = false;
        }
        else if (bytes[i] == 0x7D)
        {
            escape = true;
        }
        else
        {
            result.push_back(bytes[i]);
        }
    }
    return result;
}
} // namespace PocoDDS::Protocols::XBee
