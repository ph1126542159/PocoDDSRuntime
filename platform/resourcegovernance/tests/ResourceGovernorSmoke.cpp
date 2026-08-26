#include "PocoDDS/ResourceGovernance/ResourceGovernor.h"

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <iostream>
#include <mutex>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

using namespace PocoDDS::ResourceGovernance;
using namespace std::chrono_literals;

namespace
{
bool waitFor(const std::function<bool()>& predicate,
             std::chrono::milliseconds timeout = 2s)
{
    const auto deadline = std::chrono::steady_clock::now() + timeout;
    while (std::chrono::steady_clock::now() < deadline)
    {
        if (predicate()) return true;
        std::this_thread::sleep_for(2ms);
    }
    return predicate();
}

Policy policy(std::string owner, std::size_t concurrency,
              std::size_t queue, std::chrono::milliseconds queueTimeout,
              std::chrono::milliseconds executionTimeout,
              std::size_t failureThreshold = 5,
              std::chrono::milliseconds resetTimeout = 100ms)
{
    return {std::move(owner), concurrency, queue, queueTimeout,
            executionTimeout, failureThreshold, resetTimeout};
}
} // namespace

int main()
{
    try
    {
        ResourceGovernor governor(
            policy("*", 2, 32, 1s, 1s),
            {policy("slow.bundle", 1, 1, 40ms, 1s),
             policy("timeout.bundle", 1, 4, 1s, 40ms),
             policy("drain.bundle", 1, 4, 1s, 40ms),
             policy("failing.bundle", 1, 4, 1s, 1s, 2, 50ms),
             policy("parallel.bundle", 3, 64, 1s, 1s)});

        std::atomic<bool> releaseSlow{false};
        std::atomic<CompletionStatus> queuedStatus{CompletionStatus::failed};
        std::atomic<bool> queuedCompleted{false};
        const auto first = governor.submit("slow.bundle", {"slow-active",
            [&](const CancellationToken&) {
                while (!releaseSlow.load()) std::this_thread::sleep_for(2ms);
            }, {}});
        if (first.status != AdmissionStatus::accepted ||
            !waitFor([&] { return governor.snapshot("slow.bundle").active == 1; }))
            throw std::runtime_error("slow owner did not occupy its isolated slot");
        if (governor.submit("slow.bundle", {"slow-queued", [](const auto&) {},
                [&](const Completion& completion) {
                    queuedStatus = completion.status;
                    queuedCompleted = true;
                }}).status != AdmissionStatus::accepted)
            throw std::runtime_error("bounded owner queue rejected its only waiting item");
        if (governor.submit("slow.bundle", {"slow-rejected", [](const auto&) {}, {}})
                .status != AdmissionStatus::queueFull)
            throw std::runtime_error("bounded owner queue did not apply backpressure");

        std::atomic<bool> fastCompleted{false};
        if (governor.submit("fast.bundle", {"fast-independent", [](const auto&) {},
                [&](const Completion& completion) {
                    fastCompleted = completion.status == CompletionStatus::succeeded;
                }}).status != AdmissionStatus::accepted ||
            !waitFor([&] { return fastCompleted.load(); }, 250ms))
            throw std::runtime_error("one saturated owner blocked an independent owner");
        std::this_thread::sleep_for(60ms);
        releaseSlow = true;
        if (!waitFor([&] { return queuedCompleted.load(); }) ||
            queuedStatus != CompletionStatus::queueTimedOut)
            throw std::runtime_error("queue waiting deadline was not enforced");

        std::atomic<CompletionStatus> timeoutStatus{CompletionStatus::failed};
        std::atomic<bool> timeoutCompleted{false};
        governor.submit("timeout.bundle", {"cooperative-timeout",
            [](const CancellationToken& token) {
                while (!token.requested()) std::this_thread::sleep_for(2ms);
            }, [&](const Completion& completion) {
                timeoutStatus = completion.status;
                timeoutCompleted = true;
            }});
        if (!waitFor([&] { return timeoutCompleted.load(); }) ||
            timeoutStatus != CompletionStatus::executionTimedOut)
            throw std::runtime_error("cooperative execution timeout was not signalled");

        std::atomic<int> failureCompletions{0};
        for (int index = 0; index < 2; ++index)
        {
            const auto id = "failure-" + std::to_string(index);
            if (governor.submit("failing.bundle", {id,
                    [](const CancellationToken&) { throw std::runtime_error("injected"); },
                    [&](const Completion& completion) {
                        if (completion.status == CompletionStatus::failed)
                            ++failureCompletions;
                    }}).status != AdmissionStatus::accepted)
                throw std::runtime_error("failure injection was not admitted");
            if (!waitFor([&] { return failureCompletions.load() == index + 1; }))
                throw std::runtime_error("failure injection did not complete");
        }
        if (governor.snapshot("failing.bundle").circuit != CircuitState::open ||
            governor.submit("failing.bundle", {"open-reject", [](const auto&) {}, {}})
                .status != AdmissionStatus::circuitOpen)
            throw std::runtime_error("failure threshold did not open the owner circuit");
        std::this_thread::sleep_for(60ms);
        std::atomic<bool> probeCompleted{false};
        if (governor.submit("failing.bundle", {"half-open-probe", [](const auto&) {},
                [&](const Completion& completion) {
                    probeCompleted = completion.status == CompletionStatus::succeeded;
                }}).status != AdmissionStatus::accepted ||
            !waitFor([&] { return probeCompleted.load(); }) ||
            governor.snapshot("failing.bundle").circuit != CircuitState::closed)
            throw std::runtime_error("successful half-open probe did not close the circuit");

        std::atomic<int> active{0};
        std::atomic<int> peak{0};
        std::atomic<int> completed{0};
        for (int index = 0; index < 24; ++index)
        {
            const auto admitted = governor.submit("parallel.bundle",
                {"parallel-" + std::to_string(index),
                 [&](const CancellationToken&) {
                     const int current = ++active;
                     int observed = peak.load();
                     while (current > observed && !peak.compare_exchange_weak(observed, current)) {}
                     std::this_thread::sleep_for(5ms);
                     --active;
                 }, [&](const Completion& value) {
                     if (value.status == CompletionStatus::succeeded) ++completed;
                 }});
            if (admitted.status != AdmissionStatus::accepted)
                throw std::runtime_error("parallel work was unexpectedly rejected");
        }
        if (!waitFor([&] { return completed.load() == 24; }) || peak.load() != 3)
            throw std::runtime_error("per-owner maximum concurrency was not enforced");

        const auto slow = governor.snapshot("slow.bundle");
        const auto timed = governor.snapshot("timeout.bundle");
        if (slow.rejectedQueueFull != 1 || slow.queueTimedOut != 1 ||
            timed.executionTimedOut != 1 ||
            governor.snapshots().size() != 5)
            throw std::runtime_error("resource governance counters are incomplete");

        std::atomic<CompletionStatus> drainStatus{CompletionStatus::failed};
        if (governor.submit("drain.bundle", {"drain-timeout",
                [](const CancellationToken& token) {
                    while (!token.requested()) std::this_thread::sleep_for(2ms);
                }, [&](const Completion& completion) {
                    drainStatus = completion.status;
                }}).status != AdmissionStatus::accepted)
            throw std::runtime_error("drain deadline test was not admitted");
        governor.shutdown(ShutdownMode::drain);
        if (drainStatus != CompletionStatus::executionTimedOut)
            throw std::runtime_error("drain stopped cooperative deadline monitoring");
        if (governor.submit("after.shutdown", {"rejected", [](const auto&) {}, {}})
                .status != AdmissionStatus::shuttingDown)
            throw std::runtime_error("governor accepted work after shutdown");

        std::cout << "RESOURCE_GOVERNOR_SMOKE_PASS isolation=1 backpressure=1 "
                     "queueTimeout=1 executionTimeout=1 drainTimeout=1 "
                     "circuit=1 concurrency=3\n";
        return 0;
    }
    catch (const std::exception& exception)
    {
        std::cerr << "RESOURCE_GOVERNOR_SMOKE_FAIL " << exception.what() << '\n';
        return 1;
    }
}
