#pragma once

#include <cstdint>
#include <functional>
#include <string>

namespace PocoDDS::Devices
{
enum class DeviceState
{
    offline,
    ready,
    fault
};

struct DeviceSnapshot
{
    std::string id;
    std::string type;
    DeviceState state{DeviceState::offline};
    std::uint64_t sequence{0};
    std::int64_t timestampMicroseconds{0};
    std::string payload;
};

class Device
{
public:
    using SnapshotHandler = std::function<void(const DeviceSnapshot&)>;

    virtual ~Device() = default;

    virtual const std::string& id() const noexcept = 0;
    virtual const std::string& type() const noexcept = 0;
    virtual void start() = 0;
    virtual void stop() noexcept = 0;
    virtual DeviceSnapshot snapshot() const = 0;
    virtual std::string execute(const std::string& operation, const std::string& payload) = 0;
    virtual void setSnapshotHandler(SnapshotHandler handler) = 0;
};

const char* toString(DeviceState state) noexcept;
} // namespace PocoDDS::Devices
