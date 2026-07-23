#pragma once

#include "PocoDDS/Devices/DigitalIO.h"
#include "PocoDDS/Devices/Filesystem.h"

#include <Poco/Mutex.h>

#include <string>

namespace PocoDDS::Devices
{
class LinuxSysfsLedDevice final : public LED
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

private:
    std::string _id;
    std::string _type{"led.sysfs"};
    PocoDDS::Filesystem::path _directory;
    mutable Poco::FastMutex _mutex;
    bool _started{false};
    unsigned _maxBrightness{0};
    std::uint64_t _sequence{0};
    SnapshotHandler _snapshotHandler;
};
} // namespace PocoDDS::Devices
