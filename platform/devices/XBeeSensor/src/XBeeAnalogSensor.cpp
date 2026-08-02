#include "PocoDDS/Devices/XBeeAnalogSensor.h"

#include <Poco/NumberFormatter.h>
#include <Poco/Timestamp.h>

#include <stdexcept>
#include <utility>

namespace PocoDDS::Devices
{

XBeeAnalogSensor::XBeeAnalogSensor(Options options, XBeeRecoveryPolicy recoveryPolicy)
    : XBeeAnalogSensor(
          options,
          options.serialPort.empty()
              ? std::shared_ptr<PocoDDS::Protocols::Serial::ISerialChannel>{}
              : std::make_shared<PocoDDS::Protocols::Serial::SerialChannel>(
                    options.serialPort, options.baudRate),
          recoveryPolicy)
{
}

XBeeAnalogSensor::XBeeAnalogSensor(
    Options options,
    std::shared_ptr<PocoDDS::Protocols::Serial::ISerialChannel> serial,
    XBeeRecoveryPolicy recoveryPolicy)
    : _options(std::move(options)), _serial(std::move(serial)),
      _recoveryPolicy(recoveryPolicy)
{
    if (_options.id.empty())
        throw std::invalid_argument("XBee sensor id must not be empty");
    if (_options.analogChannel >= 8)
        throw std::invalid_argument("XBee analog channel must be in range 0..7");
    if (_options.referenceMillivolts <= 0 || _options.adcMaximum <= 0)
        throw std::invalid_argument("XBee conversion scale must be positive");
    if (_recoveryPolicy.reconnectDelay.count() < 0 ||
        _recoveryPolicy.receiveTimeout.count() <= 0 ||
        _recoveryPolicy.staleAfter.count() <= 0)
        throw std::invalid_argument("XBee recovery timeouts are invalid");
    if (_serial)
        _port = std::make_unique<PocoDDS::Protocols::XBee::XBeePort>(
            _serial, _options.escapedApiMode);
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
        markConnected();
        _thread.startFunc([this] { run(); });
        notify(snapshot());
    }
    catch (...)
    {
        _running = false;
        _port->close();
        throw;
    }
}

void XBeeAnalogSensor::stop() noexcept
{
    if (!_running.exchange(false))
        return;
    try { _thread.join(); } catch (...) {}
    if (_port) _port->close();
    {
        Poco::FastMutex::ScopedLock lock(_mutex);
        _state = DeviceState::offline;
        ++_sequence;
    }
    notify(snapshot());
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
    DeviceSnapshot current;
    {
        Poco::FastMutex::ScopedLock lock(_mutex);
        _value = converted;
        _state = DeviceState::ready;
        _lastSample = std::chrono::steady_clock::now();
        ++_sequence;
        ++_diagnostics.successfulOperations;
        _diagnostics.consecutiveFailures = 0;
        _diagnostics.lastSuccessMicroseconds = Poco::Timestamp().epochMicroseconds();
        resolveFailure(_diagnostics, _failure);
        current = {_options.id, _type, _state, _sequence,
                   Poco::Timestamp().epochMicroseconds(),
                   Poco::NumberFormatter::format(_value, 3)};
    }
    notify(current, &converted);
    return true;
}

DeviceSnapshot XBeeAnalogSensor::snapshot() const
{
    Poco::FastMutex::ScopedLock lock(_mutex);
    return {_options.id, _type, _state,
            _sequence, Poco::Timestamp().epochMicroseconds(),
            _state == DeviceState::ready ? Poco::NumberFormatter::format(_value, 3) : "no-sample"};
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
        if (!_port->isOpen())
        {
            if (!_recoveryPolicy.enabled) break;
            {
                Poco::FastMutex::ScopedLock lock(_mutex);
                ++_diagnostics.reconnectAttempts;
            }
            try
            {
                _port->open();
                markConnected();
                notify(snapshot());
            }
            catch (const std::exception& error)
            {
                markFailure(error.what(), DeviceState::fault);
                notify(snapshot());
                Poco::Thread::sleep(static_cast<long>(_recoveryPolicy.reconnectDelay.count()));
            }
            continue;
        }
        try
        {
            PocoDDS::Protocols::XBee::XBeeFrame frame;
            const auto timeout = static_cast<Poco::Timespan::TimeDiff>(
                _recoveryPolicy.receiveTimeout.count()) * Poco::Timespan::MILLISECONDS;
            if (!_port->receive(frame, Poco::Timespan(timeout)))
            {
                checkStale();
                continue;
            }
            if (frame.type() == PocoDDS::Protocols::XBee::FrameType::zigbeeIoSample)
                ingest(PocoDDS::Protocols::XBee::IoSample::decode(frame));
            checkStale();
        }
        catch (const std::exception& error)
        {
            _port->close();
            markFailure(error.what(), DeviceState::fault);
            notify(snapshot());
            if (_recoveryPolicy.enabled)
                Poco::Thread::sleep(static_cast<long>(_recoveryPolicy.reconnectDelay.count()));
        }
    }
}

void XBeeAnalogSensor::markConnected()
{
    Poco::FastMutex::ScopedLock lock(_mutex);
    _state = DeviceState::offline;
    ++_sequence;
}

void XBeeAnalogSensor::markFailure(const std::string& message, DeviceState state)
{
    Poco::FastMutex::ScopedLock lock(_mutex);
    _state = state;
    ++_sequence;
    ++_diagnostics.failedOperations;
    ++_diagnostics.consecutiveFailures;
    _diagnostics.lastFailureMicroseconds = Poco::Timestamp().epochMicroseconds();
    recordFailure(_diagnostics, _failure, "PDR-DEVICE-XBEE-OPERATION_FAILED",
                  Reliability::FailureKind::transient, true, message);
}

void XBeeAnalogSensor::checkStale()
{
    bool stale = false;
    {
        Poco::FastMutex::ScopedLock lock(_mutex);
        stale = _state == DeviceState::ready &&
            _lastSample.time_since_epoch().count() != 0 &&
            std::chrono::steady_clock::now() - _lastSample >= _recoveryPolicy.staleAfter;
    }
    if (stale)
    {
        markFailure("XBee sample stale", DeviceState::offline);
        notify(snapshot());
    }
}

void XBeeAnalogSensor::notify(const DeviceSnapshot& current, const double* value)
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

DeviceDiagnostics XBeeAnalogSensor::diagnostics() const
{
    Poco::FastMutex::ScopedLock lock(_mutex);
    return _diagnostics;
}

PocoDDS::Reliability::Failure XBeeAnalogSensor::failure() const
{
    Poco::FastMutex::ScopedLock lock(_mutex);
    return _failure;
}

} // namespace PocoDDS::Devices
