#pragma once

#include "PocoDDS/Devices/Device.h"

#include "Poco/Mutex.h"
#include "Poco/Thread.h"

#include <atomic>

namespace PocoDDS::Devices
{
class SimulatedDevice final : public Device
{
public:
    explicit SimulatedDevice(std::string id);
    ~SimulatedDevice() override;

    const std::string& id() const noexcept override;
    const std::string& type() const noexcept override;
    void start() override;
    void stop() noexcept override;
    DeviceSnapshot snapshot() const override;
    std::string execute(const std::string& operation, const std::string& payload) override;
    void setSnapshotHandler(SnapshotHandler handler) override;

private:
    void run();
    DeviceSnapshot makeSnapshot() const;

    const std::string _id;
    const std::string _type{"simulation.sensor"};
    mutable Poco::FastMutex _mutex;
    Poco::Thread _thread;
    std::atomic<bool> _running{false};
    std::uint64_t _sequence{0};
    double _value{20.0};
    SnapshotHandler _handler;
};
} // namespace PocoDDS::Devices
