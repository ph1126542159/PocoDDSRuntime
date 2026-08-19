#include "PocoDDS/Robotics/MockHardware.h"

#include <algorithm>
#include <stdexcept>
#include <unordered_set>
#include <utility>

namespace PocoDDS::Robotics
{
MockHardware::MockHardware(std::vector<std::string> jointNames) : _jointNames(std::move(jointNames))
{
}

std::string MockHardware::name() const { return "mock-hardware"; }

bool MockHardware::configure(const std::string& hardwareDescription)
{
    std::lock_guard<std::mutex> lock(_mutex);
    if (hardwareDescription.empty())
    {
        _health.detail = "hardware description is empty";
        return false;
    }
    _frame = {};
    _frame.state.frameId = "base_link";
    for (const auto& jointName : _jointNames)
        _frame.state.joints.push_back({jointName});
    _command = {};
    _health = {true, false, true, 0, 0, "configured"};
    return true;
}

bool MockHardware::activate()
{
    std::lock_guard<std::mutex> lock(_mutex);
    if (!_health.configured)
        return false;
    _health.active = true;
    _health.ready = _fault == MockHardwareFault::none || _fault == MockHardwareFault::staleFeedback;
    _health.detail = _health.ready ? "ready" : "fault injected";
    return _health.ready;
}

void MockHardware::deactivate() noexcept
{
    std::lock_guard<std::mutex> lock(_mutex);
    _health.active = false;
    _health.ready = false;
    _health.detail = "inactive";
    _command = {};
    _frame.state.twist = {};
}

void MockHardware::reset()
{
    std::lock_guard<std::mutex> lock(_mutex);
    _frame = {};
    _command = {};
    _health = {};
    _fault = MockHardwareFault::none;
}

RobotFrame MockHardware::read(std::chrono::nanoseconds period)
{
    std::lock_guard<std::mutex> lock(_mutex);
    if (!_health.active)
        throw std::logic_error("mock hardware is inactive");
    if (_fault == MockHardwareFault::readFailure)
    {
        _health.ready = false;
        _health.detail = "injected read failure";
        throw std::runtime_error(_health.detail);
    }
    ++_health.readCount;
    if (_fault != MockHardwareFault::staleFeedback)
        _frame.state.monotonicTimeNanoseconds += period.count();
    return _frame;
}

bool MockHardware::write(const RobotCommand& command, std::chrono::nanoseconds)
{
    std::lock_guard<std::mutex> lock(_mutex);
    if (!_health.active || _fault == MockHardwareFault::writeFailure)
    {
        _health.ready = false;
        _health.detail = _health.active ? "injected write failure" : "inactive";
        return false;
    }
    std::unordered_set<std::string> requestedNames;
    for (const auto& requested : command.joints)
    {
        const auto found = std::find_if(_frame.state.joints.begin(), _frame.state.joints.end(),
                                        [&requested](const JointState& state)
                                        { return state.name == requested.name; });
        if (found == _frame.state.joints.end())
        {
            _health.ready = false;
            _health.detail = "unknown joint: " + requested.name;
            return false;
        }
        if (!requestedNames.emplace(requested.name).second)
        {
            _health.ready = false;
            _health.detail = "duplicate joint command: " + requested.name;
            return false;
        }
    }

    ++_health.writeCount;
    _command = command;
    _frame.state.twist = command.baseVelocity;
    for (const auto& requested : command.joints)
    {
        const auto found = std::find_if(_frame.state.joints.begin(), _frame.state.joints.end(),
                                        [&requested](const JointState& state)
                                        { return state.name == requested.name; });
        if (requested.mode == JointCommandMode::position)
            found->position = requested.value;
        else if (requested.mode == JointCommandMode::velocity)
            found->velocity = requested.value;
        else
            found->effort = requested.value;
    }
    _health.ready = true;
    _health.detail = "ready";
    return true;
}

BackendHealth MockHardware::health() const
{
    std::lock_guard<std::mutex> lock(_mutex);
    return _health;
}

void MockHardware::injectFault(MockHardwareFault fault)
{
    std::lock_guard<std::mutex> lock(_mutex);
    _fault = fault;
    if (fault != MockHardwareFault::none && fault != MockHardwareFault::staleFeedback)
    {
        _health.ready = false;
        _health.detail = "fault injected";
    }
}

MockHardwareFault MockHardware::fault() const noexcept
{
    std::lock_guard<std::mutex> lock(_mutex);
    return _fault;
}
} // namespace PocoDDS::Robotics
