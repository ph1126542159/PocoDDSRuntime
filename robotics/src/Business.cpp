#include "PocoDDS/Robotics/Business.h"

#include <algorithm>
#include <set>
#include <stdexcept>
#include <utility>

namespace PocoDDS::Robotics
{
namespace
{
std::int64_t timestampNanoseconds(std::chrono::steady_clock::time_point value)
{
    return std::chrono::duration_cast<std::chrono::nanoseconds>(value.time_since_epoch()).count();
}

void invokeStepObserver(const BusinessContext::StepObserver& observer,
                        const BusinessStepRecord& record) noexcept
{
    if (!observer)
        return;
    try
    {
        observer(record);
    }
    catch (...)
    {
        // Telemetry consumers must never change robot behavior or terminal state.
        static_cast<void>(record);
    }
}

class TracedBusinessStep final : public Behavior
{
  public:
    TracedBusinessStep(BusinessContext& context, std::string module, std::string mission,
                       std::string step, std::string input, std::unique_ptr<Behavior> child,
                       BusinessOutputProvider outputProvider)
        : _context(context), _module(std::move(module)), _mission(std::move(mission)),
          _step(std::move(step)), _input(std::move(input)), _child(std::move(child)),
          _outputProvider(std::move(outputProvider))
    {
        if (_module.empty() || _mission.empty() || _step.empty() || !_child)
            throw std::invalid_argument("traced business step requires names and child");
    }

    BehaviorStatus tick(BehaviorBlackboard& blackboard) override
    {
        if (!_started)
        {
            _started = true;
            _startTick = _context.tick();
            _startTime = _context.now();
            _context.notifyStepStarted({_module,
                                        _mission,
                                        _step,
                                        BusinessStepStatus::running,
                                        _input,
                                        {},
                                        "started",
                                        _startTick,
                                        _startTick,
                                        timestampNanoseconds(_startTime),
                                        0});
        }
        const auto status = _child->tick(blackboard);
        if (status != BehaviorStatus::running && !_recorded)
        {
            record(status == BehaviorStatus::succeeded ? BusinessStepStatus::succeeded
                                                       : BusinessStepStatus::failed,
                   status == BehaviorStatus::succeeded ? "completed" : "behavior failed");
        }
        return status;
    }

    void reset() override
    {
        _child->reset();
        _started = false;
        _recorded = false;
        _startTick = 0;
        _startTime = {};
    }

    void halt() override
    {
        _child->halt();
        if (_started && !_recorded)
            record(BusinessStepStatus::canceled, "canceled");
    }

  private:
    void record(BusinessStepStatus status, std::string detail)
    {
        std::string output;
        if (_outputProvider)
        {
            try
            {
                output = _outputProvider();
            }
            catch (const std::exception& exception)
            {
                detail += "; output provider failed: ";
                detail += exception.what();
            }
            catch (...)
            {
                detail += "; output provider failed";
            }
        }
        const auto finishTime = _context.now();
        _context.recordStep(
            {_module, _mission, _step, status, _input, std::move(output), std::move(detail),
             _startTick, _context.tick(), timestampNanoseconds(_startTime),
             std::chrono::duration_cast<std::chrono::nanoseconds>(finishTime - _startTime)
                 .count()});
        _recorded = true;
    }

    BusinessContext& _context;
    const std::string _module;
    const std::string _mission;
    const std::string _step;
    const std::string _input;
    std::unique_ptr<Behavior> _child;
    BusinessOutputProvider _outputProvider;
    bool _started{false};
    bool _recorded{false};
    std::uint64_t _startTick{0};
    std::chrono::steady_clock::time_point _startTime;
};
} // namespace

const char* businessStepStatusName(BusinessStepStatus status) noexcept
{
    switch (status)
    {
    case BusinessStepStatus::running:
        return "running";
    case BusinessStepStatus::succeeded:
        return "succeeded";
    case BusinessStepStatus::failed:
        return "failed";
    case BusinessStepStatus::canceled:
        return "canceled";
    }
    return "unknown";
}

BusinessContext::BusinessContext(RobotRuntime& runtime, std::chrono::nanoseconds controlPeriod,
                                 Clock clock)
    : _runtime(runtime), _controlPeriod(controlPeriod), _clock(std::move(clock))
{
    if (_controlPeriod <= std::chrono::nanoseconds::zero() || !_clock)
        throw std::invalid_argument("business context requires positive period and clock");
}

SafetyDecision BusinessContext::command(RobotCommand command)
{
    if (command.sequence == 0)
        command.sequence = ++_sequence;
    return _runtime.command(command, now());
}

SafetyDecision BusinessContext::commandVelocity(const Twist& velocity)
{
    RobotCommand command;
    command.baseVelocity = velocity;
    return this->command(std::move(command));
}

RobotFrame BusinessContext::advance()
{
    auto next = _runtime.step(_controlPeriod);
    {
        std::lock_guard<std::mutex> lock(_mutex);
        _frame = next;
    }
    ++_tick;
    return next;
}

RobotFrame BusinessContext::frame() const
{
    std::lock_guard<std::mutex> lock(_mutex);
    return _frame;
}

std::chrono::nanoseconds BusinessContext::controlPeriod() const noexcept { return _controlPeriod; }

std::chrono::steady_clock::time_point BusinessContext::now() const { return _clock(); }

std::uint64_t BusinessContext::tick() const noexcept { return _tick.load(); }

void BusinessContext::setSignal(std::string name, std::string value)
{
    if (name.empty())
        throw std::invalid_argument("business signal name is required");
    std::lock_guard<std::mutex> lock(_mutex);
    _signals[std::move(name)] = std::move(value);
}

std::optional<std::string> BusinessContext::signal(const std::string& name) const
{
    std::lock_guard<std::mutex> lock(_mutex);
    const auto found = _signals.find(name);
    if (found == _signals.end())
        return std::nullopt;
    return found->second;
}

std::string BusinessContext::signalOr(const std::string& name, const std::string& fallback) const
{
    const auto value = signal(name);
    return value ? *value : fallback;
}

void BusinessContext::recordStep(BusinessStepRecord record)
{
    StepObserver observer;
    BusinessStepRecord event;
    {
        std::lock_guard<std::mutex> lock(_mutex);
        _records.push_back(std::move(record));
        event = _records.back();
        observer = _stepObserver;
    }
    invokeStepObserver(observer, event);
}

void BusinessContext::setStepObserver(StepObserver observer)
{
    std::lock_guard<std::mutex> lock(_mutex);
    _stepObserver = std::move(observer);
}

void BusinessContext::notifyStepStarted(const BusinessStepRecord& record)
{
    StepObserver observer;
    {
        std::lock_guard<std::mutex> lock(_mutex);
        observer = _stepObserver;
    }
    invokeStepObserver(observer, record);
}

std::vector<BusinessStepRecord> BusinessContext::records() const
{
    std::lock_guard<std::mutex> lock(_mutex);
    return _records;
}

bool BusinessModuleRegistry::registerModule(std::shared_ptr<RobotBusinessModule> module)
{
    if (!module)
        return false;
    const auto name = module->name();
    const auto missions = module->missions();
    if (name.empty() || missions.empty() || name.find('/') != std::string::npos)
        return false;
    std::set<std::string> uniqueMissions;
    if (!std::all_of(missions.begin(), missions.end(),
                     [&uniqueMissions](const std::string& mission)
                     {
                         return !mission.empty() && mission.find('/') == std::string::npos &&
                                uniqueMissions.emplace(mission).second;
                     }))
        return false;
    std::lock_guard<std::mutex> lock(_mutex);
    return _modules.emplace(name, std::move(module)).second;
}

bool BusinessModuleRegistry::install(const std::string& moduleName,
                                     BehaviorOrchestrator& orchestrator,
                                     BusinessContext& context) const
{
    std::shared_ptr<RobotBusinessModule> module;
    {
        std::lock_guard<std::mutex> lock(_mutex);
        const auto found = _modules.find(moduleName);
        if (found == _modules.end())
            return false;
        module = found->second;
    }
    const auto missions = module->missions();
    for (const auto& mission : missions)
    {
        if (orchestrator.hasBehavior(qualifiedBehaviorName(moduleName, mission)))
            return false;
    }
    std::vector<std::string> installed;
    installed.reserve(missions.size());
    for (const auto& mission : missions)
    {
        const auto behavior = qualifiedBehaviorName(moduleName, mission);
        if (!orchestrator.registerBehavior(behavior, [module, mission, &context]
                                           { return module->createMission(mission, context); }))
        {
            for (const auto& installedBehavior : installed)
                orchestrator.unregisterBehavior(installedBehavior);
            return false;
        }
        installed.push_back(behavior);
    }
    return true;
}

bool BusinessModuleRegistry::contains(const std::string& module) const
{
    std::lock_guard<std::mutex> lock(_mutex);
    return _modules.count(module) != 0;
}

std::vector<std::string> BusinessModuleRegistry::moduleNames() const
{
    std::lock_guard<std::mutex> lock(_mutex);
    std::vector<std::string> result;
    result.reserve(_modules.size());
    for (const auto& [name, module] : _modules)
    {
        static_cast<void>(module);
        result.push_back(name);
    }
    std::sort(result.begin(), result.end());
    return result;
}

std::vector<std::string> BusinessModuleRegistry::missionNames(const std::string& module) const
{
    std::lock_guard<std::mutex> lock(_mutex);
    const auto found = _modules.find(module);
    return found == _modules.end() ? std::vector<std::string>{} : found->second->missions();
}

std::string BusinessModuleRegistry::qualifiedBehaviorName(const std::string& module,
                                                          const std::string& mission)
{
    return module + "/" + mission;
}

std::unique_ptr<Behavior> makeTracedBusinessStep(BusinessContext& context, std::string module,
                                                 std::string mission, std::string step,
                                                 std::string input, std::unique_ptr<Behavior> child,
                                                 BusinessOutputProvider outputProvider)
{
    return std::make_unique<TracedBusinessStep>(context, std::move(module), std::move(mission),
                                                std::move(step), std::move(input), std::move(child),
                                                std::move(outputProvider));
}
} // namespace PocoDDS::Robotics
