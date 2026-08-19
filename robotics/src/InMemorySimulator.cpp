#include "PocoDDS/Robotics/SimulationAdapter.h"

#include <algorithm>
#include <cmath>
#include <iterator>
#include <stdexcept>

namespace PocoDDS::Robotics
{
void SimulationAdapter::deactivate() noexcept
{
    _backendActive = false;
    try
    {
        applyCommand({});
    }
    catch (...)
    {
    }
}

bool SimulationAdapter::write(const RobotCommand& command, std::chrono::nanoseconds)
{
    applyCommand(command);
    return true;
}

std::string InMemorySimulator::backendName() const { return "in-memory"; }

bool InMemorySimulator::connect(const std::string& world)
{
    if (world.empty())
        return false;
    std::lock_guard<std::mutex> lock(_mutex);
    _world = world;
    _connected = true;
    _backendActive = false;
    _frame = {};
    _command = {};
    _yaw = 0.0;
    _readCount = 0;
    _writeCount = 0;
    _frame.state.frameId = "world";
    return true;
}

void InMemorySimulator::reset()
{
    std::lock_guard<std::mutex> lock(_mutex);
    _frame = {};
    _command = {};
    _yaw = 0.0;
    _readCount = 0;
    _writeCount = 0;
    _connected = false;
    _backendActive = false;
    _frame.state.frameId = "world";
}

void InMemorySimulator::applyCommand(const RobotCommand& command)
{
    std::lock_guard<std::mutex> lock(_mutex);
    if (!_connected)
        throw std::logic_error("simulator is not connected");
    _command = command;
    _frame.state.twist = command.baseVelocity;
    ++_writeCount;
}

RobotFrame InMemorySimulator::step(std::chrono::nanoseconds duration)
{
    std::lock_guard<std::mutex> lock(_mutex);
    if (!_connected)
        throw std::logic_error("simulator is not connected");
    if (duration.count() < 0)
        throw std::invalid_argument("simulation step must not be negative");
    const auto seconds = std::chrono::duration<double>(duration).count();
    auto& state = _frame.state;
    state.pose.position.x += state.twist.linear.x * seconds;
    state.pose.position.y += state.twist.linear.y * seconds;
    state.pose.position.z += state.twist.linear.z * seconds;
    state.monotonicTimeNanoseconds += duration.count();
    _yaw += state.twist.angular.z * seconds;
    state.pose.orientation.z = std::sin(_yaw * 0.5);
    state.pose.orientation.w = std::cos(_yaw * 0.5);

    for (const auto& command : _command.joints)
    {
        auto found = std::find_if(state.joints.begin(), state.joints.end(),
                                  [&command](const JointState& joint)
                                  { return joint.name == command.name; });
        if (found == state.joints.end())
        {
            state.joints.push_back({command.name});
            found = std::prev(state.joints.end());
        }
        if (command.mode == JointCommandMode::position)
            found->position = command.value;
        else if (command.mode == JointCommandMode::velocity)
        {
            found->velocity = command.value;
            found->position += command.value * seconds;
        }
        else
            found->effort = command.value;
    }
    ++_readCount;
    return _frame;
}

bool InMemorySimulator::connected() const noexcept
{
    std::lock_guard<std::mutex> lock(_mutex);
    return _connected;
}

BackendHealth InMemorySimulator::health() const
{
    std::lock_guard<std::mutex> lock(_mutex);
    return {_connected,
            _backendActive,
            _connected && _backendActive,
            _readCount,
            _writeCount,
            _backendActive ? "ready" : (_connected ? "inactive" : "disconnected")};
}
} // namespace PocoDDS::Robotics
