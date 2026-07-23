#include "PocoDDS/Protocols/XBee/XBeePort.h"

#include <stdexcept>
#include <utility>

namespace PocoDDS::Protocols::XBee
{
XBeePort::XBeePort(
    std::shared_ptr<PocoDDS::Protocols::Serial::SerialChannel> serial,
    bool escapedApiMode)
    : _serial(std::move(serial)), _escapedApiMode(escapedApiMode)
{
    if (!_serial)
        throw std::invalid_argument("serial channel is required");
}

std::string XBeePort::name() const
{
    return "xbee:" + _serial->name();
}

void XBeePort::open()
{
    _serial->open();
}

void XBeePort::close() noexcept
{
    _serial->close();
}

bool XBeePort::isOpen() const noexcept
{
    return _serial->isOpen();
}

void XBeePort::send(const XBeeFrame& frame)
{
    const auto wire = frame.encode(_escapedApiMode);
    if (_serial->write(wire.data(), wire.size()) != wire.size())
        throw std::runtime_error("incomplete XBee frame write");
}

bool XBeePort::receive(XBeeFrame& frame, Poco::Timespan timeout)
{
    std::vector<std::uint8_t> buffer;
    buffer.reserve(XBeeFrame::MaxFrameLength * 2);
    while (buffer.size() < XBeeFrame::MaxFrameLength * 2)
    {
        const auto chunk = _serial->read(64, timeout);
        if (chunk.empty())
            return false;
        buffer.insert(buffer.end(), chunk.begin(), chunk.end());
        std::size_t consumed = 0;
        const auto result = XBeeFrame::parse(
            frame, buffer.data(), buffer.size(), consumed, _escapedApiMode);
        if (result == ParseStatus::ok)
            return true;
        if (result == ParseStatus::badChecksum)
            throw std::runtime_error("invalid XBee frame checksum");
    }
    throw std::runtime_error("XBee frame exceeds receive buffer");
}
} // namespace PocoDDS::Protocols::XBee
