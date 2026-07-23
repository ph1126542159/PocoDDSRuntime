#pragma once

#include "PocoDDS/Protocols/Protocol.h"

#include "Poco/Serial/SerialPort.h"
#include "Poco/Timespan.h"

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace PocoDDS::Protocols::Serial
{
class SerialChannel final : public PocoDDS::Protocols::Protocol
{
public:
    SerialChannel(std::string device,
                  int baudRate,
                  std::string parameters = "8N1",
                  Poco::Serial::SerialPort::FlowControl flowControl =
                      Poco::Serial::SerialPort::FLOW_NONE);
    ~SerialChannel() override;

    std::string name() const override;
    void open() override;
    void close() noexcept override;
    bool isOpen() const noexcept override;

    std::size_t write(const std::uint8_t* data, std::size_t size);
    std::vector<std::uint8_t> read(std::size_t size, Poco::Timespan timeout);
    Poco::Serial::SerialPort& port() noexcept;

private:
    std::string _device;
    int _baudRate;
    std::string _parameters;
    Poco::Serial::SerialPort::FlowControl _flowControl;
    Poco::Serial::SerialPort _port;
    bool _open{false};
};
} // namespace PocoDDS::Protocols::Serial
