#pragma once

#include "PocoDDS/Robotics/Backend.h"
#include "PocoDDS/Robotics/Lifecycle.h"
#include "PocoDDS/Robotics/SafetyBoundary.h"

#include <chrono>
#include <memory>
#include <mutex>
#include <string>

namespace PocoDDS::Robotics
{
class RobotRuntime final : public LifecycleComponent
{
  public:
    RobotRuntime(std::unique_ptr<RobotBackend> backend, SafetyLimits safetyLimits = {});

    void setWorld(std::string world);
    void setBackendDescription(std::string description);
    void setEmergencyStop(bool engaged, std::string reason = {});
    bool emergencyStop() const noexcept;
    SafetyDecision
    command(const RobotCommand& command,
            std::chrono::steady_clock::time_point timestamp = std::chrono::steady_clock::now());
    SafetyDecision commandVelocity(
        const Twist& command,
        std::chrono::steady_clock::time_point timestamp = std::chrono::steady_clock::now());
    RobotFrame step(std::chrono::nanoseconds duration);
    BackendHealth backendHealth() const;

  protected:
    bool onConfigure() override;
    bool onActivate() override;
    bool onDeactivate() override;
    bool onCleanup() override;
    void onShutdown() noexcept override;

  private:
    std::unique_ptr<RobotBackend> _backend;
    SafetyBoundary _safety;
    std::string _backendDescription{"empty"};
    mutable std::mutex _operationMutex;
    bool _acceptCommands{false};
};
} // namespace PocoDDS::Robotics
