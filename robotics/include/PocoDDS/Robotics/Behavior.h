#pragma once

#include <cstddef>
#include <functional>
#include <memory>
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
};

class BehaviorTask final : public Behavior
{
public:
    using Callback = std::function<BehaviorStatus(BehaviorBlackboard&)>;
    explicit BehaviorTask(Callback callback);
    BehaviorStatus tick(BehaviorBlackboard& blackboard) override;
    void reset() override;

private:
    Callback _callback;
};

class BehaviorSequence final : public Behavior
{
public:
    void add(std::unique_ptr<Behavior> child);
    BehaviorStatus tick(BehaviorBlackboard& blackboard) override;
    void reset() override;

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

private:
    std::vector<std::unique_ptr<Behavior>> _children;
    std::size_t _current{0};
};
} // namespace PocoDDS::Robotics
