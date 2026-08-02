#include "PocoDDS/Protocols/Serial/SerialChannel.h"
#include "PocoDDS/Protocols/ProtocolMetrics.h"

#include <stdexcept>
#include <utility>

namespace PocoDDS::Protocols::Serial
{
SerialChannel::SerialChannel(std::string device,
                             int baudRate,
                             std::string parameters,
                             Poco::Serial::SerialPort::FlowControl flowControl)
    : _device(std::move(device)), _baudRate(baudRate), _parameters(std::move(parameters)),
      _flowControl(flowControl)
{
}

SerialChannel::~SerialChannel()
{
    close();
}

std::string SerialChannel::name() const
{
    return "serial:" + _device;
}

void SerialChannel::open()
{
    if (_open.load())
        return;
    PocoDDS::Protocols::ProtocolMetricTimer metric("serial", "open");
    _port.open(_device, _baudRate, _parameters, _flowControl);
    _open = true;
    metric.success();
}

void SerialChannel::close() noexcept
{
    if (!_open.exchange(false))
        return;
    try
    {
        _port.close();
    }
    catch (...)
    {
    }
}

bool SerialChannel::isOpen() const noexcept
{
    return _open.load();
}

std::size_t SerialChannel::write(const std::uint8_t* data, std::size_t size)
{
    PocoDDS::Protocols::ProtocolMetricTimer metric("serial", "write", size);
    if (!_open.load())
        throw std::logic_error("serial channel is not open");
    try
    {
        const auto written = _port.write(reinterpret_cast<const char*>(data), size);
        metric.success();
        return written;
    }
    catch (...)
    {
        close();
        throw;
    }
}

std::vector<std::uint8_t> SerialChannel::read(std::size_t size, Poco::Timespan timeout)
{
    PocoDDS::Protocols::ProtocolMetricTimer metric("serial", "read");
    if (!_open.load())
        throw std::logic_error("serial channel is not open");
    try
    {
        std::vector<std::uint8_t> bytes(size);
        const auto read =
            _port.read(reinterpret_cast<char*>(bytes.data()), bytes.size(), timeout);
        bytes.resize(read);
        if (read == 0) metric.timeout(); else metric.success();
        return bytes;
    }
    catch (...)
    {
        close();
        throw;
    }
}

Poco::Serial::SerialPort& SerialChannel::port() noexcept
{
    return _port;
}
} // namespace PocoDDS::Protocols::Serial
