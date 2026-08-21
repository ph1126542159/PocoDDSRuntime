#pragma once

#include "PocoDDS/Robotics/Backend.h"

#include <chrono>
#include <string>

namespace PocoDDS::Robotics
{
class HardwareInterface : public RobotBackend
{
  public:
    virtual ~HardwareInterface() = default;
    BackendKind kind() const noexcept final { return BackendKind::hardware; }
};
} // namespace PocoDDS::Robotics
