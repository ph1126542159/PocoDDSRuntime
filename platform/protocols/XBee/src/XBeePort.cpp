#include "PocoDDS/Protocols/XBee/XBeePort.h"
#include "PocoDDS/Protocols/ProtocolMetrics.h"

#include <stdexcept>
#include <utility>

namespace PocoDDS::Protocols::XBee
{
XBeePort::XBeePort(
    std::shared_ptr<PocoDDS::Protocols::Serial::ISerialChannel> serial,
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
    _receiveBuffer.clear();
    _serial->open();
}

void XBeePort::close() noexcept
{
    _serial->close();
    _receiveBuffer.clear();
}

bool XBeePort::isOpen() const noexcept
{
    return _serial->isOpen();
}

void XBeePort::send(const XBeeFrame& frame)
{
    const auto wire = frame.encode(_escapedApiMode);
    PocoDDS::Protocols::ProtocolMetricTimer metric("xbee", "send", wire.size());
    if (_serial->write(wire.data(), wire.size()) != wire.size())
        throw std::runtime_error("incomplete XBee frame write");
    metric.success();
}

bool XBeePort::receive(XBeeFrame& frame, Poco::Timespan timeout)
{
    PocoDDS::Protocols::ProtocolMetricTimer metric("xbee", "receive");
    _receiveBuffer.reserve(XBeeFrame::MaxFrameLength * 2);
    while (_receiveBuffer.size() < XBeeFrame::MaxFrameLength * 2)
    {
        std::size_t consumed = 0;
        const auto result = XBeeFrame::parse(
            frame, _receiveBuffer.data(), _receiveBuffer.size(), consumed,
            _escapedApiMode);
        if (result == ParseStatus::ok)
        {
            _receiveBuffer.erase(_receiveBuffer.begin(),
                                 _receiveBuffer.begin() + consumed);
            metric.success();
            return true;
        }
        if (result == ParseStatus::badChecksum)
        {
            _receiveBuffer.erase(_receiveBuffer.begin(),
                                 _receiveBuffer.begin() + consumed);
            throw std::runtime_error("invalid XBee frame checksum");
        }
        if ((result == ParseStatus::notFound ||
             result == ParseStatus::notEnoughData) && consumed > 0)
        {
            _receiveBuffer.erase(_receiveBuffer.begin(),
                                 _receiveBuffer.begin() + consumed);
            if (result == ParseStatus::notFound) continue;
        }

        const auto chunk = _serial->read(64, timeout);
        if (chunk.empty())
        {
            metric.timeout();
            return false;
        }
        _receiveBuffer.insert(_receiveBuffer.end(), chunk.begin(), chunk.end());
    }
    throw std::runtime_error("XBee frame exceeds receive buffer");
}
} // namespace PocoDDS::Protocols::XBee
