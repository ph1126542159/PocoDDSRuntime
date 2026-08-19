#pragma once

#include "PocoDDS/Robotics/Types.h"

#include <chrono>
#include <cstdint>
#include <string>

namespace PocoDDS::Robotics
{
enum class BackendKind
{
    simulation,
    hardware
};

struct BackendHealth
{
    bool configured{false};
    bool active{false};
    bool ready{false};
    std::uint64_t readCount{0};
    std::uint64_t writeCount{0};
    std::string detail{"unconfigured"};
};

class RobotBackend
{
  public:
    virtual ~RobotBackend() = default;
    virtual BackendKind kind() const noexcept = 0;
    virtual std::string name() const = 0;
    virtual bool configure(const std::string& description) = 0;
    virtual bool activate() = 0;
    virtual void deactivate() noexcept = 0;
    virtual void reset() = 0;
    virtual RobotFrame read(std::chrono::nanoseconds period) = 0;
    virtual bool write(const RobotCommand& command, std::chrono::nanoseconds period) = 0;
    virtual BackendHealth health() const = 0;
};
} // namespace PocoDDS::Robotics
