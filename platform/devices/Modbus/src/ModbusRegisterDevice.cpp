#include "PocoDDS/Devices/ModbusRegisterDevice.h"

#include "Poco/Timestamp.h"
#include "Poco/Thread.h"

#include <sstream>
#include <stdexcept>
#include <utility>
#include <vector>

namespace PocoDDS::Devices
{
namespace
{
std::vector<std::uint16_t> parseNumbers(const std::string& payload, std::size_t expected)
{
    std::vector<std::uint16_t> values;
    std::istringstream stream(payload);
    std::string token;
    while (std::getline(stream, token, ','))
    {
        const auto value = std::stoul(token, nullptr, 0);
        if (value > 0xFFFF)
            throw std::out_of_range("Modbus value exceeds uint16");
        values.push_back(static_cast<std::uint16_t>(value));
    }
    if (values.size() != expected)
        throw std::invalid_argument("expected " + std::to_string(expected) +
                                    " comma-separated values");
    return values;
}

std::string join(const std::vector<std::uint16_t>& values)
{
    std::ostringstream output;
    for (std::size_t i = 0; i < values.size(); ++i)
    {
        if (i)
            output << ',';
        output << values[i];
    }
    return output.str();
}
} // namespace

ModbusRegisterDevice::ModbusRegisterDevice(
    std::string id,
    std::shared_ptr<PocoDDS::Protocols::Modbus::ModbusTcpClient> client,
    std::uint8_t unitId,
    ModbusReconnectPolicy reconnectPolicy)
    : _id(std::move(id)), _client(std::move(client)), _unitId(unitId),
      _reconnectPolicy(reconnectPolicy)
{
    if (!_client)
        throw std::invalid_argument("Modbus client is required");
}

ModbusRegisterDevice::~ModbusRegisterDevice()
{
    stop();
}

const std::string& ModbusRegisterDevice::id() const noexcept
{
    return _id;
}

const std::string& ModbusRegisterDevice::type() const noexcept
{
    return _type;
}

void ModbusRegisterDevice::start()
{
    _client->open();
    {
        Poco::FastMutex::ScopedLock lock(_mutex);
        _state = DeviceState::ready;
        ++_sequence;
        _lastPayload = _client->name();
    }
    notify();
}

void ModbusRegisterDevice::stop() noexcept
{
    _client->close();
    Poco::FastMutex::ScopedLock lock(_mutex);
    _state = DeviceState::offline;
}

DeviceSnapshot ModbusRegisterDevice::snapshot() const
{
    Poco::FastMutex::ScopedLock lock(_mutex);
    return {_id,
            _type,
            _state,
            _sequence,
            Poco::Timestamp().epochMicroseconds(),
            _lastPayload};
}

std::string ModbusRegisterDevice::execute(const std::string& operation,
                                          const std::string& payload)
{
    const auto parameters = parseNumbers(payload, 2);
    if (operation == "readHolding")
    {
        return perform([&] {
            return join(_client->readHoldingRegisters(
                _unitId, parameters[0], parameters[1]));
        }, true);
    }
    if (operation == "readInput")
    {
        return perform([&] {
            return join(_client->readInputRegisters(
                _unitId, parameters[0], parameters[1]));
        }, true);
    }
    if (operation == "writeRegister")
    {
        return perform([&] {
            _client->writeSingleRegister(_unitId, parameters[0], parameters[1]);
            return std::string("ok");
        }, false);
    }
    throw std::invalid_argument("unsupported Modbus operation: " + operation);
}

std::string ModbusRegisterDevice::perform(const std::function<std::string()>& operation,
                                          bool replaySafe)
{
    const unsigned attempts = replaySafe ? _reconnectPolicy.readRetryAttempts + 1 : 1;
    for (unsigned attempt = 0; attempt < attempts; ++attempt)
    {
        try
        {
            if (!_client->isOpen())
            {
                {
                    Poco::FastMutex::ScopedLock lock(_mutex);
                    ++_diagnostics.reconnectAttempts;
                }
                _client->open();
            }
            auto result = operation();
            markSuccess(result);
            notify();
            return result;
        }
        catch (const std::exception& error)
        {
            markFailure(error.what());
            _client->close();
            notify();
            if (attempt + 1 >= attempts)
                throw;
            Poco::Thread::sleep(static_cast<long>(_reconnectPolicy.retryDelay.count()));
        }
    }
    throw std::logic_error("unreachable Modbus retry state");
}

void ModbusRegisterDevice::markSuccess(const std::string& result)
{
    {
        Poco::FastMutex::ScopedLock lock(_mutex);
        ++_sequence;
        _lastPayload = result;
        _state = DeviceState::ready;
        ++_diagnostics.successfulOperations;
        _diagnostics.consecutiveFailures = 0;
        _diagnostics.lastSuccessMicroseconds = Poco::Timestamp().epochMicroseconds();
        resolveFailure(_diagnostics, _failure);
    }
}

void ModbusRegisterDevice::markFailure(const std::string& message)
{
    Poco::FastMutex::ScopedLock lock(_mutex);
    ++_sequence;
    _state = DeviceState::fault;
    ++_diagnostics.failedOperations;
    ++_diagnostics.consecutiveFailures;
    _diagnostics.lastFailureMicroseconds = Poco::Timestamp().epochMicroseconds();
    recordFailure(_diagnostics, _failure, "PDR-DEVICE-MODBUS-OPERATION_FAILED",
                  Reliability::FailureKind::transient, true, message);
}

void ModbusRegisterDevice::setSnapshotHandler(SnapshotHandler handler)
{
    Poco::FastMutex::ScopedLock lock(_mutex);
    _handler = std::move(handler);
}

DeviceDiagnostics ModbusRegisterDevice::diagnostics() const
{
    Poco::FastMutex::ScopedLock lock(_mutex);
    return _diagnostics;
}

PocoDDS::Reliability::Failure ModbusRegisterDevice::failure() const
{
    Poco::FastMutex::ScopedLock lock(_mutex);
    return _failure;
}

void ModbusRegisterDevice::notify()
{
    SnapshotHandler handler;
    {
        Poco::FastMutex::ScopedLock lock(_mutex);
        handler = _handler;
    }
    if (handler)
    {
        try { handler(snapshot()); } catch (...) {}
    }
}
} // namespace PocoDDS::Devices
