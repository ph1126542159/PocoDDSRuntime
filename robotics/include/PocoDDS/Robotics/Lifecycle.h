#pragma once

#include <condition_variable>
#include <mutex>
#include <string>

namespace PocoDDS::Robotics
{
enum class LifecycleState
{
    unconfigured,
    inactive,
    active,
    finalized,
    error
};

class LifecycleComponent
{
  public:
    virtual ~LifecycleComponent() = default;

    LifecycleState state() const noexcept;
    std::string lastError() const;
    bool configure();
    bool activate();
    bool deactivate();
    bool cleanup();
    void shutdown() noexcept;

  protected:
    virtual bool onConfigure();
    virtual bool onActivate();
    virtual bool onDeactivate();
    virtual bool onCleanup();
    virtual void onShutdown() noexcept;

  private:
    template <typename Callback>
    bool transition(LifecycleState required, LifecycleState next, Callback&& callback);

    mutable std::mutex _mutex;
    std::condition_variable _stateChanged;
    LifecycleState _state{LifecycleState::unconfigured};
    bool _transitioning{false};
    std::string _lastError;
};
} // namespace PocoDDS::Robotics
