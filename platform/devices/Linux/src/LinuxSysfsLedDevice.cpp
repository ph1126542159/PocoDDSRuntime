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
}

LinuxSysfsLedDevice::~LinuxSysfsLedDevice() { stop(); }
const std::string& LinuxSysfsLedDevice::id() const noexcept { return _id; }
const std::string& LinuxSysfsLedDevice::type() const noexcept { return _type; }

void LinuxSysfsLedDevice::start()
{
    Poco::FastMutex::ScopedLock lock(_mutex);
    if (_started) return;
    std::ifstream stream(_directory / "max_brightness");
    if (!(stream >> _maxBrightness) || _maxBrightness == 0)
        throw std::runtime_error("invalid LED max_brightness: " + _directory.string());
    _started = true;
}

void LinuxSysfsLedDevice::stop() noexcept
{
    Poco::FastMutex::ScopedLock lock(_mutex);
    _started = false;
}

double LinuxSysfsLedDevice::brightness() const
{
    Poco::FastMutex::ScopedLock lock(_mutex);
    if (_maxBrightness == 0)
        throw std::logic_error("LED device is not started");
    unsigned raw = 0;
    std::ifstream stream(_directory / "brightness");
    if (!(stream >> raw))
        throw std::runtime_error("cannot read LED brightness");
    return static_cast<double>(raw) / _maxBrightness;
}

void LinuxSysfsLedDevice::setBrightness(double value)
{
    value = std::clamp(value, 0.0, 1.0);
    SnapshotHandler handler;
    {
        Poco::FastMutex::ScopedLock lock(_mutex);
        if (!_started || _maxBrightness == 0)
            throw std::logic_error("LED device is not started");
        std::ofstream stream(_directory / "brightness", std::ios::trunc);
        if (!stream)
            throw std::runtime_error("cannot open LED brightness");
        stream << static_cast<unsigned>(std::lround(value * _maxBrightness));
        if (!stream)
            throw std::runtime_error("cannot write LED brightness");
        ++_sequence;
        handler = _snapshotHandler;
    }
    if (handler) handler(snapshot());
}

DeviceSnapshot LinuxSysfsLedDevice::snapshot() const
{
    const auto value = brightness();
    Poco::FastMutex::ScopedLock lock(_mutex);
    return {_id, _type, _started ? DeviceState::ready : DeviceState::offline,
            _sequence, Poco::Timestamp().epochMicroseconds(),
            Poco::NumberFormatter::format(value, 3)};
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
} // namespace PocoDDS::Devices
