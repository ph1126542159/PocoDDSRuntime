#include "PocoDDS/Scheduling/ScheduleConfigurationParticipant.h"

#include "PocoDDS/ConfigTransaction/SqliteTransactionStore.h"
#include "PocoDDS/ConfigTransaction/TransactionEngine.h"
#include "PocoDDS/ResourceGovernance/ResourceGovernor.h"

#include <Poco/AutoPtr.h>
#include <Poco/File.h>
#include <Poco/Path.h>
#include <Poco/TemporaryFile.h>
#include <Poco/UUIDGenerator.h>

#include <atomic>
#include <chrono>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <thread>

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

class SchedulerAdapter final : public PocoDDS::Scheduling::SchedulerService
{
public:
    explicit SchedulerAdapter(PocoDDS::Scheduling::Scheduler& scheduler)
        : _scheduler(scheduler) {}

    PocoDDS::Scheduling::Registration schedule(
        PocoDDS::Scheduling::TaskSpec spec,
        PocoDDS::Scheduling::TaskCallback run,
        PocoDDS::Scheduling::CompletionCallback complete) override
    {
        return _scheduler.schedule(std::move(spec), std::move(run), std::move(complete));
    }

    PocoDDS::Scheduling::Reconfiguration reconfigure(
        PocoDDS::Scheduling::TaskSpec spec) override
    {
        return _scheduler.reconfigure(std::move(spec));
    }

    bool cancelAndWait(const std::string& taskId) noexcept override
    {
        return _scheduler.cancelAndWait(taskId);
    }

    std::optional<PocoDDS::Scheduling::TaskSnapshot> snapshot(
        const std::string& taskId) const override
    {
        return _scheduler.snapshot(taskId);
    }

    std::vector<PocoDDS::Scheduling::TaskSnapshot> snapshots() const override
    {
        return _scheduler.snapshots();
    }

private:
    PocoDDS::Scheduling::Scheduler& _scheduler;
};

class RejectingParticipant final
    : public PocoDDS::ConfigTransaction::ConfigurationParticipantService
{
public:
    PocoDDS::ConfigTransaction::ParticipantDescriptor descriptor() const override
    {
        return {"later-participant", {"later.value"}, {"managed-scheduler"}};
    }
    PocoDDS::ConfigTransaction::ParticipantResult preflight(
        const PocoDDS::ConfigTransaction::Context&) override
    {
        return PocoDDS::ConfigTransaction::ParticipantResult::accepted();
    }
    PocoDDS::ConfigTransaction::ParticipantResult commit(
        const PocoDDS::ConfigTransaction::Context&) override
    {
        return PocoDDS::ConfigTransaction::ParticipantResult::rejected(
            "injected-failure", "force schedule rollback");
    }
    PocoDDS::ConfigTransaction::ParticipantResult rollback(
        const PocoDDS::ConfigTransaction::Context&) override
    {
        return PocoDDS::ConfigTransaction::ParticipantResult::accepted();
    }
};
} // namespace

int main()
{
    using namespace PocoDDS;
    using namespace PocoDDS::ConfigTransaction;
    using namespace PocoDDS::Scheduling;
    try
    {
        Poco::Path path(Poco::TemporaryFile::tempName());
        path.setFileName("pdr-schedule-configuration-" +
            Poco::UUIDGenerator::defaultGenerator().createRandom().toString() + ".sqlite");
        const auto database = path.toString();
        ResourceGovernance::ResourceGovernor governor(
            {"*", 2, 16, 1s, 2s, 10, 100ms});
        Scheduler scheduler([&](const std::string& owner,
                                ResourceGovernance::WorkItem item) {
            return governor.submit(owner, std::move(item));
        });
        std::atomic<int> runs{0};
        TaskSpec task;
        task.id = "managed-task";
        task.owner = "managed.bundle";
        task.interval = 10ms;
        task.rejectionBackoff = 10ms;
        if (scheduler.schedule(task, [&](const CancellationToken&) { ++runs; }).status !=
                RegistrationStatus::registered ||
            !waitFor([&] { return runs.load() >= 2; }))
            throw std::runtime_error("managed task did not start");

        Poco::AutoPtr<SchedulerService> adapter = new SchedulerAdapter(scheduler);
        Poco::AutoPtr<ConfigurationParticipantService> scheduleParticipant =
            new ScheduleConfigurationParticipant(
                {"managed-scheduler", "managed-task", "managed.bundle",
                 "managed.enabled", "managed.interval", "managed.jitter"},
                adapter);
        TransactionEngine engine(std::make_unique<SqliteTransactionStore>(database));
        const Values initial{{"managed.enabled", "true"},
                             {"managed.interval", "10"},
                             {"managed.jitter", "0"},
                             {"later.value", "ok"}};
        engine.initialize(initial);
        auto scheduleRegistration = engine.attach(scheduleParticipant);
        auto rejectingRegistration = engine.attach(
            Poco::AutoPtr<ConfigurationParticipantService>(new RejectingParticipant));

        auto rollbackCandidate = initial;
        rollbackCandidate["managed.enabled"] = "false";
        rollbackCandidate["managed.interval"] = "40";
        rollbackCandidate["later.value"] = "fail";
        const auto rolledBack = engine.apply(
            {"schedule-rollback", 1, rollbackCandidate});
        const auto afterRollback = scheduler.snapshot("managed-task");
        if (rolledBack.status != Status::rolledBack || !rolledBack.rolledBack ||
            !afterRollback || !afterRollback->spec.enabled ||
            afterRollback->spec.interval != 10ms)
            throw std::runtime_error("failed transaction did not restore schedule");

        rejectingRegistration.reset();
        auto disabledCandidate = initial;
        disabledCandidate["managed.enabled"] = "false";
        disabledCandidate["managed.interval"] = "40";
        const auto disabledResult = engine.apply(
            {"schedule-disable", 1, disabledCandidate});
        const auto disabled = scheduler.snapshot("managed-task");
        if (disabledResult.status != Status::committed || !disabled || disabled->spec.enabled ||
            disabled->spec.interval != 40ms || disabled->nextRunIn)
            throw std::runtime_error("schedule disable transaction did not commit");
        std::this_thread::sleep_for(20ms);
        const int disabledRuns = runs.load();
        std::this_thread::sleep_for(100ms);
        if (runs.load() != disabledRuns)
            throw std::runtime_error("disabled transactional schedule still executed");

        auto enabledCandidate = disabledCandidate;
        enabledCandidate["managed.enabled"] = "true";
        enabledCandidate["managed.interval"] = "25";
        enabledCandidate["managed.jitter"] = "5";
        const auto enabledResult = engine.apply(
            {"schedule-enable", 2, enabledCandidate});
        if (enabledResult.status != Status::committed ||
            !waitFor([&] { return runs.load() >= disabledRuns + 2; }))
            throw std::runtime_error("schedule enable transaction did not resume execution");
        const auto enabled = scheduler.snapshot("managed-task");
        if (!enabled || !enabled->spec.enabled || enabled->spec.interval != 25ms ||
            enabled->spec.jitter != 5ms)
            throw std::runtime_error("committed schedule settings are incomplete");

        auto invalidCandidate = enabledCandidate;
        invalidCandidate["managed.jitter"] = "26";
        const auto invalid = engine.apply(
            {"schedule-invalid", 3, invalidCandidate});
        const auto afterInvalid = scheduler.snapshot("managed-task");
        if (invalid.status != Status::preflightFailed || !afterInvalid ||
            afterInvalid->spec.jitter != 5ms || engine.current().generation != 3)
            throw std::runtime_error("invalid schedule transaction mutated active state");

        scheduleRegistration.reset();
        scheduler.cancelAndWait("managed-task");
        scheduler.shutdown();
        try { Poco::File(database).remove(); } catch (...) {}
        try { Poco::File(database + "-wal").remove(); } catch (...) {}
        try { Poco::File(database + "-shm").remove(); } catch (...) {}
        std::cout << "SCHEDULE_CONFIGURATION_PASS rollback=true disable=true "
                     "reenable=true preflight=true\n";
        return 0;
    }
    catch (const std::exception& exception)
    {
        std::cerr << "SCHEDULE_CONFIGURATION_FAIL " << exception.what() << '\n';
        return 1;
    }
}
