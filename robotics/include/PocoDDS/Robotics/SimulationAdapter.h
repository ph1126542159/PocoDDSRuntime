#pragma once

#include "PocoDDS/Robotics/Types.h"

#include <chrono>
#include <mutex>
#include <string>

namespace PocoDDS::Robotics
{
class SimulationAdapter
{
public:
    virtual ~SimulationAdapter() = default;
    virtual std::string backendName() const = 0;
    virtual bool connect(const std::string& world) = 0;
    virtual void reset() = 0;
    virtual void applyCommand(const RobotCommand& command) = 0;
    virtual RobotFrame step(std::chrono::nanoseconds duration) = 0;
    virtual bool connected() const noexcept = 0;
};

class InMemorySimulator final : public SimulationAdapter
{
public:
    std::string backendName() const override;
    bool connect(const std::string& world) override;
    void reset() override;
    void applyCommand(const RobotCommand& command) override;
    RobotFrame step(std::chrono::nanoseconds duration) override;
    bool connected() const noexcept override;

private:
    bool _connected{false};
    std::string _world;
    RobotFrame _frame;
    RobotCommand _command;
    double _yaw{0.0};
    mutable std::mutex _mutex;
};
} // namespace PocoDDS::Robotics
