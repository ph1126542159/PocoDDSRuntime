#pragma once

#include "PocoDDS/Robotics/Types.h"

#include <chrono>
#include <string>

namespace PocoDDS::Robotics
{
class HardwareInterface
{
public:
    virtual ~HardwareInterface() = default;
    virtual std::string name() const = 0;
    virtual bool configure(const std::string& hardwareDescription) = 0;
    virtual bool activate() = 0;
    virtual RobotFrame read(std::chrono::nanoseconds period) = 0;
    virtual bool write(const RobotCommand& command, std::chrono::nanoseconds period) = 0;
    virtual void deactivate() noexcept = 0;
};
} // namespace PocoDDS::Robotics
