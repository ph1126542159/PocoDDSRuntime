#include "PocoDDS/Robotics/SafetyBoundary.h"

#include <algorithm>
#include <cmath>
#include <stdexcept>
#include <utility>

namespace PocoDDS::Robotics
{
namespace
{
double clampMagnitude(double value, double maximum)
{
    return std::max(-maximum, std::min(value, maximum));
}

bool finite(const Twist& command)
{
    return std::isfinite(command.linear.x) && std::isfinite(command.linear.y) &&
           std::isfinite(command.linear.z) && std::isfinite(command.angular.x) &&
           std::isfinite(command.angular.y) && std::isfinite(command.angular.z);
}

bool finite(const RobotCommand& command)
{
    if (!finite(command.baseVelocity))
        return false;
    return std::all_of(command.joints.begin(), command.joints.end(),
                       [](const JointCommand& joint) {
                           return !joint.name.empty() && std::isfinite(joint.value);
                       });
}
} // namespace

SafetyBoundary::SafetyBoundary(SafetyLimits limits) : _limits(limits)
{
    if (limits.maximumLinearSpeed <= 0.0 || limits.maximumAngularSpeed <= 0.0 ||
        limits.commandTimeout.count() <= 0)
        throw std::invalid_argument("safety limits must be positive");
}

void SafetyBoundary::setEmergencyStop(bool engaged, std::string reason)
{
    std::lock_guard<std::mutex> lock(_mutex);
    _emergencyStop = engaged;
    _emergencyStopReason = engaged && reason.empty() ? "emergency stop" : std::move(reason);
}

bool SafetyBoundary::emergencyStop() const noexcept
{
    std::lock_guard<std::mutex> lock(_mutex);
    return _emergencyStop;
}

SafetyDecision SafetyBoundary::evaluate(
    const RobotCommand& requested, std::chrono::steady_clock::time_point commandTime,
    std::chrono::steady_clock::time_point now) const
{
    std::lock_guard<std::mutex> lock(_mutex);
    if (_emergencyStop)
        return {false, {}, _emergencyStopReason};
    if (commandTime > now || now - commandTime > _limits.commandTimeout)
        return {false, {}, "command watchdog expired"};
    if (!finite(requested))
        return {false, {}, "non-finite command"};

    auto limited = requested;
    auto& velocity = limited.baseVelocity;
    velocity.linear.x = clampMagnitude(velocity.linear.x, _limits.maximumLinearSpeed);
    velocity.linear.y = clampMagnitude(velocity.linear.y, _limits.maximumLinearSpeed);
    velocity.linear.z = clampMagnitude(velocity.linear.z, _limits.maximumLinearSpeed);
    velocity.angular.x = clampMagnitude(velocity.angular.x, _limits.maximumAngularSpeed);
    velocity.angular.y = clampMagnitude(velocity.angular.y, _limits.maximumAngularSpeed);
    velocity.angular.z = clampMagnitude(velocity.angular.z, _limits.maximumAngularSpeed);
    for (auto& joint : limited.joints)
    {
        const auto found = _limits.joints.find(joint.name);
        if (found == _limits.joints.end())
            return {false, {}, "joint safety limit missing: " + joint.name};
        const auto& limit = found->second;
        if (limit.minimumPosition > limit.maximumPosition || limit.maximumVelocity <= 0.0 ||
            limit.maximumEffort <= 0.0)
            return {false, {}, "invalid joint safety limit: " + joint.name};
        if (joint.mode == JointCommandMode::position)
            joint.value = std::max(limit.minimumPosition,
                                   std::min(joint.value, limit.maximumPosition));
        else if (joint.mode == JointCommandMode::velocity)
            joint.value = clampMagnitude(joint.value, limit.maximumVelocity);
        else
            joint.value = clampMagnitude(joint.value, limit.maximumEffort);
    }
    return {true, limited, "permitted"};
}
} // namespace PocoDDS::Robotics
