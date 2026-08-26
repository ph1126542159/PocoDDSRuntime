#include "PocoDDS/Scheduling/Scheduler.h"

#include "PocoDDS/ResourceGovernance/ResourceGovernor.h"

#include <atomic>
#include <chrono>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <thread>

using namespace PocoDDS;
using namespace std::chrono_literals;

namespace
{
bool waitFor(const std::function<bool()>& predicate,
             std::chrono::milliseconds timeout = 3s)
{
    const auto deadline = std::chrono::steady_clock::now() + timeout;
    while (std::chrono::steady_clock::now() < deadline)
    {
        if (predicate()) return true;
        std::this_thread::sleep_for(2ms);
    }
    return predicate();
}

Scheduling::TaskSpec spec(std::string id, std::string owner,
                          std::chrono::milliseconds interval,
                          Scheduling::ScheduleMode mode = Scheduling::ScheduleMode::fixedDelay,
                          Scheduling::MisfirePolicy misfire = Scheduling::MisfirePolicy::skip)
{
    Scheduling::TaskSpec value;
    value.id = std::move(id);
    value.owner = std::move(owner);
    value.interval = interval;
    value.rejectionBackoff = 10ms;
    value.mode = mode;
    value.misfire = misfire;
    return value;
}
} // namespace

int main()
{
    try
    {
        ResourceGovernance::ResourceGovernor governor(
            {"*", 4, 32, 1s, 2s, 10, 100ms});
        auto submit = [&](const std::string& owner, ResourceGovernance::WorkItem item) {
            return governor.submit(owner, std::move(item));
        };
        Scheduling::Scheduler scheduler(submit);

        std::atomic<int> fixedDelayRuns{0};
        std::atomic<int> fixedDelayActive{0};
        std::atomic<int> fixedDelayPeak{0};
        auto fixedDelay = spec("fixed-delay", "fixed-delay.bundle", 15ms);
        fixedDelay.jitter = 5ms;
        if (scheduler.schedule(fixedDelay, [&](const Scheduling::CancellationToken&) {
                const int active = ++fixedDelayActive;
                int peak = fixedDelayPeak.load();
                while (active > peak && !fixedDelayPeak.compare_exchange_weak(peak, active)) {}
                std::this_thread::sleep_for(8ms);
                --fixedDelayActive;
                ++fixedDelayRuns;
            }).status != Scheduling::RegistrationStatus::registered ||
            !waitFor([&] { return fixedDelayRuns.load() >= 4; }))
            throw std::runtime_error("fixed-delay task did not execute");
        const auto delaySnapshot = scheduler.snapshot("fixed-delay");
        if (!delaySnapshot || fixedDelayPeak.load() != 1 ||
            delaySnapshot->triggered < 4 || delaySnapshot->misfires != 0 ||
            delaySnapshot->spec.jitter != 5ms)
            throw std::runtime_error("fixed-delay or jitter semantics are incorrect");
        scheduler.cancelAndWait("fixed-delay");

        std::atomic<int> skipRuns{0};
        if (scheduler.schedule(
                spec("fixed-rate-skip", "skip.bundle", 10ms,
                     Scheduling::ScheduleMode::fixedRate,
                     Scheduling::MisfirePolicy::skip),
                [&](const Scheduling::CancellationToken&) {
                    ++skipRuns;
                    std::this_thread::sleep_for(45ms);
                }).status != Scheduling::RegistrationStatus::registered ||
            !waitFor([&] {
                const auto value = scheduler.snapshot("fixed-rate-skip");
                return value && value->completed >= 2 && value->misfires >= 2;
            }))
            throw std::runtime_error("fixed-rate skip misfires were not recorded");
        const auto skipSnapshot = scheduler.snapshot("fixed-rate-skip");
        if (!skipSnapshot || skipSnapshot->misfires < 2 || skipRuns.load() < 2)
            throw std::runtime_error("fixed-rate skip snapshot is incomplete");
        scheduler.cancelAndWait("fixed-rate-skip");

        std::atomic<int> coalescedRuns{0};
        if (scheduler.schedule(
                spec("fixed-rate-coalesce", "coalesce.bundle", 10ms,
                     Scheduling::ScheduleMode::fixedRate,
                     Scheduling::MisfirePolicy::coalesce),
                [&](const Scheduling::CancellationToken&) {
                    const int run = ++coalescedRuns;
                    if (run == 1) std::this_thread::sleep_for(45ms);
                }).status != Scheduling::RegistrationStatus::registered ||
            !waitFor([&] {
                const auto value = scheduler.snapshot("fixed-rate-coalesce");
                return coalescedRuns.load() >= 3 && value && value->misfires >= 2;
            }))
            throw std::runtime_error("coalesced misfire did not trigger a follow-up run");
        scheduler.cancelAndWait("fixed-rate-coalesce");

        std::atomic<int> reconfiguredRuns{0};
        auto managed = spec("managed-reconfigure", "managed.bundle", 15ms);
        if (scheduler.schedule(managed, [&](const Scheduling::CancellationToken&) {
                ++reconfiguredRuns;
            }).status != Scheduling::RegistrationStatus::registered ||
            !waitFor([&] { return reconfiguredRuns.load() >= 2; }))
            throw std::runtime_error("reconfiguration task did not start");
        const auto beforeDisable = scheduler.snapshot("managed-reconfigure");
        managed.enabled = false;
        managed.interval = 40ms;
        managed.initialDelay = 40ms;
        managed.jitter = 5ms;
        managed.rejectionBackoff = 40ms;
        if (scheduler.reconfigure(managed).status !=
                Scheduling::ReconfigurationStatus::reconfigured)
            throw std::runtime_error("valid schedule reconfiguration was rejected");
        std::this_thread::sleep_for(20ms);
        const int disabledRuns = reconfiguredRuns.load();
        std::this_thread::sleep_for(100ms);
        const auto disabled = scheduler.snapshot("managed-reconfigure");
        if (reconfiguredRuns.load() != disabledRuns || !disabled || disabled->spec.enabled ||
            disabled->nextRunIn || !beforeDisable ||
            disabled->triggered < beforeDisable->triggered)
            throw std::runtime_error("disabled schedule still triggered or lost counters");

        managed.enabled = true;
        managed.initialDelay = 5ms;
        if (scheduler.reconfigure(managed).status !=
                Scheduling::ReconfigurationStatus::reconfigured ||
            !waitFor([&] { return reconfiguredRuns.load() >= disabledRuns + 2; }))
            throw std::runtime_error("re-enabled schedule did not resume");
        auto wrongOwner = managed;
        wrongOwner.owner = "other.bundle";
        auto invalidReconfiguration = managed;
        invalidReconfiguration.jitter = invalidReconfiguration.interval + 1ms;
        auto missingReconfiguration = managed;
        missingReconfiguration.id = "missing-task";
        if (scheduler.reconfigure(wrongOwner).status !=
                Scheduling::ReconfigurationStatus::invalid ||
            scheduler.reconfigure(invalidReconfiguration).status !=
                Scheduling::ReconfigurationStatus::invalid ||
            scheduler.reconfigure(missingReconfiguration).status !=
                Scheduling::ReconfigurationStatus::notFound)
            throw std::runtime_error("invalid schedule reconfiguration was accepted");
        scheduler.cancelAndWait("managed-reconfigure");

        std::atomic<int> submitAttempts{0};
        Scheduling::Scheduler rejecting([&](const std::string& owner,
                                             ResourceGovernance::WorkItem item) {
            if (++submitAttempts <= 2)
                return ResourceGovernance::Admission{
                    ResourceGovernance::AdmissionStatus::queueFull,
                    owner, item.id, "injected rejection"};
            return governor.submit(owner, std::move(item));
        });
        std::atomic<int> recoveredRuns{0};
        if (rejecting.schedule(spec("rejection-recovery", "reject.bundle", 100ms),
                [&](const Scheduling::CancellationToken&) { ++recoveredRuns; }).status !=
                Scheduling::RegistrationStatus::registered ||
            !waitFor([&] { return recoveredRuns.load() == 1; }))
            throw std::runtime_error("admission rejection backoff did not recover");
        const auto rejection = rejecting.snapshot("rejection-recovery");
        if (!rejection || rejection->rejected != 2 || rejection->accepted < 1)
            throw std::runtime_error("admission rejection counters are incomplete");
        rejecting.cancelAndWait("rejection-recovery");

        std::atomic<bool> cancellationStarted{false};
        std::atomic<bool> cancellationObserved{false};
        auto callbackLifetime = std::make_shared<int>(1);
        std::weak_ptr<int> callbackLifetimeProbe = callbackLifetime;
        if (scheduler.schedule(spec("cancel", "cancel.bundle", 1s),
                [&, callbackLifetime](const Scheduling::CancellationToken& token) {
                    cancellationStarted = true;
                    while (!token.requested()) std::this_thread::sleep_for(2ms);
                    cancellationObserved = true;
                }).status != Scheduling::RegistrationStatus::registered ||
            !waitFor([&] { return cancellationStarted.load(); }))
            throw std::runtime_error("cancellation task did not start");
        callbackLifetime.reset();
        if (!scheduler.cancelAndWait("cancel") || !cancellationObserved.load() ||
            !callbackLifetimeProbe.expired())
            throw std::runtime_error("cancel-and-wait did not form an unload barrier");

        auto futureLifetime = std::make_shared<int>(2);
        std::weak_ptr<int> futureLifetimeProbe = futureLifetime;
        auto future = spec("future-cancel", "future.bundle", 1s);
        future.initialDelay = 1h;
        if (scheduler.schedule(future,
                [futureLifetime](const Scheduling::CancellationToken&) {}).status !=
                Scheduling::RegistrationStatus::registered)
            throw std::runtime_error("future cancellation task was not registered");
        futureLifetime.reset();
        if (!scheduler.cancelAndWait("future-cancel") || !futureLifetimeProbe.expired())
            throw std::runtime_error("idle timer wait retained a Bundle callback after cancel");

        if (scheduler.schedule(spec("duplicate", "duplicate.bundle", 1s),
                [](const auto&) {}).status != Scheduling::RegistrationStatus::registered ||
            scheduler.schedule(spec("duplicate", "duplicate.bundle", 1s),
                [](const auto&) {}).status != Scheduling::RegistrationStatus::duplicate)
            throw std::runtime_error("duplicate schedule id was not rejected");
        auto invalid = spec("invalid", "invalid.bundle", 0ms);
        if (scheduler.schedule(invalid, [](const auto&) {}).status !=
                Scheduling::RegistrationStatus::invalid)
            throw std::runtime_error("invalid schedule was accepted");
        scheduler.cancelAndWait("duplicate");

        scheduler.shutdown();
        if (scheduler.schedule(spec("after-shutdown", "late.bundle", 1s),
                [](const auto&) {}).status != Scheduling::RegistrationStatus::shuttingDown)
            throw std::runtime_error("scheduler accepted work after shutdown");
        if (scheduler.reconfigure(spec("after-shutdown", "late.bundle", 1s)).status !=
                Scheduling::ReconfigurationStatus::shuttingDown)
            throw std::runtime_error("scheduler reconfigured work after shutdown");

        std::cout << "SCHEDULER_SMOKE_PASS fixedDelay=1 fixedRate=1 skip=1 "
                     "coalesce=1 jitter=1 rejectionBackoff=1 cancelBarrier=1 "
                     "transactionalReconfigure=1\n";
        return 0;
    }
    catch (const std::exception& exception)
    {
        std::cerr << "SCHEDULER_SMOKE_FAIL " << exception.what() << '\n';
        return 1;
    }
}
