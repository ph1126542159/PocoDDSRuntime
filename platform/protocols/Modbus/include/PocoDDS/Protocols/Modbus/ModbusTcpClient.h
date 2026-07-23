#pragma once

#include "PocoDDS/Protocols/Modbus/ModbusTcpCodec.h"
#include "PocoDDS/Protocols/Protocol.h"

#include "Poco/Mutex.h"
#include "Poco/Net/SocketAddress.h"
#include "Poco/Net/StreamSocket.h"
#include "Poco/Timespan.h"

#include <cstdint>
#include <string>
#include <vector>

namespace PocoDDS::Protocols::Modbus
{
class ModbusTcpClient final : public PocoDDS::Protocols::Protocol
{
public:
    explicit ModbusTcpClient(Poco::Net::SocketAddress server,
                             Poco::Timespan timeout = Poco::Timespan(2, 0));
    ~ModbusTcpClient() override;

    std::string name() const override;
    void open() override;
    void close() noexcept override;
    bool isOpen() const noexcept override;

    std::vector<std::uint16_t> readHoldingRegisters(std::uint8_t unitId,
                                                    std::uint16_t address,
                                                    std::uint16_t count);
    std::vector<std::uint16_t> readInputRegisters(std::uint8_t unitId,
                                                  std::uint16_t address,
                                                  std::uint16_t count);
    void writeSingleRegister(std::uint8_t unitId,
                             std::uint16_t address,
                             std::uint16_t value);

private:
    Response transact(const std::vector<std::uint8_t>& request);
    void sendAll(const std::uint8_t* data, std::size_t size);
    void receiveAll(std::uint8_t* data, std::size_t size);

    Poco::Net::SocketAddress _server;
    Poco::Timespan _timeout;
    Poco::Net::StreamSocket _socket;
    mutable Poco::FastMutex _mutex;
    std::uint16_t _nextTransaction{1};
    bool _open{false};
};
} // namespace PocoDDS::Protocols::Modbus
