#pragma once

#include <cstddef>
#include <cstdint>
#include <vector>

namespace PocoDDS::Protocols::Modbus
{
enum class FunctionCode : std::uint8_t
{
    readCoils = 0x01,
    readDiscreteInputs = 0x02,
    readHoldingRegisters = 0x03,
    readInputRegisters = 0x04,
    writeSingleCoil = 0x05,
    writeSingleRegister = 0x06,
    writeMultipleCoils = 0x0F,
    writeMultipleRegisters = 0x10
};

struct Response
{
    std::uint16_t transactionId{0};
    std::uint8_t unitId{0};
    FunctionCode function{FunctionCode::readHoldingRegisters};
    bool exception{false};
    std::uint8_t exceptionCode{0};
    std::vector<std::uint8_t> data;
};

class ModbusTcpCodec
{
public:
    static std::vector<std::uint8_t> readRegisters(std::uint16_t transactionId,
                                                   std::uint8_t unitId,
                                                   FunctionCode function,
                                                   std::uint16_t address,
                                                   std::uint16_t count);
    static std::vector<std::uint8_t> writeSingleRegister(std::uint16_t transactionId,
                                                        std::uint8_t unitId,
                                                        std::uint16_t address,
                                                        std::uint16_t value);
    static Response decodeResponse(const std::uint8_t* bytes, std::size_t size);
};
} // namespace PocoDDS::Protocols::Modbus
