#pragma once

#include <chrono>
#include <cstddef>
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
enum class BehaviorStatus
{
    running,
    succeeded,
    failed
};

using BehaviorBlackboard = std::unordered_map<std::string, std::string>;

class Behavior
{
  public:
    virtual ~Behavior() = default;
    virtual BehaviorStatus tick(BehaviorBlackboard& blackboard) = 0;
    virtual void reset() = 0;
    virtual void halt() { reset(); }
};

class BehaviorTask final : public Behavior
{
  public:
    using Callback = std::function<BehaviorStatus(BehaviorBlackboard&)>;
    using HaltCallback = std::function<void()>;
    explicit BehaviorTask(Callback callback, HaltCallback haltCallback = {});
    BehaviorStatus tick(BehaviorBlackboard& blackboard) override;
    void reset() override;
    void halt() override;

  private:
    Callback _callback;
    HaltCallback _haltCallback;
};

class BehaviorSequence final : public Behavior
{
  public:
    void add(std::unique_ptr<Behavior> child);
    BehaviorStatus tick(BehaviorBlackboard& blackboard) override;
    void reset() override;
    void halt() override;

  private:
    std::vector<std::unique_ptr<Behavior>> _children;
    std::size_t _current{0};
};

class BehaviorSelector final : public Behavior
{
  public:
    void add(std::unique_ptr<Behavior> child);
    BehaviorStatus tick(BehaviorBlackboard& blackboard) override;
    void reset() override;
    void halt() override;

  private:
    std::vector<std::unique_ptr<Behavior>> _children;
    std::size_t _current{0};
};

class BehaviorRetry final : public Behavior
{
  public:
    BehaviorRetry(std::unique_ptr<Behavior> child, std::size_t maximumAttempts);
    BehaviorStatus tick(BehaviorBlackboard& blackboard) override;
    void reset() override;
    void halt() override;

  private:
    std::unique_ptr<Behavior> _child;
    std::size_t _maximumAttempts;
    std::size_t _attempt{0};
};

class BehaviorTimeout final : public Behavior
{
  public:
    using Clock = std::function<std::chrono::steady_clock::time_point()>;
    BehaviorTimeout(
        std::unique_ptr<Behavior> child, std::chrono::steady_clock::duration timeout,
        Clock clock = [] { return std::chrono::steady_clock::now(); });
    BehaviorStatus tick(BehaviorBlackboard& blackboard) override;
    void reset() override;
    void halt() override;

  private:
    std::unique_ptr<Behavior> _child;
    std::chrono::steady_clock::duration _timeout;
    Clock _clock;
    std::optional<std::chrono::steady_clock::time_point> _started;
    bool _timedOut{false};
};

class BehaviorParallel final : public Behavior
{
  public:
    explicit BehaviorParallel(std::size_t successThreshold = 0);
    void add(std::unique_ptr<Behavior> child);
    BehaviorStatus tick(BehaviorBlackboard& blackboard) override;
    void reset() override;
    void halt() override;

  private:
    std::vector<std::unique_ptr<Behavior>> _children;
    std::vector<BehaviorStatus> _states;
    std::size_t _successThreshold;
};

enum class BehaviorExecutionStatus
{
    accepted,
    running,
    succeeded,
    failed,
    canceled
};

struct BehaviorExecutionSnapshot
{
    std::string id;
    std::string behavior;
    BehaviorExecutionStatus status{BehaviorExecutionStatus::accepted};
    std::uint64_t tickCount{0};
    std::string detail;
};

class BehaviorOrchestrator
{
  public:
    using Factory = std::function<std::unique_ptr<Behavior>()>;

    bool registerBehavior(std::string name, Factory factory);
    bool hasBehavior(const std::string& name) const;
    bool start(std::string executionId, const std::string& behavior,
               BehaviorBlackboard blackboard = {});
    std::optional<BehaviorExecutionSnapshot> tick(const std::string& executionId);
    bool cancel(const std::string& executionId);
    std::optional<BehaviorExecutionSnapshot> snapshot(const std::string& executionId) const;

  private:
    struct Execution
    {
        mutable std::mutex mutex;
        BehaviorExecutionSnapshot snapshot;
        std::unique_ptr<Behavior> root;
        BehaviorBlackboard blackboard;
    };

    mutable std::mutex _mutex;
    std::unordered_map<std::string, Factory> _factories;
    std::unordered_map<std::string, std::shared_ptr<Execution>> _executions;
};
} // namespace PocoDDS::Robotics
