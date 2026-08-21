#include "PocoDDS/Robotics/SafetyBoundary.h"

#include <algorithm>
#include <cmath>
#include <stdexcept>
#include <unordered_set>
#include <utility>

namespace PocoDDS::Robotics
{
namespace
{
double clampMagnitude(double value, double maximum)
{
    return std::max(-maximum, std::min(value, maximum));
}

void clampNorm(Vector3& value, double maximum)
{
    const auto largest = std::max({std::abs(value.x), std::abs(value.y), std::abs(value.z)});
    if (largest == 0.0)
        return;
    const auto normalizedNorm = std::hypot(value.x / largest, value.y / largest, value.z / largest);
    const auto maximumLargest = maximum / normalizedNorm;
    if (largest <= maximumLargest)
        return;
    const auto scale = maximumLargest / largest;
    value.x *= scale;
    value.y *= scale;
    value.z *= scale;
}

bool positiveFinite(double value) { return std::isfinite(value) && value > 0.0; }

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
    return std::all_of(command.joints.begin(), command.joints.end(), [](const JointCommand& joint)
                       { return !joint.name.empty() && std::isfinite(joint.value); });
}
} // namespace

SafetyBoundary::SafetyBoundary(SafetyLimits limits) : _limits(std::move(limits))
{
    if (!positiveFinite(_limits.maximumLinearSpeed) ||
        !positiveFinite(_limits.maximumAngularSpeed) || _limits.commandTimeout.count() <= 0)
        throw std::invalid_argument("safety limits must be positive");
    for (const auto& [name, limit] : _limits.joints)
    {
        if (name.empty() || !std::isfinite(limit.minimumPosition) ||
            !std::isfinite(limit.maximumPosition) ||
            limit.minimumPosition > limit.maximumPosition ||
            !positiveFinite(limit.maximumVelocity) || !positiveFinite(limit.maximumEffort))
            throw std::invalid_argument("invalid joint safety limit: " + name);
    }
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

SafetyDecision SafetyBoundary::evaluate(const RobotCommand& requested,
                                        std::chrono::steady_clock::time_point commandTime,
                                        std::chrono::steady_clock::time_point now) const
{
    std::lock_guard<std::mutex> lock(_mutex);
    if (_emergencyStop)
        return {false, {}, _emergencyStopReason};
    if (commandTime > now || now - commandTime > _limits.commandTimeout)
        return {false, {}, "command watchdog expired"};
    if (!finite(requested))
        return {false, {}, "non-finite command"};

    std::unordered_set<std::string> commandedJoints;
    for (const auto& joint : requested.joints)
    {
        if (!commandedJoints.emplace(joint.name).second)
            return {false, {}, "duplicate joint command: " + joint.name};
    }

    auto limited = requested;
    auto& velocity = limited.baseVelocity;
    clampNorm(velocity.linear, _limits.maximumLinearSpeed);
    clampNorm(velocity.angular, _limits.maximumAngularSpeed);
    for (auto& joint : limited.joints)
    {
        const auto found = _limits.joints.find(joint.name);
        if (found == _limits.joints.end())
            return {false, {}, "joint safety limit missing: " + joint.name};
        const auto& limit = found->second;
        if (joint.mode == JointCommandMode::position)
            joint.value =
                std::max(limit.minimumPosition, std::min(joint.value, limit.maximumPosition));
        else if (joint.mode == JointCommandMode::velocity)
            joint.value = clampMagnitude(joint.value, limit.maximumVelocity);
        else
            joint.value = clampMagnitude(joint.value, limit.maximumEffort);
    }
    return {true, limited, "permitted"};
}
} // namespace PocoDDS::Robotics
