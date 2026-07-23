#include "PocoDDS/Devices/LinuxSysfsGpioDevice.h"

#include <Poco/Timestamp.h>

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
    bool manageExport)
    : _id(std::move(id)), _pin(pin), _direction(direction),
      _root(std::move(sysfsRoot)), _manageExport(manageExport)
{
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
    Poco::FastMutex::ScopedLock lock(_mutex);
    if (_started)
        return;
    if (_manageExport)
        writeControl(_root / "export", std::to_string(_pin));
    const auto gpio = _root / ("gpio" + std::to_string(_pin));
    writeControl(gpio / "direction", _direction == Direction::output ? "out" : "in");
    _started = true;
}

void LinuxSysfsGpioDevice::stop() noexcept
{
    Poco::FastMutex::ScopedLock lock(_mutex);
    if (!_started)
        return;
    if (_manageExport)
    {
        try { writeControl(_root / "unexport", std::to_string(_pin)); } catch (...) {}
    }
    _started = false;
}

std::uint32_t LinuxSysfsGpioDevice::read() const
{
    Poco::FastMutex::ScopedLock lock(_mutex);
    std::ifstream stream(_root / ("gpio" + std::to_string(_pin)) / "value");
    unsigned value = 0;
    if (!(stream >> value))
        throw std::runtime_error("cannot read GPIO value");
    return value ? 1U : 0U;
}

void LinuxSysfsGpioDevice::write(std::uint32_t value)
{
    if (_direction != Direction::output)
        throw std::logic_error("cannot write input GPIO");
    ValueHandler valueHandler;
    SnapshotHandler snapshotHandler;
    {
        Poco::FastMutex::ScopedLock lock(_mutex);
        writeControl(
            _root / ("gpio" + std::to_string(_pin)) / "value",
            value ? "1" : "0");
        ++_sequence;
        valueHandler = _valueHandler;
        snapshotHandler = _snapshotHandler;
    }
    if (valueHandler) valueHandler(value ? 1U : 0U);
    if (snapshotHandler) snapshotHandler(snapshot());
}

DeviceSnapshot LinuxSysfsGpioDevice::snapshot() const
{
    const auto value = read();
    Poco::FastMutex::ScopedLock lock(_mutex);
    return {_id, _type, _started ? DeviceState::ready : DeviceState::offline, _sequence,
            Poco::Timestamp().epochMicroseconds(), std::to_string(value)};
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

} // namespace PocoDDS::Devices
