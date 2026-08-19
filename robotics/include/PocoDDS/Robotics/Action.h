#pragma once

#include <functional>
#include <mutex>
#include <optional>
#include <string>
#include <unordered_map>

namespace PocoDDS::Robotics
{
enum class ActionStatus
{
    accepted,
    running,
    succeeded,
    canceled,
    failed
};

struct ActionGoal
{
    std::string id;
    std::string behavior;
    std::string parameters;
};

struct ActionFeedback
{
    ActionStatus status{ActionStatus::accepted};
    double progress{0.0};
    std::string detail;
};

class ActionCoordinator
{
public:
    using Executor = std::function<ActionFeedback(const ActionGoal&, bool cancelRequested)>;

    bool submit(ActionGoal goal, Executor executor);
    bool cancel(const std::string& goalId);
    std::optional<ActionFeedback> tick(const std::string& goalId);
    std::optional<ActionFeedback> feedback(const std::string& goalId) const;

private:
    struct Entry
    {
        ActionGoal goal;
        Executor executor;
        ActionFeedback feedback;
        bool cancelRequested{false};
    };

    mutable std::mutex _mutex;
    std::unordered_map<std::string, Entry> _entries;
};
} // namespace PocoDDS::Robotics
