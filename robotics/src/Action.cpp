#include "PocoDDS/Robotics/Action.h"

#include <algorithm>
#include <cmath>
#include <exception>
#include <utility>

namespace PocoDDS::Robotics
{
bool ActionCoordinator::submit(ActionGoal goal, Executor executor)
{
    if (goal.id.empty() || goal.behavior.empty() || !executor)
        return false;
    std::lock_guard<std::mutex> lock(_mutex);
    Entry entry;
    entry.goal = std::move(goal);
    entry.executor = std::move(executor);
    entry.feedback.detail = "accepted";
    return _entries.emplace(entry.goal.id, std::move(entry)).second;
}

bool ActionCoordinator::cancel(const std::string& goalId)
{
    std::lock_guard<std::mutex> lock(_mutex);
    const auto found = _entries.find(goalId);
    if (found == _entries.end())
        return false;
    const auto status = found->second.feedback.status;
    if (status == ActionStatus::succeeded || status == ActionStatus::failed ||
        status == ActionStatus::canceled)
        return false;
    found->second.cancelRequested = true;
    return true;
}

std::optional<ActionFeedback> ActionCoordinator::tick(const std::string& goalId)
{
    ActionGoal goal;
    Executor executor;
    bool cancelRequested = false;
    {
        std::lock_guard<std::mutex> lock(_mutex);
        const auto found = _entries.find(goalId);
        if (found == _entries.end())
            return std::nullopt;
        const auto status = found->second.feedback.status;
        if (status == ActionStatus::succeeded || status == ActionStatus::failed ||
            status == ActionStatus::canceled)
            return found->second.feedback;
        if (found->second.executing)
            return found->second.feedback;
        found->second.executing = true;
        goal = found->second.goal;
        executor = found->second.executor;
        cancelRequested = found->second.cancelRequested;
    }

    ActionFeedback next;
    try
    {
        next = executor(goal, cancelRequested);
        if (!std::isfinite(next.progress))
            next = {ActionStatus::failed, 0.0, "executor returned non-finite progress"};
        else
        {
            next.progress = std::clamp(next.progress, 0.0, 1.0);
            if (next.status == ActionStatus::accepted)
                next.status = ActionStatus::running;
            if (next.status == ActionStatus::succeeded)
                next.progress = 1.0;
        }
    }
    catch (const std::exception& exception)
    {
        next = {ActionStatus::failed, 0.0, exception.what()};
    }
    catch (...)
    {
        next = {ActionStatus::failed, 0.0, "unknown action executor failure"};
    }

    std::lock_guard<std::mutex> lock(_mutex);
    const auto found = _entries.find(goalId);
    if (found == _entries.end())
        return std::nullopt;
    found->second.executing = false;
    if (found->second.cancelRequested && next.status != ActionStatus::succeeded &&
        next.status != ActionStatus::failed)
    {
        next.status = ActionStatus::canceled;
        next.detail = "canceled";
    }
    found->second.feedback = next;
    return found->second.feedback;
}

std::optional<ActionFeedback> ActionCoordinator::feedback(const std::string& goalId) const
{
    std::lock_guard<std::mutex> lock(_mutex);
    const auto found = _entries.find(goalId);
    if (found == _entries.end())
        return std::nullopt;
    return found->second.feedback;
}
} // namespace PocoDDS::Robotics
