#pragma once

#include "PocoDDS/Devices/DigitalIO.h"
#include "PocoDDS/Devices/Filesystem.h"

#include <Poco/Mutex.h>

#include <chrono>
#include <string>

namespace PocoDDS::Devices
{

class LinuxSysfsGpioDevice final : public DigitalIO, public DiagnosticDevice
{
public:
    enum class Direction { input, output };

    LinuxSysfsGpioDevice(
        std::string id,
        unsigned pin,
        Direction direction,
        PocoDDS::Filesystem::path sysfsRoot = "/sys/class/gpio",
        bool manageExport = true,
        std::chrono::milliseconds exportTimeout = std::chrono::milliseconds(1000));
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
    DeviceDiagnostics diagnostics() const override;

private:
    void writeControl(const PocoDDS::Filesystem::path& file, const std::string& value) const;
    void markSuccess(const std::string& payload) const;
    void markFailure(const std::string& message) const;
    void notify(const DeviceSnapshot& snapshot, const std::uint32_t* value = nullptr) const;

    std::string _id;
    std::string _type{"gpio.sysfs"};
    unsigned _pin;
    Direction _direction;
    PocoDDS::Filesystem::path _root;
    bool _manageExport;
    std::chrono::milliseconds _exportTimeout;
    mutable bool _exportedByUs{false};
    mutable DeviceState _state{DeviceState::offline};
    mutable std::uint64_t _sequence{0};
    mutable std::string _lastPayload{"stopped"};
    mutable DeviceDiagnostics _diagnostics;
    mutable Poco::FastMutex _mutex;
    SnapshotHandler _snapshotHandler;
    ValueHandler _valueHandler;
};

} // namespace PocoDDS::Devices
