#include "PocoDDS/Robotics/RobotRuntime.h"

#include <stdexcept>
#include <utility>

namespace PocoDDS::Robotics
{
RobotRuntime::RobotRuntime(std::unique_ptr<RobotBackend> backend, SafetyLimits safetyLimits,
                           Clock clock)
    : _backend(std::move(backend)), _commandTimeout(safetyLimits.commandTimeout),
      _safety(std::move(safetyLimits)), _clock(std::move(clock))
{
    if (!_backend)
        throw std::invalid_argument("robot backend is required");
    if (!_clock)
        throw std::invalid_argument("robot runtime clock is required");
}

void RobotRuntime::setWorld(std::string world) { setBackendDescription(std::move(world)); }

void RobotRuntime::setBackendDescription(std::string description)
{
    if (state() != LifecycleState::unconfigured)
        throw std::logic_error("backend description can only be set while unconfigured");
    _backendDescription = std::move(description);
}

void RobotRuntime::setEmergencyStop(bool engaged, std::string reason)
{
    std::lock_guard<std::mutex> lock(_operationMutex);
    _safety.setEmergencyStop(engaged, std::move(reason));
    if (engaged)
        _lastCommandTime.reset();
    if (engaged && _backend->health().active)
    {
        try
        {
            if (!_backend->write({}, std::chrono::nanoseconds::zero()))
                _acceptCommands = false;
        }
        catch (...)
        {
            _acceptCommands = false;
        }
    }
}

bool RobotRuntime::emergencyStop() const noexcept { return _safety.emergencyStop(); }

SafetyDecision RobotRuntime::commandVelocity(const Twist& command,
                                             std::chrono::steady_clock::time_point timestamp)
{
    RobotCommand robotCommand;
    robotCommand.baseVelocity = command;
    return this->command(robotCommand, timestamp);
}

SafetyDecision RobotRuntime::command(const RobotCommand& command,
                                     std::chrono::steady_clock::time_point timestamp)
{
    std::lock_guard<std::mutex> lock(_operationMutex);
    if (!_acceptCommands)
        return {false, {}, "runtime is not active"};
    const auto now = _clock();
    auto decision = _safety.evaluate(command, timestamp, now);
    bool written = false;
    try
    {
        written = _backend->write(decision.permitted ? decision.command : RobotCommand{},
                                  std::chrono::nanoseconds::zero());
    }
    catch (...)
    {
        _acceptCommands = false;
        _safety.setEmergencyStop(true, "backend write failure");
        return {false, {}, "backend write failure"};
    }
    if (!written)
    {
        _acceptCommands = false;
        _safety.setEmergencyStop(true, decision.permitted ? "backend rejected command"
                                                          : "backend rejected safety stop");
        return {false,
                {},
                decision.permitted ? "backend rejected command" : "backend rejected safety stop"};
    }
    if (decision.permitted)
        _lastCommandTime = now;
    else
        _lastCommandTime.reset();
    return decision;
}

RobotFrame RobotRuntime::step(std::chrono::nanoseconds duration)
{
    std::lock_guard<std::mutex> lock(_operationMutex);
    if (!_acceptCommands)
        throw std::logic_error("runtime is not active");
    const auto now = _clock();
    if (_lastCommandTime && now >= *_lastCommandTime && now - *_lastCommandTime > _commandTimeout)
    {
        try
        {
            if (!_backend->write({}, std::chrono::nanoseconds::zero()))
                throw std::runtime_error("backend rejected watchdog stop");
            _lastCommandTime.reset();
        }
        catch (...)
        {
            _acceptCommands = false;
            _safety.setEmergencyStop(true, "backend watchdog stop failure");
            throw;
        }
    }
    try
    {
        return _backend->read(duration);
    }
    catch (...)
    {
        _acceptCommands = false;
        _safety.setEmergencyStop(true, "backend read failure");
        throw;
    }
}

BackendHealth RobotRuntime::backendHealth() const
{
    std::lock_guard<std::mutex> lock(_operationMutex);
    return _backend->health();
}

bool RobotRuntime::onConfigure()
{
    std::lock_guard<std::mutex> lock(_operationMutex);
    return _backend->configure(_backendDescription);
}

bool RobotRuntime::onActivate()
{
    std::lock_guard<std::mutex> lock(_operationMutex);
    _acceptCommands = _backend->activate();
    _lastCommandTime.reset();
    return _acceptCommands;
}

bool RobotRuntime::onDeactivate()
{
    std::lock_guard<std::mutex> lock(_operationMutex);
    _acceptCommands = false;
    _lastCommandTime.reset();
    bool stopped = false;
    try
    {
        stopped = _backend->write({}, std::chrono::nanoseconds::zero());
    }
    catch (...)
    {
        stopped = false;
    }
    _backend->deactivate();
    return stopped;
}

bool RobotRuntime::onCleanup()
{
    std::lock_guard<std::mutex> lock(_operationMutex);
    _acceptCommands = false;
    _lastCommandTime.reset();
    _backend->reset();
    return true;
}

void RobotRuntime::onShutdown() noexcept
{
    std::lock_guard<std::mutex> lock(_operationMutex);
    _acceptCommands = false;
    _lastCommandTime.reset();
    try
    {
        _backend->write({}, std::chrono::nanoseconds::zero());
    }
    catch (...)
    {
        _backend->deactivate();
        return;
    }
    _backend->deactivate();
}
} // namespace PocoDDS::Robotics
