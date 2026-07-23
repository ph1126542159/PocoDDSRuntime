#pragma once

#include "PocoDDS/Devices/DigitalIO.h"
#include "PocoDDS/Devices/Filesystem.h"

#include <Poco/Mutex.h>

#include <string>

namespace PocoDDS::Devices
{

class LinuxSysfsGpioDevice final : public DigitalIO
{
public:
    enum class Direction { input, output };

    LinuxSysfsGpioDevice(
        std::string id,
        unsigned pin,
        Direction direction,
        PocoDDS::Filesystem::path sysfsRoot = "/sys/class/gpio",
        bool manageExport = true);
    ~LinuxSysfsGpioDevice() override;

    const std::string& id() const noexcept override;
    const std::string& type() const noexcept override;
    void start() override;
    void stop() noexcept override;
    DeviceSnapshot snapshot() const override;
    std::string execute(const std::string& operation, const std::string& payload) override;
    void setSnapshotHandler(SnapshotHandler handler) override;

    std::uint32_t read() const override;
    void write(std::uint32_t value) override;
    void setValueHandler(ValueHandler handler) override;

private:
    void writeControl(const PocoDDS::Filesystem::path& file, const std::string& value) const;

    std::string _id;
    std::string _type{"gpio.sysfs"};
    unsigned _pin;
    Direction _direction;
    PocoDDS::Filesystem::path _root;
    bool _manageExport;
    bool _started{false};
    std::uint64_t _sequence{0};
    mutable Poco::FastMutex _mutex;
    SnapshotHandler _snapshotHandler;
    ValueHandler _valueHandler;
};

} // namespace PocoDDS::Devices
