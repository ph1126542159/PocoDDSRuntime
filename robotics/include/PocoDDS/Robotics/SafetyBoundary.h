#pragma once

#include "PocoDDS/Robotics/Types.h"

#include <chrono>
#include <mutex>
#include <string>
#include <unordered_map>

namespace PocoDDS::Robotics
{
struct JointSafetyLimit
{
    double minimumPosition{-3.141592653589793};
    double maximumPosition{3.141592653589793};
    double maximumVelocity{1.0};
    double maximumEffort{1.0};
};

struct SafetyLimits
{
    double maximumLinearSpeed{1.0};
    double maximumAngularSpeed{1.0};
    std::chrono::milliseconds commandTimeout{250};
    std::unordered_map<std::string, JointSafetyLimit> joints;
};

struct SafetyDecision
{
    bool permitted{false};
    RobotCommand command;
    std::string reason;
};

class SafetyBoundary
{
public:
    explicit SafetyBoundary(SafetyLimits limits = {});
    void setEmergencyStop(bool engaged, std::string reason = {});
    bool emergencyStop() const noexcept;
    SafetyDecision evaluate(const RobotCommand& requested,
                            std::chrono::steady_clock::time_point commandTime,
                            std::chrono::steady_clock::time_point now) const;

private:
    SafetyLimits _limits;
    mutable std::mutex _mutex;
    bool _emergencyStop{true};
    std::string _emergencyStopReason{"startup interlock"};
};
} // namespace PocoDDS::Robotics
