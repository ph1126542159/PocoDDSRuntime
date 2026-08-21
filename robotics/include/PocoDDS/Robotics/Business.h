#pragma once

#include "PocoDDS/Robotics/Behavior.h"
#include "PocoDDS/Robotics/RobotRuntime.h"

#include <atomic>
#include <chrono>
#include <cstdint>
#include <functional>
#include <memory>
#include <mutex>
#include <optional>
#include <string>
#include <unordered_map>
#include <vector>

namespace PocoDDS::Robotics
{
enum class BusinessStepStatus
{
    succeeded,
    failed,
    canceled,
    running
};

const char* businessStepStatusName(BusinessStepStatus status) noexcept;

struct BusinessStepRecord
{
    std::string module;
    std::string mission;
    std::string step;
    BusinessStepStatus status{BusinessStepStatus::failed};
    std::string input;
    std::string output;
    std::string detail;
    std::uint64_t startTick{0};
    std::uint64_t finishTick{0};
    std::int64_t startTimeNanoseconds{0};
    std::int64_t durationNanoseconds{0};
};

class BusinessContext
{
  public:
    using Clock = std::function<std::chrono::steady_clock::time_point()>;
    using StepObserver = std::function<void(const BusinessStepRecord&)>;

    BusinessContext(
        RobotRuntime& runtime, std::chrono::nanoseconds controlPeriod,
        Clock clock = [] { return std::chrono::steady_clock::now(); });

    SafetyDecision command(RobotCommand command);
    SafetyDecision commandVelocity(const Twist& velocity);
    RobotFrame advance();
    RobotFrame frame() const;
    std::chrono::nanoseconds controlPeriod() const noexcept;
    std::chrono::steady_clock::time_point now() const;
    std::uint64_t tick() const noexcept;

    void setSignal(std::string name, std::string value);
    std::optional<std::string> signal(const std::string& name) const;
    std::string signalOr(const std::string& name, const std::string& fallback) const;

    void setStepObserver(StepObserver observer);
    void notifyStepStarted(const BusinessStepRecord& record);
    void recordStep(BusinessStepRecord record);
    std::vector<BusinessStepRecord> records() const;

  private:
    RobotRuntime& _runtime;
    const std::chrono::nanoseconds _controlPeriod;
    Clock _clock;
    std::atomic<std::uint64_t> _sequence{0};
    std::atomic<std::uint64_t> _tick{0};
    mutable std::mutex _mutex;
    RobotFrame _frame;
    std::unordered_map<std::string, std::string> _signals;
    std::vector<BusinessStepRecord> _records;
    StepObserver _stepObserver;
};

class RobotBusinessModule
{
  public:
    virtual ~RobotBusinessModule() = default;
    virtual std::string name() const = 0;
    virtual std::vector<std::string> missions() const = 0;
    virtual std::unique_ptr<Behavior> createMission(const std::string& mission,
                                                    BusinessContext& context) const = 0;
};

class BusinessModuleRegistry
{
  public:
    bool registerModule(std::shared_ptr<RobotBusinessModule> module);
    bool install(const std::string& module, BehaviorOrchestrator& orchestrator,
                 BusinessContext& context) const;
    bool contains(const std::string& module) const;
    std::vector<std::string> moduleNames() const;
    std::vector<std::string> missionNames(const std::string& module) const;
    static std::string qualifiedBehaviorName(const std::string& module, const std::string& mission);

  private:
    mutable std::mutex _mutex;
    std::unordered_map<std::string, std::shared_ptr<RobotBusinessModule>> _modules;
};

using BusinessOutputProvider = std::function<std::string()>;

std::unique_ptr<Behavior> makeTracedBusinessStep(BusinessContext& context, std::string module,
                                                 std::string mission, std::string step,
                                                 std::string input, std::unique_ptr<Behavior> child,
                                                 BusinessOutputProvider outputProvider = {});
} // namespace PocoDDS::Robotics
