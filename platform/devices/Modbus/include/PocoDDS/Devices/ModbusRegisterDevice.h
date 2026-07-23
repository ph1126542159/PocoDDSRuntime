#pragma once

#include "PocoDDS/Devices/Device.h"
#include "PocoDDS/Protocols/Modbus/ModbusTcpClient.h"

#include "Poco/Mutex.h"

#include <cstdint>
#include <memory>

namespace PocoDDS::Devices
{
class ModbusRegisterDevice final : public Device
{
public:
    ModbusRegisterDevice(std::string id,
                         std::shared_ptr<PocoDDS::Protocols::Modbus::ModbusTcpClient> client,
                         std::uint8_t unitId);
    ~ModbusRegisterDevice() override;

    const std::string& id() const noexcept override;
    const std::string& type() const noexcept override;
    void start() override;
    void stop() noexcept override;
    DeviceSnapshot snapshot() const override;
    std::string execute(const std::string& operation, const std::string& payload) override;
    void setSnapshotHandler(SnapshotHandler handler) override;

private:
    void notify();

    const std::string _id;
    const std::string _type{"modbus.registers"};
    std::shared_ptr<PocoDDS::Protocols::Modbus::ModbusTcpClient> _client;
    std::uint8_t _unitId;
    mutable Poco::FastMutex _mutex;
    SnapshotHandler _handler;
    DeviceState _state{DeviceState::offline};
    std::uint64_t _sequence{0};
    std::string _lastPayload;
};
} // namespace PocoDDS::Devices
