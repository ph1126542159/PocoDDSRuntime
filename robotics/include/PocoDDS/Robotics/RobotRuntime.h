#pragma once

#include "PocoDDS/Robotics/Backend.h"
#include "PocoDDS/Robotics/Lifecycle.h"
#include "PocoDDS/Robotics/SafetyBoundary.h"

#include <chrono>
#include <functional>
#include <memory>
#include <mutex>
#include <optional>
#include <string>

namespace PocoDDS::Robotics
{
class RobotRuntime final : public LifecycleComponent
{
  public:
    using Clock = std::function<std::chrono::steady_clock::time_point()>;

    RobotRuntime(
        std::unique_ptr<RobotBackend> backend, SafetyLimits safetyLimits = {},
        Clock clock = [] { return std::chrono::steady_clock::now(); });

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
    std::chrono::steady_clock::duration _commandTimeout;
    SafetyBoundary _safety;
    Clock _clock;
    std::string _backendDescription{"empty"};
    mutable std::mutex _operationMutex;
    bool _acceptCommands{false};
    std::optional<std::chrono::steady_clock::time_point> _lastCommandTime;
};
} // namespace PocoDDS::Robotics
