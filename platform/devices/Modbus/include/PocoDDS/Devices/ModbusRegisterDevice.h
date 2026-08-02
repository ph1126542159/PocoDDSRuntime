#pragma once

#include "PocoDDS/Devices/Device.h"
#include "PocoDDS/Protocols/Modbus/ModbusTcpClient.h"

#include "Poco/Mutex.h"

#include <cstdint>
#include <chrono>
#include <functional>
#include <memory>

namespace PocoDDS::Devices
{
struct ModbusReconnectPolicy
{
    unsigned readRetryAttempts{1};
    std::chrono::milliseconds retryDelay{50};
};

class ModbusRegisterDevice final : public Device, public DiagnosticDevice,
                                   public FailureDiagnosticDevice
{
public:
    ModbusRegisterDevice(std::string id,
                         std::shared_ptr<PocoDDS::Protocols::Modbus::ModbusTcpClient> client,
                         std::uint8_t unitId,
                         ModbusReconnectPolicy reconnectPolicy = {});
    ~ModbusRegisterDevice() override;

    const std::string& id() const noexcept override;
    const std::string& type() const noexcept override;
    void start() override;
    void stop() noexcept override;
    DeviceSnapshot snapshot() const override;
    std::string execute(const std::string& operation, const std::string& payload) override;
    void setSnapshotHandler(SnapshotHandler handler) override;
    DeviceDiagnostics diagnostics() const override;
    PocoDDS::Reliability::Failure failure() const override;

private:
    void notify();
    std::string perform(const std::function<std::string()>& operation, bool replaySafe);
    void markSuccess(const std::string& result);
    void markFailure(const std::string& message);

    const std::string _id;
    const std::string _type{"modbus.registers"};
    std::shared_ptr<PocoDDS::Protocols::Modbus::ModbusTcpClient> _client;
    std::uint8_t _unitId;
    ModbusReconnectPolicy _reconnectPolicy;
    mutable Poco::FastMutex _mutex;
    SnapshotHandler _handler;
    DeviceState _state{DeviceState::offline};
    std::uint64_t _sequence{0};
    std::string _lastPayload;
    DeviceDiagnostics _diagnostics;
    PocoDDS::Reliability::Failure _failure;
};
} // namespace PocoDDS::Devices
