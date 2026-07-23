#include "PocoDDS/Protocols/Serial/SerialChannel.h"

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
    if (_open)
        return;
    _port.open(_device, _baudRate, _parameters, _flowControl);
    _open = true;
}

void SerialChannel::close() noexcept
{
    if (!_open)
        return;
    try
    {
        _port.close();
    }
    catch (...)
    {
    }
    _open = false;
}

bool SerialChannel::isOpen() const noexcept
{
    return _open;
}

std::size_t SerialChannel::write(const std::uint8_t* data, std::size_t size)
{
    if (!_open)
        throw std::logic_error("serial channel is not open");
    return _port.write(reinterpret_cast<const char*>(data), size);
}

std::vector<std::uint8_t> SerialChannel::read(std::size_t size, Poco::Timespan timeout)
{
    if (!_open)
        throw std::logic_error("serial channel is not open");
    std::vector<std::uint8_t> bytes(size);
    const auto read =
        _port.read(reinterpret_cast<char*>(bytes.data()), bytes.size(), timeout);
    bytes.resize(read);
    return bytes;
}

Poco::Serial::SerialPort& SerialChannel::port() noexcept
{
    return _port;
}
} // namespace PocoDDS::Protocols::Serial
