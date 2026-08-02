#include "PocoDDS/Devices/CanSignalSensor.h"

#include <Poco/NumberFormatter.h>
#include <Poco/Timestamp.h>

#include <chrono>
#include <stdexcept>
#include <utility>

namespace PocoDDS::Devices
{
CanSignalSensor::CanSignalSensor(Options options, CanRecoveryPolicy recoveryPolicy)
    : CanSignalSensor(
          options,
          options.interfaceName.empty()
              ? std::shared_ptr<PocoDDS::Protocols::CAN::CanEndpoint>{}
              : std::make_shared<PocoDDS::Protocols::CAN::SocketCanEndpoint>(
                    options.interfaceName),
          recoveryPolicy)
{
}

CanSignalSensor::CanSignalSensor(
    Options options,
    std::shared_ptr<PocoDDS::Protocols::CAN::CanEndpoint> endpoint,
    CanRecoveryPolicy recoveryPolicy)
    : _options(std::move(options)), _recoveryPolicy(recoveryPolicy),
      _endpoint(std::move(endpoint))
{
    if (_options.id.empty())
        throw std::invalid_argument("CAN sensor id must not be empty");
    if (_recoveryPolicy.reconnectDelay.count() < 0 ||
        _recoveryPolicy.receiveTimeout.count() <= 0 ||
        _recoveryPolicy.staleAfter.count() <= 0)
        throw std::invalid_argument("CAN recovery timeouts are invalid");
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
        markConnected();
        _thread.startFunc([this] { run(); });
        notify(snapshot(), false);
    }
    catch (...)
    {
        _running = false;
        _endpoint->close();
        throw;
    }
}

void CanSignalSensor::stop() noexcept
{
    if (!_running.exchange(false)) return;
    try { _thread.join(); } catch (...) {}
    if (_endpoint) _endpoint->close();
    DeviceSnapshot current;
    {
        Poco::FastMutex::ScopedLock lock(_mutex);
        _state = DeviceState::offline;
        ++_sequence;
        _lastPayload = "stopped";
        current = {_options.id, _type, _state, _sequence,
                   Poco::Timestamp().epochMicroseconds(), _lastPayload};
    }
    notify(current, false);
}

bool CanSignalSensor::ingest(const PocoDDS::Protocols::CAN::CanFrame& frame)
{
    if (frame.error || frame.id != _options.frameId ||
        frame.extended != _options.extended) return false;
    const double decoded = PocoDDS::Protocols::CAN::SignalCodec::decodeScaled(
        frame, _options.bitOffset, _options.bitLength, _options.bitOrder,
        _options.signedValue, _options.factor, _options.offset);
    DeviceSnapshot current;
    {
        Poco::FastMutex::ScopedLock lock(_mutex);
        _value = decoded;
        _state = DeviceState::ready;
        ++_sequence;
        ++_diagnostics.successfulOperations;
        _diagnostics.consecutiveFailures = 0;
        _diagnostics.lastSuccessMicroseconds = Poco::Timestamp().epochMicroseconds();
        resolveFailure(_diagnostics, _failure);
        _lastFrame = std::chrono::steady_clock::now();
        _lastPayload = Poco::NumberFormatter::format(_value, 3);
        current = {_options.id, _type, _state, _sequence,
                   Poco::Timestamp().epochMicroseconds(), _lastPayload};
    }
    notify(current, true);
    return true;
}

DeviceSnapshot CanSignalSensor::snapshot() const
{
    Poco::FastMutex::ScopedLock lock(_mutex);
    return {_options.id, _type, _state, _sequence,
            Poco::Timestamp().epochMicroseconds(), _lastPayload};
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
        if (!_endpoint->isOpen())
        {
            if (!_recoveryPolicy.enabled)
                break;
            {
                Poco::FastMutex::ScopedLock lock(_mutex);
                ++_diagnostics.reconnectAttempts;
            }
            try
            {
                _endpoint->open();
                markConnected();
                notify(snapshot(), false);
            }
            catch (const std::exception& error)
            {
                markTransportFailure(error.what());
                notify(snapshot(), false);
                Poco::Thread::sleep(
                    static_cast<long>(_recoveryPolicy.reconnectDelay.count()));
            }
            continue;
        }
        try
        {
            PocoDDS::Protocols::CAN::CanFrame frame;
            if (_endpoint->receive(frame, _recoveryPolicy.receiveTimeout))
            {
                if (frame.error)
                    throw std::runtime_error(
                        "SocketCAN error frame mask=" + std::to_string(frame.id));
                static_cast<void>(ingest(frame));
            }
            checkStale();
        }
        catch (const std::exception& error)
        {
            _endpoint->close();
            markTransportFailure(error.what());
            notify(snapshot(), false);
            if (_recoveryPolicy.enabled)
                Poco::Thread::sleep(
                    static_cast<long>(_recoveryPolicy.reconnectDelay.count()));
        }
    }
}

void CanSignalSensor::markConnected()
{
    Poco::FastMutex::ScopedLock lock(_mutex);
    _state = DeviceState::offline;
    ++_sequence;
    _lastPayload = "waiting-for-frame:" + _endpoint->name();
    _lastFrame = {};
}

void CanSignalSensor::markTransportFailure(const std::string& message)
{
    Poco::FastMutex::ScopedLock lock(_mutex);
    _state = DeviceState::fault;
    ++_sequence;
    ++_diagnostics.failedOperations;
    ++_diagnostics.consecutiveFailures;
    _diagnostics.lastFailureMicroseconds = Poco::Timestamp().epochMicroseconds();
    recordFailure(_diagnostics, _failure, "PDR-DEVICE-CAN-TRANSPORT_FAILED",
                  Reliability::FailureKind::transient, true, message);
    _lastPayload = message;
}

void CanSignalSensor::checkStale()
{
    DeviceSnapshot current;
    bool changed = false;
    {
        Poco::FastMutex::ScopedLock lock(_mutex);
        if (_state == DeviceState::ready && _lastFrame != std::chrono::steady_clock::time_point{} &&
            std::chrono::steady_clock::now() - _lastFrame >= _recoveryPolicy.staleAfter)
        {
            _state = DeviceState::offline;
            ++_sequence;
            ++_diagnostics.failedOperations;
            ++_diagnostics.consecutiveFailures;
            _diagnostics.lastFailureMicroseconds = Poco::Timestamp().epochMicroseconds();
            recordFailure(_diagnostics, _failure, "PDR-DEVICE-CAN-SIGNAL_STALE",
                          Reliability::FailureKind::transient, true,
                          "CAN signal stale");
            _lastPayload = "stale";
            current = {_options.id, _type, _state, _sequence,
                       Poco::Timestamp().epochMicroseconds(), _lastPayload};
            changed = true;
        }
    }
    if (changed)
        notify(current, false);
}

void CanSignalSensor::notify(const DeviceSnapshot& current, bool notifyValue)
{
    SnapshotHandler snapshotHandler;
    ValueHandler valueHandler;
    double currentValue = 0;
    {
        Poco::FastMutex::ScopedLock lock(_mutex);
        snapshotHandler = _snapshotHandler;
        valueHandler = _valueHandler;
        currentValue = _value;
    }
    if (notifyValue && valueHandler)
    {
        try { valueHandler(currentValue); } catch (...) {}
    }
    if (snapshotHandler)
    {
        try { snapshotHandler(current); } catch (...) {}
    }
}

DeviceDiagnostics CanSignalSensor::diagnostics() const
{
    Poco::FastMutex::ScopedLock lock(_mutex);
    return _diagnostics;
}
PocoDDS::Reliability::Failure CanSignalSensor::failure() const
{
    Poco::FastMutex::ScopedLock lock(_mutex);
    return _failure;
}
} // namespace PocoDDS::Devices
