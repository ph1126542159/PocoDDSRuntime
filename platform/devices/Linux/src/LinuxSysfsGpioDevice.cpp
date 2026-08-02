#include "PocoDDS/Devices/LinuxSysfsGpioDevice.h"

#include <Poco/Timestamp.h>
#include <Poco/Thread.h>

#include <fstream>
#include <stdexcept>
#include <utility>

namespace PocoDDS::Devices
{

LinuxSysfsGpioDevice::LinuxSysfsGpioDevice(
    std::string id,
    unsigned pin,
    Direction direction,
    PocoDDS::Filesystem::path sysfsRoot,
    bool manageExport,
    std::chrono::milliseconds exportTimeout)
    : _id(std::move(id)), _pin(pin), _direction(direction),
      _root(std::move(sysfsRoot)), _manageExport(manageExport),
      _exportTimeout(exportTimeout)
{
    if (_id.empty()) throw std::invalid_argument("GPIO device id must not be empty");
    if (_exportTimeout.count() < 0)
        throw std::invalid_argument("GPIO export timeout must be non-negative");
}

LinuxSysfsGpioDevice::~LinuxSysfsGpioDevice() { stop(); }
const std::string& LinuxSysfsGpioDevice::id() const noexcept { return _id; }
const std::string& LinuxSysfsGpioDevice::type() const noexcept { return _type; }

void LinuxSysfsGpioDevice::writeControl(
    const PocoDDS::Filesystem::path& file,
    const std::string& value) const
{
    std::ofstream stream(file, std::ios::trunc);
    if (!stream)
        throw std::runtime_error("cannot open GPIO sysfs file: " + file.string());
    stream << value;
    if (!stream)
        throw std::runtime_error("cannot write GPIO sysfs file: " + file.string());
}

void LinuxSysfsGpioDevice::start()
{
    const auto gpio = _root / ("gpio" + std::to_string(_pin));
    {
        Poco::FastMutex::ScopedLock lock(_mutex);
        if (_state == DeviceState::ready) return;
    }
    try
    {
        if (_manageExport && !PocoDDS::Filesystem::exists(gpio))
        {
            writeControl(_root / "export", std::to_string(_pin));
            Poco::FastMutex::ScopedLock lock(_mutex);
            _exportedByUs = true;
        }
        const auto deadline = std::chrono::steady_clock::now() + _exportTimeout;
        while (!PocoDDS::Filesystem::exists(gpio) &&
               std::chrono::steady_clock::now() < deadline)
            Poco::Thread::sleep(10);
        if (!PocoDDS::Filesystem::exists(gpio))
            throw std::runtime_error("GPIO sysfs node did not appear: " + gpio.string());
        writeControl(gpio / "direction", _direction == Direction::output ? "out" : "in");
        Poco::FastMutex::ScopedLock lock(_mutex);
        _state = DeviceState::ready;
        _lastPayload = "configured";
        ++_sequence;
    }
    catch (const std::exception& error)
    {
        markFailure(error.what());
        throw;
    }
}

void LinuxSysfsGpioDevice::stop() noexcept
{
    bool unexport = false;
    {
        Poco::FastMutex::ScopedLock lock(_mutex);
        if (_state == DeviceState::offline && !_exportedByUs) return;
        unexport = _manageExport && _exportedByUs;
        _exportedByUs = false;
        _state = DeviceState::offline;
        _lastPayload = "stopped";
        ++_sequence;
    }
    if (unexport)
        try { writeControl(_root / "unexport", std::to_string(_pin)); } catch (...) {}
    notify(snapshot());
}

std::uint32_t LinuxSysfsGpioDevice::read() const
{
    try
    {
        {
            Poco::FastMutex::ScopedLock lock(_mutex);
            if (_state == DeviceState::offline)
                throw std::logic_error("GPIO device is not started");
        }
        std::ifstream stream(_root / ("gpio" + std::to_string(_pin)) / "value");
        unsigned value = 0;
        if (!(stream >> value)) throw std::runtime_error("cannot read GPIO value");
        const auto normalized = value ? 1U : 0U;
        markSuccess(std::to_string(normalized));
        return normalized;
    }
    catch (const std::exception& error)
    {
        markFailure(error.what());
        throw;
    }
}

void LinuxSysfsGpioDevice::write(std::uint32_t value)
{
    if (_direction != Direction::output)
        throw std::logic_error("cannot write input GPIO");
    const auto normalized = value ? 1U : 0U;
    DeviceSnapshot current;
    try
    {
        {
            Poco::FastMutex::ScopedLock lock(_mutex);
            if (_state == DeviceState::offline)
                throw std::logic_error("GPIO device is not started");
        }
        writeControl(
            _root / ("gpio" + std::to_string(_pin)) / "value",
            normalized ? "1" : "0");
        markSuccess(std::to_string(normalized));
        Poco::FastMutex::ScopedLock lock(_mutex);
        current = {_id, _type, _state, _sequence,
                   Poco::Timestamp().epochMicroseconds(), _lastPayload};
    }
    catch (const std::exception& error)
    {
        markFailure(error.what());
        throw;
    }
    notify(current, &normalized);
}

DeviceSnapshot LinuxSysfsGpioDevice::snapshot() const
{
    {
        Poco::FastMutex::ScopedLock lock(_mutex);
        if (_state == DeviceState::offline)
            return {_id, _type, _state, _sequence,
                    Poco::Timestamp().epochMicroseconds(), _lastPayload};
    }
    try { (void) read(); } catch (...) {}
    Poco::FastMutex::ScopedLock lock(_mutex);
    return {_id, _type, _state, _sequence,
            Poco::Timestamp().epochMicroseconds(), _lastPayload};
}

std::string LinuxSysfsGpioDevice::execute(
    const std::string& operation,
    const std::string& payload)
{
    if (operation == "read")
        return std::to_string(read());
    if (operation == "write")
    {
        write(static_cast<std::uint32_t>(std::stoul(payload)));
        return std::to_string(read());
    }
    if (operation == "toggle")
    {
        const auto next = read() == 0 ? 1U : 0U;
        write(next);
        return std::to_string(next);
    }
    throw std::invalid_argument("unsupported GPIO operation: " + operation);
}

void LinuxSysfsGpioDevice::setSnapshotHandler(SnapshotHandler handler)
{
    Poco::FastMutex::ScopedLock lock(_mutex);
    _snapshotHandler = std::move(handler);
}

void LinuxSysfsGpioDevice::setValueHandler(ValueHandler handler)
{
    Poco::FastMutex::ScopedLock lock(_mutex);
    _valueHandler = std::move(handler);
}

void LinuxSysfsGpioDevice::markSuccess(const std::string& payload) const
{
    Poco::FastMutex::ScopedLock lock(_mutex);
    _state = DeviceState::ready;
    _lastPayload = payload;
    ++_sequence;
    ++_diagnostics.successfulOperations;
    _diagnostics.consecutiveFailures = 0;
    _diagnostics.lastSuccessMicroseconds = Poco::Timestamp().epochMicroseconds();
        resolveFailure(_diagnostics, _failure);
}

void LinuxSysfsGpioDevice::markFailure(const std::string& message) const
{
    Poco::FastMutex::ScopedLock lock(_mutex);
    _state = DeviceState::fault;
    _lastPayload = message;
    ++_sequence;
    ++_diagnostics.failedOperations;
    ++_diagnostics.consecutiveFailures;
    _diagnostics.lastFailureMicroseconds = Poco::Timestamp().epochMicroseconds();
    recordFailure(_diagnostics, _failure, "PDR-DEVICE-LINUX-GPIO_IO_FAILED",
                  Reliability::FailureKind::hardware, true, message);
}

void LinuxSysfsGpioDevice::notify(const DeviceSnapshot& current,
                                  const std::uint32_t* value) const
{
    SnapshotHandler snapshotHandler;
    ValueHandler valueHandler;
    {
        Poco::FastMutex::ScopedLock lock(_mutex);
        snapshotHandler = _snapshotHandler;
        valueHandler = _valueHandler;
    }
    if (value && valueHandler) try { valueHandler(*value); } catch (...) {}
    if (snapshotHandler) try { snapshotHandler(current); } catch (...) {}
}

DeviceDiagnostics LinuxSysfsGpioDevice::diagnostics() const
{
    Poco::FastMutex::ScopedLock lock(_mutex);
    return _diagnostics;
}

PocoDDS::Reliability::Failure LinuxSysfsGpioDevice::failure() const
{
    Poco::FastMutex::ScopedLock lock(_mutex);
    return _failure;
}

} // namespace PocoDDS::Devices
