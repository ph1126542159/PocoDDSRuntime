#pragma once

#include "PocoDDS/Robotics/HardwareInterface.h"

#include <mutex>
#include <string>
#include <vector>

namespace PocoDDS::Robotics
{
enum class MockHardwareFault
{
    none,
    readFailure,
    writeFailure,
    staleFeedback
};

class MockHardware final : public HardwareInterface
{
  public:
    explicit MockHardware(std::vector<std::string> jointNames = {});

    std::string name() const override;
    bool configure(const std::string& hardwareDescription) override;
    bool activate() override;
    void deactivate() noexcept override;
    void reset() override;
    RobotFrame read(std::chrono::nanoseconds period) override;
    bool write(const RobotCommand& command, std::chrono::nanoseconds period) override;
    BackendHealth health() const override;

    void injectFault(MockHardwareFault fault);
    MockHardwareFault fault() const noexcept;

  private:
    std::vector<std::string> _jointNames;
    mutable std::mutex _mutex;
    RobotFrame _frame;
    RobotCommand _command;
    BackendHealth _health;
    MockHardwareFault _fault{MockHardwareFault::none};
};
} // namespace PocoDDS::Robotics
