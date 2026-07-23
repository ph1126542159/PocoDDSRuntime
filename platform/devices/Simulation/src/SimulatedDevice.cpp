#include "PocoDDS/Devices/SimulatedDevice.h"

#include "Poco/NumberFormatter.h"
#include "Poco/Logger.h"
#include "Poco/Timestamp.h"

#include <stdexcept>
#include <utility>

namespace PocoDDS::Devices
{
SimulatedDevice::SimulatedDevice(std::string id) : _id(std::move(id)) {}

SimulatedDevice::~SimulatedDevice()
{
    stop();
}

const std::string& SimulatedDevice::id() const noexcept
{
    return _id;
}

const std::string& SimulatedDevice::type() const noexcept
{
    return _type;
}

void SimulatedDevice::start()
{
    if (_running.exchange(true))
        return;
    _thread.startFunc([this] { run(); });
}

void SimulatedDevice::stop() noexcept
{
    if (!_running.exchange(false))
        return;
    try
    {
        _thread.join();
    }
    catch (...)
    {
    }
}

DeviceSnapshot SimulatedDevice::snapshot() const
{
    Poco::FastMutex::ScopedLock lock(_mutex);
    return makeSnapshot();
}

std::string SimulatedDevice::execute(const std::string& operation, const std::string& payload)
{
    Poco::FastMutex::ScopedLock lock(_mutex);
    if (operation == "read")
        return Poco::NumberFormatter::format(_value, 2);
    if (operation == "set")
    {
        _value = std::stod(payload);
        ++_sequence;
        return Poco::NumberFormatter::format(_value, 2);
    }
    throw std::invalid_argument("unsupported simulated-device operation: " + operation);
}

void SimulatedDevice::setSnapshotHandler(SnapshotHandler handler)
{
    Poco::FastMutex::ScopedLock lock(_mutex);
    _handler = std::move(handler);
}

DeviceSnapshot SimulatedDevice::makeSnapshot() const
{
    return {_id,
            _type,
            _running ? DeviceState::ready : DeviceState::offline,
            _sequence,
            Poco::Timestamp().epochMicroseconds(),
            Poco::NumberFormatter::format(_value, 2)};
}

void SimulatedDevice::run()
{
    while (_running)
    {
        SnapshotHandler handler;
        DeviceSnapshot current;
        {
            Poco::FastMutex::ScopedLock lock(_mutex);
            _value += 0.25;
            ++_sequence;
            current = makeSnapshot();
            handler = _handler;
        }
        if (handler)
        {
            try
            {
                handler(current);
            }
            catch (const std::exception& exception)
            {
                Poco::Logger::get("PocoDDS.Devices.SimulatedDevice")
                    .error("Snapshot handler failed: %s", std::string(exception.what()));
            }
        }
        Poco::Thread::sleep(200);
    }
}
} // namespace PocoDDS::Devices
