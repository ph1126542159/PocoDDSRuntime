#include "PocoDDS/Devices/ModbusRegisterDevice.h"

#include "Poco/Timestamp.h"

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
    std::uint8_t unitId)
    : _id(std::move(id)), _client(std::move(client)), _unitId(unitId)
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
    std::string result;
    if (operation == "readHolding")
    {
        result = join(_client->readHoldingRegisters(
            _unitId, parameters[0], parameters[1]));
    }
    else if (operation == "readInput")
    {
        result = join(
            _client->readInputRegisters(_unitId, parameters[0], parameters[1]));
    }
    else if (operation == "writeRegister")
    {
        _client->writeSingleRegister(_unitId, parameters[0], parameters[1]);
        result = "ok";
    }
    else
    {
        throw std::invalid_argument("unsupported Modbus operation: " + operation);
    }

    {
        Poco::FastMutex::ScopedLock lock(_mutex);
        ++_sequence;
        _lastPayload = result;
    }
    notify();
    return result;
}

void ModbusRegisterDevice::setSnapshotHandler(SnapshotHandler handler)
{
    Poco::FastMutex::ScopedLock lock(_mutex);
    _handler = std::move(handler);
}

void ModbusRegisterDevice::notify()
{
    SnapshotHandler handler;
    {
        Poco::FastMutex::ScopedLock lock(_mutex);
        handler = _handler;
    }
    if (handler)
        handler(snapshot());
}
} // namespace PocoDDS::Devices
