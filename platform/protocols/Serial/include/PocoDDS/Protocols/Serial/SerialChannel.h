#pragma once

#include "PocoDDS/Protocols/Protocol.h"

#include "Poco/Serial/SerialPort.h"
#include "Poco/Timespan.h"

#include <cstddef>
#include <atomic>
#include <cstdint>
#include <string>
#include <vector>

namespace PocoDDS::Protocols::Serial
{
class ISerialChannel : public PocoDDS::Protocols::Protocol
{
public:
    ~ISerialChannel() override = default;
    virtual std::size_t write(const std::uint8_t* data, std::size_t size) = 0;
    virtual std::vector<std::uint8_t> read(std::size_t size, Poco::Timespan timeout) = 0;
};

class SerialChannel final : public ISerialChannel
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

    std::size_t write(const std::uint8_t* data, std::size_t size) override;
    std::vector<std::uint8_t> read(std::size_t size, Poco::Timespan timeout) override;
    Poco::Serial::SerialPort& port() noexcept;

private:
    std::string _device;
    int _baudRate;
    std::string _parameters;
    Poco::Serial::SerialPort::FlowControl _flowControl;
    Poco::Serial::SerialPort _port;
    std::atomic_bool _open{false};
};
} // namespace PocoDDS::Protocols::Serial
