#include "PocoDDS/Protocols/Modbus/ModbusTcpCodec.h"

#include <stdexcept>

namespace PocoDDS::Protocols::Modbus
{
namespace
{
void append16(std::vector<std::uint8_t>& output, std::uint16_t value)
{
    output.push_back(static_cast<std::uint8_t>(value >> 8));
    output.push_back(static_cast<std::uint8_t>(value & 0xFF));
}

std::uint16_t read16(const std::uint8_t* bytes)
{
    return static_cast<std::uint16_t>((static_cast<std::uint16_t>(bytes[0]) << 8) | bytes[1]);
}

std::vector<std::uint8_t> requestHeader(std::uint16_t transactionId,
                                        std::uint8_t unitId,
                                        FunctionCode function)
{
    std::vector<std::uint8_t> frame;
    frame.reserve(12);
    append16(frame, transactionId);
    append16(frame, 0);
    append16(frame, 6);
    frame.push_back(unitId);
    frame.push_back(static_cast<std::uint8_t>(function));
    return frame;
}
} // namespace

std::vector<std::uint8_t> ModbusTcpCodec::readRegisters(std::uint16_t transactionId,
                                                        std::uint8_t unitId,
                                                        FunctionCode function,
                                                        std::uint16_t address,
                                                        std::uint16_t count)
{
    if (function != FunctionCode::readHoldingRegisters &&
        function != FunctionCode::readInputRegisters)
        throw std::invalid_argument("function is not a register-read function");
    if (count == 0 || count > 125)
        throw std::out_of_range("Modbus register count must be in [1, 125]");

    auto frame = requestHeader(transactionId, unitId, function);
    append16(frame, address);
    append16(frame, count);
    return frame;
}

std::vector<std::uint8_t> ModbusTcpCodec::writeSingleRegister(std::uint16_t transactionId,
                                                             std::uint8_t unitId,
                                                             std::uint16_t address,
                                                             std::uint16_t value)
{
    auto frame =
        requestHeader(transactionId, unitId, FunctionCode::writeSingleRegister);
    append16(frame, address);
    append16(frame, value);
    return frame;
}

Response ModbusTcpCodec::decodeResponse(const std::uint8_t* bytes, std::size_t size)
{
    if (!bytes || size < 9)
        throw std::invalid_argument("incomplete Modbus TCP response");
    if (read16(bytes + 2) != 0)
        throw std::invalid_argument("invalid Modbus protocol identifier");

    const std::uint16_t declaredLength = read16(bytes + 4);
    if (declaredLength < 3 || static_cast<std::size_t>(declaredLength) + 6 != size)
        throw std::invalid_argument("invalid Modbus TCP length");

    Response response;
    response.transactionId = read16(bytes);
    response.unitId = bytes[6];
    response.exception = (bytes[7] & 0x80) != 0;
    response.function = static_cast<FunctionCode>(bytes[7] & 0x7F);
    if (response.exception)
        response.exceptionCode = bytes[8];
    else
        response.data.assign(bytes + 8, bytes + size);
    return response;
}
} // namespace PocoDDS::Protocols::Modbus
