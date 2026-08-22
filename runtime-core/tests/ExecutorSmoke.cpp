#include "PocoDDS/RuntimeCore/Executor.h"

#include <atomic>
#include <future>
#include <iostream>
#include <memory>

int main()
{
    using namespace PocoDDS::RuntimeCore;

    ThreadPoolExecutor::Options options;
    options.workerCount = 1;
    options.queueCapacity = 1;
    options.overflowPolicy = OverflowPolicy::dropOldest;
    ThreadPoolExecutor executor(options);

    auto release = std::make_shared<std::promise<void>>();
    auto releaseFuture = release->get_future().share();
    auto started = std::make_shared<std::promise<void>>();
    auto startedFuture = started->get_future();
    auto cancelled = std::make_shared<std::promise<RuntimeError>>();
    auto cancelledFuture = cancelled->get_future();
    auto newestRan = std::make_shared<std::promise<void>>();
    auto newestFuture = newestRan->get_future();
    std::atomic<bool> displacedRan{false};

    if (executor.submit({[started, releaseFuture]
                         {
                             started->set_value();
                             releaseFuture.wait();
                         },
                         {}}) != SubmitStatus::accepted)
        return 1;
    startedFuture.wait();

    if (executor.submit({[&displacedRan] { displacedRan = true; }, [cancelled](RuntimeError error)
                         { cancelled->set_value(std::move(error)); }}) != SubmitStatus::accepted)
        return 2;

    const auto newestStatus = executor.submit({[newestRan] { newestRan->set_value(); }, {}});
    if (newestStatus != SubmitStatus::acceptedAfterDroppingOldest)
        return 3;
    const auto displacedError = cancelledFuture.get();
    if (displacedError.code != RuntimeErrorCode::queueFull || !displacedError.retryable)
        return 4;

    release->set_value();
    newestFuture.wait();
    executor.shutdown(ShutdownMode::drain);
    if (displacedRan || executor.pending() != 0)
        return 5;

    InlineExecutor inlineExecutor;
    inlineExecutor.shutdown();
    RuntimeError stoppedError;
    if (inlineExecutor.submit({[] {}, [&stoppedError](RuntimeError error)
                               { stoppedError = std::move(error); }}) != SubmitStatus::stopped ||
        stoppedError.code != RuntimeErrorCode::stopped)
        return 6;

    std::cout << "PDR_RUNTIME_CORE_EXECUTOR_PASS backpressure=drop-oldest shutdown=drain\n";
    return 0;
}
