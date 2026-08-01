#include "PocoDDS/Protocols/Modbus/ModbusTcpClient.h"
#include "PocoDDS/Protocols/ProtocolMetrics.h"

#include "Poco/Net/Socket.h"

#include <stdexcept>

namespace PocoDDS::Protocols::Modbus
{
namespace
{
std::uint16_t read16(const std::uint8_t* bytes)
{
    return static_cast<std::uint16_t>((static_cast<std::uint16_t>(bytes[0]) << 8) | bytes[1]);
}
} // namespace

ModbusTcpClient::ModbusTcpClient(Poco::Net::SocketAddress server, Poco::Timespan timeout)
    : _server(std::move(server)), _timeout(timeout)
{
}

ModbusTcpClient::~ModbusTcpClient()
{
    close();
}

std::string ModbusTcpClient::name() const
{
    return "modbus-tcp:" + _server.toString();
}

void ModbusTcpClient::open()
{
    Poco::FastMutex::ScopedLock lock(_mutex);
    if (_open)
        return;
    PocoDDS::Protocols::ProtocolMetricTimer metric("modbus-tcp", "connect");
    _socket.connect(_server, _timeout);
    _socket.setNoDelay(true);
    _open = true;
    metric.success();
}

void ModbusTcpClient::close() noexcept
{
    Poco::FastMutex::ScopedLock lock(_mutex);
    if (!_open)
        return;
    try
    {
        _socket.close();
    }
    catch (...)
    {
    }
    _open = false;
}

bool ModbusTcpClient::isOpen() const noexcept
{
    Poco::FastMutex::ScopedLock lock(_mutex);
    return _open;
}

std::vector<std::uint16_t> ModbusTcpClient::readHoldingRegisters(
    std::uint8_t unitId,
    std::uint16_t address,
    std::uint16_t count)
{
    PocoDDS::Protocols::ProtocolMetricTimer metric("modbus-tcp", "read-holding-registers");
    Poco::FastMutex::ScopedLock lock(_mutex);
    const auto transaction = _nextTransaction++;
    const auto response = transact(ModbusTcpCodec::readRegisters(
        transaction, unitId, FunctionCode::readHoldingRegisters, address, count));
    if (response.exception)
        throw std::runtime_error("Modbus exception: " + std::to_string(response.exceptionCode));
    if (response.function != FunctionCode::readHoldingRegisters || response.data.empty() ||
        response.data.front() != count * 2 || response.data.size() != count * 2 + 1)
        throw std::runtime_error("invalid Modbus holding-register response");

    std::vector<std::uint16_t> values;
    values.reserve(count);
    for (std::size_t i = 1; i < response.data.size(); i += 2)
        values.push_back(read16(response.data.data() + i));
    metric.success();
    return values;
}

std::vector<std::uint16_t> ModbusTcpClient::readInputRegisters(
    std::uint8_t unitId,
    std::uint16_t address,
    std::uint16_t count)
{
    PocoDDS::Protocols::ProtocolMetricTimer metric("modbus-tcp", "read-input-registers");
    Poco::FastMutex::ScopedLock lock(_mutex);
    const auto transaction = _nextTransaction++;
    const auto response = transact(ModbusTcpCodec::readRegisters(
        transaction, unitId, FunctionCode::readInputRegisters, address, count));
    if (response.exception)
        throw std::runtime_error("Modbus exception: " + std::to_string(response.exceptionCode));
    if (response.function != FunctionCode::readInputRegisters || response.data.empty() ||
        response.data.front() != count * 2 || response.data.size() != count * 2 + 1)
        throw std::runtime_error("invalid Modbus input-register response");

    std::vector<std::uint16_t> values;
    values.reserve(count);
    for (std::size_t i = 1; i < response.data.size(); i += 2)
        values.push_back(read16(response.data.data() + i));
    metric.success();
    return values;
}

void ModbusTcpClient::writeSingleRegister(std::uint8_t unitId,
                                          std::uint16_t address,
                                          std::uint16_t value)
{
    PocoDDS::Protocols::ProtocolMetricTimer metric("modbus-tcp", "write-single-register");
    Poco::FastMutex::ScopedLock lock(_mutex);
    const auto transaction = _nextTransaction++;
    const auto response =
        transact(ModbusTcpCodec::writeSingleRegister(transaction, unitId, address, value));
    if (response.exception)
        throw std::runtime_error("Modbus exception: " + std::to_string(response.exceptionCode));
    if (response.function != FunctionCode::writeSingleRegister || response.data.size() != 4 ||
        read16(response.data.data()) != address || read16(response.data.data() + 2) != value)
        throw std::runtime_error("invalid Modbus write-single-register response");
    metric.success();
}

Response ModbusTcpClient::transact(const std::vector<std::uint8_t>& request)
{
    if (!_open)
        throw std::logic_error("Modbus TCP client is not open");
    try
    {
        sendAll(request.data(), request.size());

        std::vector<std::uint8_t> response(6);
        receiveAll(response.data(), response.size());
        const auto remaining = read16(response.data() + 4);
        if (remaining < 3 || remaining > 254)
            throw std::runtime_error("invalid Modbus TCP response length");
        response.resize(6 + remaining);
        receiveAll(response.data() + 6, remaining);
        return ModbusTcpCodec::decodeResponse(response.data(), response.size());
    }
    catch (...)
    {
        // A stream cannot be considered reusable after a partial request,
        // timeout, reset or malformed frame. Publish the real state so callers
        // can apply their retry policy and reconnect with open().
        try
        {
            _socket.close();
        }
        catch (...)
        {
        }
        _open = false;
        throw;
    }
}

void ModbusTcpClient::sendAll(const std::uint8_t* data, std::size_t size)
{
    std::size_t offset = 0;
    while (offset < size)
    {
        const int sent =
            _socket.sendBytes(data + offset, static_cast<int>(size - offset));
        if (sent <= 0)
            throw std::runtime_error("Modbus TCP connection closed while sending");
        offset += static_cast<std::size_t>(sent);
    }
}

void ModbusTcpClient::receiveAll(std::uint8_t* data, std::size_t size)
{
    std::size_t offset = 0;
    while (offset < size)
    {
        if (!_socket.poll(_timeout, Poco::Net::Socket::SELECT_READ))
            throw std::runtime_error("Modbus TCP receive timeout");
        const int received =
            _socket.receiveBytes(data + offset, static_cast<int>(size - offset));
        if (received <= 0)
            throw std::runtime_error("Modbus TCP connection closed while receiving");
        offset += static_cast<std::size_t>(received);
    }
}
} // namespace PocoDDS::Protocols::Modbus
