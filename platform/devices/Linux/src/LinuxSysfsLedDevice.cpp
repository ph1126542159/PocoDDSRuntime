#include "PocoDDS/Devices/LinuxSysfsLedDevice.h"

#include <Poco/NumberFormatter.h>
#include <Poco/Timestamp.h>

#include <algorithm>
#include <cmath>
#include <fstream>
#include <stdexcept>
#include <utility>

namespace PocoDDS::Devices
{
LinuxSysfsLedDevice::LinuxSysfsLedDevice(
    std::string id, PocoDDS::Filesystem::path ledDirectory)
    : _id(std::move(id)), _directory(std::move(ledDirectory))
{
    if (_id.empty()) throw std::invalid_argument("LED device id must not be empty");
}

LinuxSysfsLedDevice::~LinuxSysfsLedDevice() { stop(); }
const std::string& LinuxSysfsLedDevice::id() const noexcept { return _id; }
const std::string& LinuxSysfsLedDevice::type() const noexcept { return _type; }

void LinuxSysfsLedDevice::start()
{
    {
        Poco::FastMutex::ScopedLock lock(_mutex);
        if (_state == DeviceState::ready) return;
    }
    try
    {
        unsigned maximum = 0;
        std::ifstream stream(_directory / "max_brightness");
        if (!(stream >> maximum) || maximum == 0)
            throw std::runtime_error("invalid LED max_brightness: " + _directory.string());
        Poco::FastMutex::ScopedLock lock(_mutex);
        _maxBrightness = maximum;
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

void LinuxSysfsLedDevice::stop() noexcept
{
    {
        Poco::FastMutex::ScopedLock lock(_mutex);
        if (_state == DeviceState::offline) return;
        _state = DeviceState::offline;
        _maxBrightness = 0;
        _lastPayload = "stopped";
        ++_sequence;
    }
    notify(snapshot());
}

double LinuxSysfsLedDevice::brightness() const
{
    try
    {
        unsigned maximum = 0;
        {
            Poco::FastMutex::ScopedLock lock(_mutex);
            maximum = _maxBrightness;
            if (_state == DeviceState::offline || maximum == 0)
                throw std::logic_error("LED device is not started");
        }
        unsigned raw = 0;
        std::ifstream stream(_directory / "brightness");
        if (!(stream >> raw)) throw std::runtime_error("cannot read LED brightness");
        const auto result = static_cast<double>(raw) / maximum;
        markSuccess(Poco::NumberFormatter::format(result, 3));
        return result;
    }
    catch (const std::exception& error)
    {
        markFailure(error.what());
        throw;
    }
}

void LinuxSysfsLedDevice::setBrightness(double value)
{
    value = std::clamp(value, 0.0, 1.0);
    DeviceSnapshot current;
    try
    {
        unsigned maximum = 0;
        {
            Poco::FastMutex::ScopedLock lock(_mutex);
            maximum = _maxBrightness;
            if (_state == DeviceState::offline || maximum == 0)
                throw std::logic_error("LED device is not started");
        }
        std::ofstream stream(_directory / "brightness", std::ios::trunc);
        if (!stream)
            throw std::runtime_error("cannot open LED brightness");
        stream << static_cast<unsigned>(std::lround(value * maximum));
        if (!stream)
            throw std::runtime_error("cannot write LED brightness");
        markSuccess(Poco::NumberFormatter::format(value, 3));
        Poco::FastMutex::ScopedLock lock(_mutex);
        current = {_id, _type, _state, _sequence,
                   Poco::Timestamp().epochMicroseconds(), _lastPayload};
    }
    catch (const std::exception& error)
    {
        markFailure(error.what());
        throw;
    }
    notify(current);
}

DeviceSnapshot LinuxSysfsLedDevice::snapshot() const
{
    {
        Poco::FastMutex::ScopedLock lock(_mutex);
        if (_state == DeviceState::offline)
            return {_id, _type, _state, _sequence,
                    Poco::Timestamp().epochMicroseconds(), _lastPayload};
    }
    try { (void) brightness(); } catch (...) {}
    Poco::FastMutex::ScopedLock lock(_mutex);
    return {_id, _type, _state, _sequence,
            Poco::Timestamp().epochMicroseconds(), _lastPayload};
}

std::string LinuxSysfsLedDevice::execute(
    const std::string& operation, const std::string& payload)
{
    if (operation == "read") return Poco::NumberFormatter::format(brightness(), 3);
    if (operation == "on") setBrightness(1);
    else if (operation == "off") setBrightness(0);
    else if (operation == "set") setBrightness(std::stod(payload));
    else throw std::invalid_argument("unsupported LED operation: " + operation);
    return Poco::NumberFormatter::format(brightness(), 3);
}

void LinuxSysfsLedDevice::setSnapshotHandler(SnapshotHandler handler)
{
    Poco::FastMutex::ScopedLock lock(_mutex);
    _snapshotHandler = std::move(handler);
}

void LinuxSysfsLedDevice::markSuccess(const std::string& payload) const
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

void LinuxSysfsLedDevice::markFailure(const std::string& message) const
{
    Poco::FastMutex::ScopedLock lock(_mutex);
    _state = DeviceState::fault;
    _lastPayload = message;
    ++_sequence;
    ++_diagnostics.failedOperations;
    ++_diagnostics.consecutiveFailures;
    _diagnostics.lastFailureMicroseconds = Poco::Timestamp().epochMicroseconds();
    recordFailure(_diagnostics, _failure, "PDR-DEVICE-LINUX-LED_IO_FAILED",
                  Reliability::FailureKind::hardware, true, message);
}

void LinuxSysfsLedDevice::notify(const DeviceSnapshot& current) const
{
    SnapshotHandler handler;
    {
        Poco::FastMutex::ScopedLock lock(_mutex);
        handler = _snapshotHandler;
    }
    if (handler) try { handler(current); } catch (...) {}
}

DeviceDiagnostics LinuxSysfsLedDevice::diagnostics() const
{
    Poco::FastMutex::ScopedLock lock(_mutex);
    return _diagnostics;
}
PocoDDS::Reliability::Failure LinuxSysfsLedDevice::failure() const
{
    Poco::FastMutex::ScopedLock lock(_mutex);
    return _failure;
}
} // namespace PocoDDS::Devices
