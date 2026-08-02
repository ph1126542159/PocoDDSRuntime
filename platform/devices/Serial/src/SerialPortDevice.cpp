#include "PocoDDS/Devices/SerialPortDevice.h"

#include <Poco/Timestamp.h>

#include <stdexcept>
#include <utility>

namespace PocoDDS::Devices
{

SerialPortDevice::SerialPortDevice(std::string id, std::string port, int baudRate,
                                   SerialReconnectPolicy reconnectPolicy)
    : SerialPortDevice(
          std::move(id),
          std::make_shared<PocoDDS::Protocols::Serial::SerialChannel>(
              std::move(port), baudRate),
          reconnectPolicy)
{
}

SerialPortDevice::SerialPortDevice(
    std::string id,
    std::shared_ptr<PocoDDS::Protocols::Serial::ISerialChannel> channel,
    SerialReconnectPolicy reconnectPolicy)
    : _id(std::move(id)), _channel(std::move(channel)),
      _reconnectPolicy(reconnectPolicy)
{
    if (_id.empty())
        throw std::invalid_argument("serial device id must not be empty");
    if (!_channel)
        throw std::invalid_argument("serial channel is required");
    if (_reconnectPolicy.delay.count() < 0 ||
        _reconnectPolicy.readTimeout.count() <= 0)
        throw std::invalid_argument("serial reconnect delay must be non-negative and read timeout positive");
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
        markReady();
        _thread.startFunc([this] { run(); });
        notify(snapshot());
    }
    catch (...)
    {
        _running = false;
        _channel->close();
        Poco::FastMutex::ScopedLock lock(_mutex);
        _state = DeviceState::offline;
        throw;
    }
}

void SerialPortDevice::stop() noexcept
{
    if (!_running.exchange(false))
        return;
    try { _thread.join(); } catch (...) {}
    _channel->close();
    DeviceSnapshot current;
    {
        Poco::FastMutex::ScopedLock lock(_mutex);
        _state = DeviceState::offline;
        ++_sequence;
        current = {_id, _type, _state, _sequence,
                   Poco::Timestamp().epochMicroseconds(), _lastPayload};
    }
    notify(current);
}

DeviceSnapshot SerialPortDevice::snapshot() const
{
    Poco::FastMutex::ScopedLock lock(_mutex);
    return {_id, _type, _state, _sequence,
            Poco::Timestamp().epochMicroseconds(), _lastPayload};
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
    {
        Poco::FastMutex::ScopedLock lock(_mutex);
        if (!_running || _state != DeviceState::ready)
            throw std::runtime_error("serial device is not ready");
    }
    try
    {
        const auto written = _channel->write(data.data(), data.size());
        if (written != data.size())
            throw std::runtime_error("partial serial write: " + std::to_string(written) +
                                     "/" + std::to_string(data.size()));
        DeviceSnapshot current;
        {
            Poco::FastMutex::ScopedLock lock(_mutex);
            ++_sequence;
            ++_diagnostics.successfulOperations;
            _diagnostics.consecutiveFailures = 0;
            _diagnostics.lastSuccessMicroseconds = Poco::Timestamp().epochMicroseconds();
            resolveFailure(_diagnostics, _failure);
            _lastPayload = std::to_string(written) + " bytes written";
            current = {_id, _type, _state, _sequence,
                       Poco::Timestamp().epochMicroseconds(), _lastPayload};
        }
        notify(current);
        return written;
    }
    catch (const std::exception& error)
    {
        _channel->close();
        markFailure(error.what());
        notify(snapshot());
        throw;
    }
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
        if (!_channel->isOpen())
        {
            if (!_reconnectPolicy.enabled)
                break;
            {
                Poco::FastMutex::ScopedLock lock(_mutex);
                ++_diagnostics.reconnectAttempts;
            }
            try
            {
                _channel->open();
                markReady();
                notify(snapshot());
            }
            catch (const std::exception& error)
            {
                markFailure(error.what());
                notify(snapshot());
                Poco::Thread::sleep(static_cast<long>(_reconnectPolicy.delay.count()));
            }
            continue;
        }

        try
        {
            const auto timeoutMicroseconds =
                static_cast<Poco::Timespan::TimeDiff>(_reconnectPolicy.readTimeout.count()) *
                Poco::Timespan::MILLISECONDS;
            const auto data = _channel->read(4096, Poco::Timespan(timeoutMicroseconds));
            if (data.empty())
                continue;
            DeviceSnapshot current;
            {
                Poco::FastMutex::ScopedLock lock(_mutex);
                ++_sequence;
                _state = DeviceState::ready;
                ++_diagnostics.successfulOperations;
                _diagnostics.consecutiveFailures = 0;
                _diagnostics.lastSuccessMicroseconds = Poco::Timestamp().epochMicroseconds();
                resolveFailure(_diagnostics, _failure);
                _lastPayload = std::to_string(data.size()) + " bytes read";
                current = {_id, _type, _state, _sequence,
                           Poco::Timestamp().epochMicroseconds(), _lastPayload};
            }
            notify(current, &data);
        }
        catch (const std::exception& error)
        {
            _channel->close();
            markFailure(error.what());
            notify(snapshot());
            if (_reconnectPolicy.enabled)
                Poco::Thread::sleep(static_cast<long>(_reconnectPolicy.delay.count()));
        }
    }
}

void SerialPortDevice::markReady()
{
    Poco::FastMutex::ScopedLock lock(_mutex);
    _state = DeviceState::ready;
    ++_sequence;
    _diagnostics.consecutiveFailures = 0;
    resolveFailure(_diagnostics, _failure);
    _lastPayload = _channel->name();
}

void SerialPortDevice::markFailure(const std::string& message)
{
    Poco::FastMutex::ScopedLock lock(_mutex);
    _state = DeviceState::fault;
    ++_sequence;
    ++_diagnostics.failedOperations;
    ++_diagnostics.consecutiveFailures;
    _diagnostics.lastFailureMicroseconds = Poco::Timestamp().epochMicroseconds();
    recordFailure(_diagnostics, _failure, "PDR-DEVICE-SERIAL-OPERATION_FAILED",
                  Reliability::FailureKind::transient, true, message);
}

void SerialPortDevice::notify(const DeviceSnapshot& current,
                              const std::vector<std::uint8_t>* data)
{
    SnapshotHandler snapshotHandler;
    DataHandler dataHandler;
    {
        Poco::FastMutex::ScopedLock lock(_mutex);
        snapshotHandler = _snapshotHandler;
        dataHandler = _dataHandler;
    }
    if (data && dataHandler)
    {
        try { dataHandler(*data); } catch (...) {}
    }
    if (snapshotHandler)
    {
        try { snapshotHandler(current); } catch (...) {}
    }
}

DeviceDiagnostics SerialPortDevice::diagnostics() const
{
    Poco::FastMutex::ScopedLock lock(_mutex);
    return _diagnostics;
}

PocoDDS::Reliability::Failure SerialPortDevice::failure() const
{
    Poco::FastMutex::ScopedLock lock(_mutex);
    return _failure;
}

} // namespace PocoDDS::Devices
