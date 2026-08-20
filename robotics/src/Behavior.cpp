#include "PocoDDS/Robotics/Behavior.h"

#include <algorithm>
#include <stdexcept>
#include <utility>

namespace PocoDDS::Robotics
{
BehaviorTask::BehaviorTask(Callback callback, HaltCallback haltCallback)
    : _callback(std::move(callback)), _haltCallback(std::move(haltCallback))
{
    if (!_callback)
        throw std::invalid_argument("behavior callback is required");
}

BehaviorStatus BehaviorTask::tick(BehaviorBlackboard& blackboard) { return _callback(blackboard); }

void BehaviorTask::reset() {}

void BehaviorTask::halt()
{
    if (_haltCallback)
        _haltCallback();
    reset();
}

void BehaviorSequence::add(std::unique_ptr<Behavior> child)
{
    if (!child)
        throw std::invalid_argument("behavior child is required");
    _children.push_back(std::move(child));
}

BehaviorStatus BehaviorSequence::tick(BehaviorBlackboard& blackboard)
{
    while (_current < _children.size())
    {
        const auto status = _children[_current]->tick(blackboard);
        if (status == BehaviorStatus::running || status == BehaviorStatus::failed)
            return status;
        ++_current;
    }
    return BehaviorStatus::succeeded;
}

void BehaviorSequence::reset()
{
    for (auto& child : _children)
        child->reset();
    _current = 0;
}

void BehaviorSequence::halt()
{
    for (auto& child : _children)
        child->halt();
    _current = 0;
}

void BehaviorSelector::add(std::unique_ptr<Behavior> child)
{
    if (!child)
        throw std::invalid_argument("behavior child is required");
    _children.push_back(std::move(child));
}

BehaviorStatus BehaviorSelector::tick(BehaviorBlackboard& blackboard)
{
    while (_current < _children.size())
    {
        const auto status = _children[_current]->tick(blackboard);
        if (status == BehaviorStatus::running || status == BehaviorStatus::succeeded)
            return status;
        ++_current;
    }
    return BehaviorStatus::failed;
}

void BehaviorSelector::reset()
{
    for (auto& child : _children)
        child->reset();
    _current = 0;
}

void BehaviorSelector::halt()
{
    for (auto& child : _children)
        child->halt();
    _current = 0;
}

BehaviorRetry::BehaviorRetry(std::unique_ptr<Behavior> child, std::size_t maximumAttempts)
    : _child(std::move(child)), _maximumAttempts(maximumAttempts)
{
    if (!_child || _maximumAttempts == 0)
        throw std::invalid_argument("retry requires a child and at least one attempt");
}

BehaviorStatus BehaviorRetry::tick(BehaviorBlackboard& blackboard)
{
    const auto status = _child->tick(blackboard);
    if (status != BehaviorStatus::failed)
        return status;
    ++_attempt;
    if (_attempt >= _maximumAttempts)
        return BehaviorStatus::failed;
    _child->reset();
    return BehaviorStatus::running;
}

void BehaviorRetry::reset()
{
    _attempt = 0;
    _child->reset();
}

void BehaviorRetry::halt()
{
    _attempt = 0;
    _child->halt();
}

BehaviorTimeout::BehaviorTimeout(std::unique_ptr<Behavior> child,
                                 std::chrono::steady_clock::duration timeout, Clock clock)
    : _child(std::move(child)), _timeout(timeout), _clock(std::move(clock))
{
    if (!_child || _timeout <= std::chrono::steady_clock::duration::zero() || !_clock)
        throw std::invalid_argument("timeout requires a child, duration and clock");
}

BehaviorStatus BehaviorTimeout::tick(BehaviorBlackboard& blackboard)
{
    if (_timedOut)
        return BehaviorStatus::failed;
    const auto now = _clock();
    if (!_started)
        _started = now;
    if (now - *_started >= _timeout)
    {
        _child->halt();
        _timedOut = true;
        return BehaviorStatus::failed;
    }
    return _child->tick(blackboard);
}

void BehaviorTimeout::reset()
{
    _started.reset();
    _timedOut = false;
    _child->reset();
}

void BehaviorTimeout::halt()
{
    _started.reset();
    _timedOut = false;
    _child->halt();
}

BehaviorParallel::BehaviorParallel(std::size_t successThreshold)
    : _successThreshold(successThreshold)
{
}

void BehaviorParallel::add(std::unique_ptr<Behavior> child)
{
    if (!child)
        throw std::invalid_argument("behavior child is required");
    _children.push_back(std::move(child));
    _states.push_back(BehaviorStatus::running);
}

BehaviorStatus BehaviorParallel::tick(BehaviorBlackboard& blackboard)
{
    if (_children.empty())
        return BehaviorStatus::succeeded;
    const auto required = _successThreshold == 0 ? _children.size() : _successThreshold;
    if (required > _children.size())
        return BehaviorStatus::failed;

    std::size_t successes = 0;
    std::size_t failures = 0;
    for (std::size_t index = 0; index < _children.size(); ++index)
    {
        if (_states[index] == BehaviorStatus::running)
            _states[index] = _children[index]->tick(blackboard);
        successes += _states[index] == BehaviorStatus::succeeded ? 1U : 0U;
        failures += _states[index] == BehaviorStatus::failed ? 1U : 0U;
    }
    if (successes >= required)
    {
        for (std::size_t index = 0; index < _children.size(); ++index)
        {
            if (_states[index] == BehaviorStatus::running)
            {
                _children[index]->halt();
                _states[index] = BehaviorStatus::failed;
            }
        }
        return BehaviorStatus::succeeded;
    }
    if (_children.size() - failures < required)
    {
        for (std::size_t index = 0; index < _children.size(); ++index)
        {
            if (_states[index] == BehaviorStatus::running)
            {
                _children[index]->halt();
                _states[index] = BehaviorStatus::failed;
            }
        }
        return BehaviorStatus::failed;
    }
    return BehaviorStatus::running;
}

void BehaviorParallel::reset()
{
    for (auto& child : _children)
        child->reset();
    std::fill(_states.begin(), _states.end(), BehaviorStatus::running);
}

void BehaviorParallel::halt()
{
    for (auto& child : _children)
        child->halt();
    std::fill(_states.begin(), _states.end(), BehaviorStatus::running);
}

bool BehaviorOrchestrator::registerBehavior(std::string name, Factory factory)
{
    if (name.empty() || !factory)
        return false;
    std::lock_guard<std::mutex> lock(_mutex);
    return _factories.emplace(std::move(name), std::move(factory)).second;
}

bool BehaviorOrchestrator::hasBehavior(const std::string& name) const
{
    std::lock_guard<std::mutex> lock(_mutex);
    return _factories.count(name) != 0;
}

bool BehaviorOrchestrator::start(std::string executionId, const std::string& behavior,
                                 BehaviorBlackboard blackboard)
{
    if (executionId.empty() || behavior.empty())
        return false;
    Factory factory;
    {
        std::lock_guard<std::mutex> lock(_mutex);
        const auto found = _factories.find(behavior);
        if (found == _factories.end() || _executions.count(executionId) != 0)
            return false;
        factory = found->second;
    }
    auto root = factory();
    if (!root)
        return false;
    auto execution = std::make_shared<Execution>();
    execution->snapshot.id = executionId;
    execution->snapshot.behavior = behavior;
    execution->snapshot.detail = "accepted";
    execution->root = std::move(root);
    execution->blackboard = std::move(blackboard);
    std::lock_guard<std::mutex> lock(_mutex);
    return _executions.emplace(std::move(executionId), std::move(execution)).second;
}

std::optional<BehaviorExecutionSnapshot> BehaviorOrchestrator::tick(const std::string& executionId)
{
    std::shared_ptr<Execution> execution;
    {
        std::lock_guard<std::mutex> lock(_mutex);
        const auto found = _executions.find(executionId);
        if (found == _executions.end())
            return std::nullopt;
        execution = found->second;
    }
    std::lock_guard<std::mutex> lock(execution->mutex);
    if (execution->snapshot.status == BehaviorExecutionStatus::canceled ||
        execution->snapshot.status == BehaviorExecutionStatus::succeeded ||
        execution->snapshot.status == BehaviorExecutionStatus::failed)
        return execution->snapshot;
    ++execution->snapshot.tickCount;
    const auto status = execution->root->tick(execution->blackboard);
    if (status == BehaviorStatus::running)
    {
        execution->snapshot.status = BehaviorExecutionStatus::running;
        execution->snapshot.detail = "running";
    }
    else if (status == BehaviorStatus::succeeded)
    {
        execution->snapshot.status = BehaviorExecutionStatus::succeeded;
        execution->snapshot.detail = "succeeded";
    }
    else
    {
        execution->snapshot.status = BehaviorExecutionStatus::failed;
        execution->snapshot.detail = "failed";
    }
    return execution->snapshot;
}

bool BehaviorOrchestrator::cancel(const std::string& executionId)
{
    std::shared_ptr<Execution> execution;
    {
        std::lock_guard<std::mutex> lock(_mutex);
        const auto found = _executions.find(executionId);
        if (found == _executions.end())
            return false;
        execution = found->second;
    }
    std::lock_guard<std::mutex> lock(execution->mutex);
    if (execution->snapshot.status == BehaviorExecutionStatus::succeeded ||
        execution->snapshot.status == BehaviorExecutionStatus::failed ||
        execution->snapshot.status == BehaviorExecutionStatus::canceled)
        return false;
    execution->root->halt();
    execution->snapshot.status = BehaviorExecutionStatus::canceled;
    execution->snapshot.detail = "canceled";
    return true;
}

std::optional<BehaviorExecutionSnapshot>
BehaviorOrchestrator::snapshot(const std::string& executionId) const
{
    std::shared_ptr<Execution> execution;
    {
        std::lock_guard<std::mutex> lock(_mutex);
        const auto found = _executions.find(executionId);
        if (found == _executions.end())
            return std::nullopt;
        execution = found->second;
    }
    std::lock_guard<std::mutex> lock(execution->mutex);
    return execution->snapshot;
}
} // namespace PocoDDS::Robotics
