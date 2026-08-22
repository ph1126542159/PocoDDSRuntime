#pragma once

#include "PocoDDS/RuntimeCore/Contract.h"
#include "PocoDDS/RuntimeCore/Export.h"

#include <atomic>
#include <chrono>
#include <cstddef>
#include <functional>
#include <memory>

namespace PocoDDS::RuntimeCore
{

enum class OverflowPolicy
{
    rejectNewest,
    dropOldest,
    blockPublisher
};

enum class ShutdownMode
{
    drain,
    cancelPending
};

enum class SubmitStatus
{
    accepted,
    acceptedAfterDroppingOldest,
    rejected,
    timedOut,
    stopped,
    executionFailed
};

struct ExecutorTask
{
    std::function<void()> run;
    std::function<void(RuntimeError)> cancel;
};

class PDR_RUNTIME_CORE_API IExecutor
{
  public:
    virtual ~IExecutor() = default;
    virtual SubmitStatus submit(ExecutorTask task) = 0;
    virtual void shutdown(ShutdownMode mode = ShutdownMode::drain) noexcept = 0;
    virtual std::size_t pending() const noexcept = 0;
};

class PDR_RUNTIME_CORE_API InlineExecutor final : public IExecutor
{
  public:
    SubmitStatus submit(ExecutorTask task) override;
    void shutdown(ShutdownMode mode = ShutdownMode::drain) noexcept override;
    std::size_t pending() const noexcept override;

  private:
    std::atomic<bool> _stopped{false};
};

class PDR_RUNTIME_CORE_API ThreadPoolExecutor final : public IExecutor
{
  public:
    struct Options
    {
        std::size_t workerCount{1};
        std::size_t queueCapacity{1024};
        OverflowPolicy overflowPolicy{OverflowPolicy::rejectNewest};
        std::chrono::milliseconds blockTimeout{1000};
    };

    explicit ThreadPoolExecutor(Options options);
    ~ThreadPoolExecutor() override;

    ThreadPoolExecutor(const ThreadPoolExecutor&) = delete;
    ThreadPoolExecutor& operator=(const ThreadPoolExecutor&) = delete;

    SubmitStatus submit(ExecutorTask task) override;
    void shutdown(ShutdownMode mode = ShutdownMode::drain) noexcept override;
    std::size_t pending() const noexcept override;

  private:
    struct State;
    std::shared_ptr<State> _state;
};

} // namespace PocoDDS::RuntimeCore
