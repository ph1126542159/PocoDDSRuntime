#pragma once

#include "PocoDDS/Robotics/HardwareInterface.h"
#include "PocoDDS/Robotics/SimulationAdapter.h"

namespace PocoDDS::Robotics
{
class ExternalHardware final : public HardwareInterface
{
  public:
    using CommandSink = ExternalSimulator::CommandSink;
    using Clock = ExternalSimulator::Clock;

    ExternalHardware(
        std::string backend, CommandSink commandSink,
        std::chrono::steady_clock::duration feedbackTimeout,
        Clock clock = [] { return std::chrono::steady_clock::now(); });

    std::string name() const override;
    bool configure(const std::string& hardwareDescription) override;
    bool activate() override;
    void deactivate() noexcept override;
    void reset() override;
    RobotFrame read(std::chrono::nanoseconds period) override;
    bool write(const RobotCommand& command, std::chrono::nanoseconds period) override;
    BackendHealth health() const override;
    void updateFrame(RobotFrame frame);

  private:
    ExternalSimulator _transport;
};
} // namespace PocoDDS::Robotics
