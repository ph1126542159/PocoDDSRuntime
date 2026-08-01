#pragma once

#include "PocoDDS/Devices/DigitalIO.h"
#include "PocoDDS/Devices/Filesystem.h"

#include <Poco/Mutex.h>

#include <string>

namespace PocoDDS::Devices
{
class LinuxSysfsLedDevice final : public LED, public DiagnosticDevice
{
public:
    LinuxSysfsLedDevice(std::string id, PocoDDS::Filesystem::path ledDirectory);
    ~LinuxSysfsLedDevice() override;
    const std::string& id() const noexcept override;
    const std::string& type() const noexcept override;
    void start() override;
    void stop() noexcept override;
    DeviceSnapshot snapshot() const override;
    std::string execute(const std::string& operation, const std::string& payload) override;
    void setSnapshotHandler(SnapshotHandler handler) override;
    void setBrightness(double brightness) override;
    double brightness() const override;
    DeviceDiagnostics diagnostics() const override;

private:
    void markSuccess(const std::string& payload) const;
    void markFailure(const std::string& message) const;
    void notify(const DeviceSnapshot& snapshot) const;
    std::string _id;
    std::string _type{"led.sysfs"};
    PocoDDS::Filesystem::path _directory;
    mutable Poco::FastMutex _mutex;
    mutable DeviceState _state{DeviceState::offline};
    mutable unsigned _maxBrightness{0};
    mutable std::uint64_t _sequence{0};
    mutable std::string _lastPayload{"stopped"};
    mutable DeviceDiagnostics _diagnostics;
    SnapshotHandler _snapshotHandler;
};
} // namespace PocoDDS::Devices
