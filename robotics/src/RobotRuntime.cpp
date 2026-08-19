#include "PocoDDS/Robotics/RobotRuntime.h"

#include <stdexcept>
#include <utility>

namespace PocoDDS::Robotics
{
RobotRuntime::RobotRuntime(std::unique_ptr<SimulationAdapter> simulator,
                           SafetyLimits safetyLimits)
    : _simulator(std::move(simulator)), _safety(safetyLimits)
{
    if (!_simulator)
        throw std::invalid_argument("simulation adapter is required");
}

void RobotRuntime::setWorld(std::string world)
{
    if (state() != LifecycleState::unconfigured)
        throw std::logic_error("world can only be set while unconfigured");
    _world = std::move(world);
}

void RobotRuntime::setEmergencyStop(bool engaged, std::string reason)
{
    std::lock_guard<std::mutex> lock(_operationMutex);
    _safety.setEmergencyStop(engaged, std::move(reason));
    if (engaged && _simulator->connected())
        _simulator->applyCommand({});
}

bool RobotRuntime::emergencyStop() const noexcept
{
    return _safety.emergencyStop();
}

SafetyDecision RobotRuntime::commandVelocity(
    const Twist& command, std::chrono::steady_clock::time_point timestamp)
{
    RobotCommand robotCommand;
    robotCommand.baseVelocity = command;
    return this->command(robotCommand, timestamp);
}

SafetyDecision RobotRuntime::command(
    const RobotCommand& command, std::chrono::steady_clock::time_point timestamp)
{
    std::lock_guard<std::mutex> lock(_operationMutex);
    if (!_acceptCommands)
        return {false, {}, "runtime is not active"};
    auto decision = _safety.evaluate(command, timestamp, std::chrono::steady_clock::now());
    _simulator->applyCommand(decision.permitted ? decision.command : RobotCommand{});
    return decision;
}

RobotFrame RobotRuntime::step(std::chrono::nanoseconds duration)
{
    std::lock_guard<std::mutex> lock(_operationMutex);
    if (!_acceptCommands)
        throw std::logic_error("runtime is not active");
    return _simulator->step(duration);
}

bool RobotRuntime::onConfigure()
{
    std::lock_guard<std::mutex> lock(_operationMutex);
    return _simulator->connect(_world);
}

bool RobotRuntime::onActivate()
{
    std::lock_guard<std::mutex> lock(_operationMutex);
    _acceptCommands = _simulator->connected();
    return _acceptCommands;
}

bool RobotRuntime::onDeactivate()
{
    std::lock_guard<std::mutex> lock(_operationMutex);
    _acceptCommands = false;
    _simulator->applyCommand({});
    return true;
}

bool RobotRuntime::onCleanup()
{
    std::lock_guard<std::mutex> lock(_operationMutex);
    _acceptCommands = false;
    _simulator->reset();
    return true;
}

void RobotRuntime::onShutdown() noexcept
{
    std::lock_guard<std::mutex> lock(_operationMutex);
    _acceptCommands = false;
    try
    {
        if (_simulator->connected())
            _simulator->applyCommand({});
    }
    catch (...)
    {
    }
}
} // namespace PocoDDS::Robotics
