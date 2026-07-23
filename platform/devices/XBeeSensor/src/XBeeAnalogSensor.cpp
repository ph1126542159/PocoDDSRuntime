#include "PocoDDS/Devices/XBeeAnalogSensor.h"

#include <Poco/NumberFormatter.h>
#include <Poco/Timestamp.h>

#include <stdexcept>
#include <utility>

namespace PocoDDS::Devices
{

XBeeAnalogSensor::XBeeAnalogSensor(Options options): _options(std::move(options))
{
    if (_options.id.empty())
        throw std::invalid_argument("XBee sensor id must not be empty");
    if (_options.analogChannel >= 8)
        throw std::invalid_argument("XBee analog channel must be in range 0..7");
    if (!_options.serialPort.empty())
    {
        _serial = std::make_shared<PocoDDS::Protocols::Serial::SerialChannel>(
            _options.serialPort, _options.baudRate);
        _port = std::make_unique<PocoDDS::Protocols::XBee::XBeePort>(
            _serial, _options.escapedApiMode);
    }
}

XBeeAnalogSensor::~XBeeAnalogSensor() { stop(); }
const std::string& XBeeAnalogSensor::id() const noexcept { return _options.id; }
const std::string& XBeeAnalogSensor::type() const noexcept { return _type; }

void XBeeAnalogSensor::start()
{
    if (!_port)
        throw std::logic_error("XBee sensor has no serial port");
    if (_running.exchange(true))
        return;
    try
    {
        _port->open();
        _thread.startFunc([this] { run(); });
    }
    catch (...)
    {
        _running = false;
        throw;
    }
}

void XBeeAnalogSensor::stop() noexcept
{
    if (!_running.exchange(false))
        return;
    try { _thread.join(); } catch (...) {}
    if (_port) _port->close();
}

double XBeeAnalogSensor::convert(std::uint16_t sample) const
{
    const double millivolts =
        _options.referenceMillivolts * static_cast<double>(sample) /
        _options.adcMaximum;
    switch (_options.conversion)
    {
    case Conversion::raw:
        return sample;
    case Conversion::millivolts:
        return millivolts;
    case Conversion::temperatureCelsius:
        return (millivolts - 500.0) / 10.0;
    case Conversion::relativeHumidity:
        return ((millivolts * 108.2 / 33.2) / 5000.0 - 0.16) / 0.0062;
    }
    throw std::logic_error("invalid XBee conversion");
}

bool XBeeAnalogSensor::ingest(const PocoDDS::Protocols::XBee::IoSample& sample)
{
    if (sample.sourceAddress != _options.sourceAddress ||
        !sample.hasAnalog(_options.analogChannel))
        return false;

    const double converted = convert(sample.analog(_options.analogChannel));
    SnapshotHandler snapshotHandler;
    ValueHandler valueHandler;
    {
        Poco::FastMutex::ScopedLock lock(_mutex);
        _value = converted;
        _ready = true;
        ++_sequence;
        snapshotHandler = _snapshotHandler;
        valueHandler = _valueHandler;
    }
    if (valueHandler) valueHandler(converted);
    if (snapshotHandler) snapshotHandler(snapshot());
    return true;
}

DeviceSnapshot XBeeAnalogSensor::snapshot() const
{
    Poco::FastMutex::ScopedLock lock(_mutex);
    return {_options.id, _type, _ready ? DeviceState::ready : DeviceState::offline,
            _sequence, Poco::Timestamp().epochMicroseconds(),
            _ready ? Poco::NumberFormatter::format(_value, 3) : "no-sample"};
}

std::string XBeeAnalogSensor::execute(
    const std::string& operation,
    const std::string&)
{
    if (operation == "read")
        return snapshot().payload;
    throw std::invalid_argument("unsupported XBee sensor operation: " + operation);
}

void XBeeAnalogSensor::setSnapshotHandler(SnapshotHandler handler)
{
    Poco::FastMutex::ScopedLock lock(_mutex);
    _snapshotHandler = std::move(handler);
}

double XBeeAnalogSensor::value() const
{
    Poco::FastMutex::ScopedLock lock(_mutex);
    return _value;
}

std::string XBeeAnalogSensor::physicalQuantity() const
{
    return _options.physicalQuantity;
}

std::string XBeeAnalogSensor::physicalUnit() const
{
    return _options.physicalUnit;
}

void XBeeAnalogSensor::setValueHandler(ValueHandler handler)
{
    Poco::FastMutex::ScopedLock lock(_mutex);
    _valueHandler = std::move(handler);
}

void XBeeAnalogSensor::run()
{
    while (_running)
    {
        PocoDDS::Protocols::XBee::XBeeFrame frame;
        if (!_port->receive(frame, Poco::Timespan(0, 250000)))
            continue;
        if (frame.type() == PocoDDS::Protocols::XBee::FrameType::zigbeeIoSample)
            ingest(PocoDDS::Protocols::XBee::IoSample::decode(frame));
    }
}

} // namespace PocoDDS::Devices
