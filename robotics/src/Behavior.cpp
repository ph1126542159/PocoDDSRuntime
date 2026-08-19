#include "PocoDDS/Robotics/Behavior.h"

#include <stdexcept>
#include <utility>

namespace PocoDDS::Robotics
{
BehaviorTask::BehaviorTask(Callback callback) : _callback(std::move(callback))
{
    if (!_callback)
        throw std::invalid_argument("behavior callback is required");
}

BehaviorStatus BehaviorTask::tick(BehaviorBlackboard& blackboard)
{
    return _callback(blackboard);
}

void BehaviorTask::reset() {}

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
} // namespace PocoDDS::Robotics
