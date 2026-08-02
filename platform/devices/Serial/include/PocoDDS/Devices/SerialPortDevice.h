#pragma once

#include "PocoDDS/Devices/SerialDevice.h"
#include "PocoDDS/Protocols/Serial/SerialChannel.h"

#include <Poco/Mutex.h>
#include <Poco/Thread.h>

#include <atomic>
#include <chrono>
#include <memory>
#include <string>

namespace PocoDDS::Devices
{

struct SerialReconnectPolicy
{
    bool enabled{true};
    std::chrono::milliseconds delay{250};
    std::chrono::milliseconds readTimeout{250};
};

class SerialPortDevice final : public SerialDevice, public DiagnosticDevice,
                               public FailureDiagnosticDevice
{
public:
    SerialPortDevice(std::string id, std::string port, int baudRate,
                     SerialReconnectPolicy reconnectPolicy = {});
    SerialPortDevice(
        std::string id,
        std::shared_ptr<PocoDDS::Protocols::Serial::ISerialChannel> channel,
        SerialReconnectPolicy reconnectPolicy = {});
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
    DeviceDiagnostics diagnostics() const override;
    PocoDDS::Reliability::Failure failure() const override;

private:
    void run();
    void markReady();
    void markFailure(const std::string& message);
    void notify(const DeviceSnapshot& snapshot, const std::vector<std::uint8_t>* data = nullptr);

    std::string _id;
    std::string _type{"serial"};
    std::shared_ptr<PocoDDS::Protocols::Serial::ISerialChannel> _channel;
    SerialReconnectPolicy _reconnectPolicy;
    std::atomic_bool _running{false};
    mutable Poco::FastMutex _mutex;
    Poco::Thread _thread;
    std::uint64_t _sequence{0};
    DeviceState _state{DeviceState::offline};
    std::string _lastPayload;
    DeviceDiagnostics _diagnostics;
    PocoDDS::Reliability::Failure _failure;
    SnapshotHandler _snapshotHandler;
    DataHandler _dataHandler;
};

} // namespace PocoDDS::Devices
