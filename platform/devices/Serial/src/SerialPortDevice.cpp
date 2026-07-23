#include "PocoDDS/Devices/SerialPortDevice.h"

#include <Poco/Timestamp.h>

#include <stdexcept>
#include <utility>

namespace PocoDDS::Devices
{

SerialPortDevice::SerialPortDevice(std::string id, std::string port, int baudRate)
    : _id(std::move(id)),
      _channel(std::make_unique<PocoDDS::Protocols::Serial::SerialChannel>(
          std::move(port), baudRate))
{
}

SerialPortDevice::~SerialPortDevice()
{
    stop();
}

const std::string& SerialPortDevice::id() const noexcept { return _id; }
const std::string& SerialPortDevice::type() const noexcept { return _type; }

void SerialPortDevice::start()
{
    if (_running.exchange(true))
        return;
    try
    {
        _channel->open();
        _thread.startFunc([this] { run(); });
    }
    catch (...)
    {
        _running = false;
        throw;
    }
}

void SerialPortDevice::stop() noexcept
{
    if (!_running.exchange(false))
        return;
    try { _thread.join(); } catch (...) {}
    _channel->close();
}

DeviceSnapshot SerialPortDevice::snapshot() const
{
    Poco::FastMutex::ScopedLock lock(_mutex);
    return {_id, _type, _running ? DeviceState::ready : DeviceState::offline, _sequence,
            Poco::Timestamp().epochMicroseconds(), _channel->name()};
}

std::string SerialPortDevice::execute(const std::string& operation, const std::string& payload)
{
    if (operation == "write")
    {
        const std::vector<std::uint8_t> bytes(payload.begin(), payload.end());
        return std::to_string(write(bytes));
    }
    throw std::invalid_argument("unsupported serial-device operation: " + operation);
}

void SerialPortDevice::setSnapshotHandler(SnapshotHandler handler)
{
    Poco::FastMutex::ScopedLock lock(_mutex);
    _snapshotHandler = std::move(handler);
}

std::size_t SerialPortDevice::write(const std::vector<std::uint8_t>& data)
{
    return _channel->write(data.data(), data.size());
}

void SerialPortDevice::setDataHandler(DataHandler handler)
{
    Poco::FastMutex::ScopedLock lock(_mutex);
    _dataHandler = std::move(handler);
}

void SerialPortDevice::run()
{
    while (_running)
    {
        const auto data = _channel->read(4096, Poco::Timespan(0, 250000));
        if (data.empty())
            continue;

        DataHandler dataHandler;
        SnapshotHandler snapshotHandler;
        DeviceSnapshot current;
        {
            Poco::FastMutex::ScopedLock lock(_mutex);
            ++_sequence;
            dataHandler = _dataHandler;
            snapshotHandler = _snapshotHandler;
            current = {_id, _type, DeviceState::ready, _sequence,
                       Poco::Timestamp().epochMicroseconds(),
                       std::to_string(data.size()) + " bytes"};
        }
        if (dataHandler) dataHandler(data);
        if (snapshotHandler) snapshotHandler(current);
    }
}

} // namespace PocoDDS::Devices
