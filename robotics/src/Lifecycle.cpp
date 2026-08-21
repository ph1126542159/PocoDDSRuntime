#include "PocoDDS/Robotics/Lifecycle.h"

#include <exception>
#include <utility>

namespace PocoDDS::Robotics
{
LifecycleState LifecycleComponent::state() const noexcept
{
    std::lock_guard<std::mutex> lock(_mutex);
    return _state;
}

std::string LifecycleComponent::lastError() const
{
    std::lock_guard<std::mutex> lock(_mutex);
    return _lastError;
}

template <typename Callback>
bool LifecycleComponent::transition(LifecycleState required, LifecycleState next,
                                    Callback&& callback)
{
    {
        std::lock_guard<std::mutex> lock(_mutex);
        if (_state != required || _transitioning)
            return false;
        _transitioning = true;
    }

    bool accepted = false;
    std::string error;
    try
    {
        accepted = std::forward<Callback>(callback)();
        if (!accepted)
            error = "lifecycle callback rejected transition";
    }
    catch (const std::exception& exception)
    {
        error = exception.what();
    }
    catch (...)
    {
        error = "unknown lifecycle failure";
    }

    std::lock_guard<std::mutex> lock(_mutex);
    _transitioning = false;
    _state = accepted ? next : LifecycleState::error;
    _lastError = std::move(error);
    _stateChanged.notify_all();
    return accepted;
}

bool LifecycleComponent::configure()
{
    return transition(LifecycleState::unconfigured, LifecycleState::inactive,
                      [this] { return onConfigure(); });
}

bool LifecycleComponent::activate()
{
    return transition(LifecycleState::inactive, LifecycleState::active,
                      [this] { return onActivate(); });
}

bool LifecycleComponent::deactivate()
{
    return transition(LifecycleState::active, LifecycleState::inactive,
                      [this] { return onDeactivate(); });
}

bool LifecycleComponent::cleanup()
{
    return transition(LifecycleState::inactive, LifecycleState::unconfigured,
                      [this] { return onCleanup(); });
}

void LifecycleComponent::shutdown() noexcept
{
    {
        std::unique_lock<std::mutex> lock(_mutex);
        _stateChanged.wait(lock, [this] { return !_transitioning; });
        if (_state == LifecycleState::finalized)
            return;
        _transitioning = true;
    }
    onShutdown();
    std::lock_guard<std::mutex> lock(_mutex);
    _state = LifecycleState::finalized;
    _transitioning = false;
    _stateChanged.notify_all();
}

bool LifecycleComponent::onConfigure() { return true; }
bool LifecycleComponent::onActivate() { return true; }
bool LifecycleComponent::onDeactivate() { return true; }
bool LifecycleComponent::onCleanup() { return true; }
void LifecycleComponent::onShutdown() noexcept {}
} // namespace PocoDDS::Robotics
