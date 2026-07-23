#pragma once

#include "PocoDDS/Devices/SerialDevice.h"
#include "PocoDDS/Protocols/Serial/SerialChannel.h"

#include <Poco/Mutex.h>
#include <Poco/Thread.h>

#include <atomic>
#include <memory>
#include <string>

namespace PocoDDS::Devices
{

class SerialPortDevice final : public SerialDevice
{
public:
    SerialPortDevice(std::string id, std::string port, int baudRate);
    ~SerialPortDevice() override;

    const std::string& id() const noexcept override;
    const std::string& type() const noexcept override;
    void start() override;
    void stop() noexcept override;
    DeviceSnapshot snapshot() const override;
    std::string execute(const std::string& operation, const std::string& payload) override;
    void setSnapshotHandler(SnapshotHandler handler) override;

    std::size_t write(const std::vector<std::uint8_t>& data) override;
    void setDataHandler(DataHandler handler) override;

private:
    void run();

    std::string _id;
    std::string _type{"serial"};
    std::unique_ptr<PocoDDS::Protocols::Serial::SerialChannel> _channel;
    std::atomic_bool _running{false};
    mutable Poco::FastMutex _mutex;
    Poco::Thread _thread;
    std::uint64_t _sequence{0};
    SnapshotHandler _snapshotHandler;
    DataHandler _dataHandler;
};

} // namespace PocoDDS::Devices
