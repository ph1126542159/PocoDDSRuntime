#include "PocoDDS/Devices/CanSignalSensor.h"

#include <Poco/NumberFormatter.h>
#include <Poco/Timestamp.h>

#include <chrono>
#include <stdexcept>
#include <utility>

namespace PocoDDS::Devices
{
CanSignalSensor::CanSignalSensor(Options options): _options(std::move(options))
{
    if (_options.id.empty())
        throw std::invalid_argument("CAN sensor id must not be empty");
    if (!_options.interfaceName.empty())
        _endpoint = std::make_unique<PocoDDS::Protocols::CAN::SocketCanEndpoint>(
            _options.interfaceName);
}

CanSignalSensor::~CanSignalSensor() { stop(); }
const std::string& CanSignalSensor::id() const noexcept { return _options.id; }
const std::string& CanSignalSensor::type() const noexcept { return _type; }

void CanSignalSensor::start()
{
    if (!_endpoint)
        throw std::logic_error("CAN sensor has no SocketCAN interface");
    if (_running.exchange(true)) return;
    try
    {
        _endpoint->open();
        _thread.startFunc([this] { run(); });
    }
    catch (...)
    {
        _running = false;
        throw;
    }
}

void CanSignalSensor::stop() noexcept
{
    if (!_running.exchange(false)) return;
    try { _thread.join(); } catch (...) {}
    if (_endpoint) _endpoint->close();
}

bool CanSignalSensor::ingest(const PocoDDS::Protocols::CAN::CanFrame& frame)
{
    if (frame.id != _options.frameId) return false;
    const double decoded = PocoDDS::Protocols::CAN::SignalCodec::decodeScaled(
        frame, _options.bitOffset, _options.bitLength, _options.bitOrder,
        _options.signedValue, _options.factor, _options.offset);
    SnapshotHandler snapshotHandler;
    ValueHandler valueHandler;
    {
        Poco::FastMutex::ScopedLock lock(_mutex);
        _value = decoded;
        _ready = true;
        ++_sequence;
        snapshotHandler = _snapshotHandler;
        valueHandler = _valueHandler;
    }
    if (valueHandler) valueHandler(decoded);
    if (snapshotHandler) snapshotHandler(snapshot());
    return true;
}

DeviceSnapshot CanSignalSensor::snapshot() const
{
    Poco::FastMutex::ScopedLock lock(_mutex);
    return {_options.id, _type, _ready ? DeviceState::ready : DeviceState::offline,
            _sequence, Poco::Timestamp().epochMicroseconds(),
            _ready ? Poco::NumberFormatter::format(_value, 3) : "no-frame"};
}

std::string CanSignalSensor::execute(const std::string& operation, const std::string&)
{
    if (operation == "read") return snapshot().payload;
    throw std::invalid_argument("unsupported CAN sensor operation: " + operation);
}

void CanSignalSensor::setSnapshotHandler(SnapshotHandler handler)
{
    Poco::FastMutex::ScopedLock lock(_mutex);
    _snapshotHandler = std::move(handler);
}

double CanSignalSensor::value() const
{
    Poco::FastMutex::ScopedLock lock(_mutex);
    return _value;
}

std::string CanSignalSensor::physicalQuantity() const { return _options.physicalQuantity; }
std::string CanSignalSensor::physicalUnit() const { return _options.physicalUnit; }

void CanSignalSensor::setValueHandler(ValueHandler handler)
{
    Poco::FastMutex::ScopedLock lock(_mutex);
    _valueHandler = std::move(handler);
}

void CanSignalSensor::run()
{
    while (_running)
    {
        PocoDDS::Protocols::CAN::CanFrame frame;
        if (_endpoint->receive(frame, std::chrono::milliseconds(250)))
            ingest(frame);
    }
}
} // namespace PocoDDS::Devices
