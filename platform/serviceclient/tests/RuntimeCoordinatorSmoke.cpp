#include "PocoDDS/ServiceClient/RuntimeCoordinator.h"

#include <Poco/AutoPtr.h>
#include <Poco/Timestamp.h>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <iostream>
#include <map>
#include <mutex>
#include <stdexcept>
#include <string>
#include <utility>

using namespace std::chrono_literals;
using namespace PocoDDS::ResourceGovernance;
using namespace PocoDDS::ServiceClient;
using namespace PocoDDS::ServiceDirectory;

namespace
{
void require(bool condition, const std::string& detail)
{
    if (!condition) throw std::runtime_error(detail);
}

class DirectoryService final : public ServiceDirectoryRuntimeService
{
public:
    ObservationResult observe(Advertisement value) override
    {
        return _directory.observe(std::move(value));
    }
    bool withdraw(const std::string& serviceName,
                  const std::string& instanceId,
                  const std::string& runtimeId,
                  std::uint64_t incarnation,
                  std::uint64_t revision) override
    {
        return _directory.withdraw(serviceName, instanceId, runtimeId,
                                   incarnation, revision);
    }
    PocoDDS::ServiceDirectory::Snapshot snapshot() const override
    {
        return _directory.snapshot();
    }
    RouteResult route(const RouteRequest& request) override
    {
        return _router.select(_directory.snapshot(), request);
    }

private:
    Directory _directory;
    Router _router;
};

class GovernorService final : public ResourceGovernorService
{
public:
    GovernorService()
        : _governor(PocoDDS::ResourceGovernance::Policy{
              "*", 2, 8, 1000ms, 1000ms, 3, 100ms})
    {
    }

    Admission submit(const std::string& owner, WorkItem item) override
    {
        if (item.id == "governor-throws")
            throw std::runtime_error("simulated governor submit failure");
        return _governor.submit(owner, std::move(item));
    }
    PocoDDS::ResourceGovernance::Snapshot snapshot(
        const std::string& owner) const override
    {
        return _governor.snapshot(owner);
    }
    std::vector<PocoDDS::ResourceGovernance::Snapshot> snapshots()
        const override
    {
        return _governor.snapshots();
    }

private:
    ResourceGovernor _governor;
};

class Provider final : public ServiceInvocationProvider
{
public:
    using Callback = std::function<AttemptResult(
        const ProviderInvocationRequest&)>;

    explicit Provider(Callback callback): _callback(std::move(callback)) {}
    std::string providerId() const override { return "loopback-provider"; }
    std::string protocol() const override { return "loopback"; }
    AttemptResult invoke(const ProviderInvocationRequest& request) override
    {
        return _callback(request);
    }

private:
    Callback _callback;
};

class MemoryJournal final : public InvocationJournal
{
public:
    InvocationJournalClaim claim(
        const InvocationJournalClaimRequest& request) override
    {
        std::lock_guard<std::mutex> lock(_mutex);
        ++_snapshot.claims;
        const auto found = _entries.find(request.scopeDigest);
        if (found == _entries.end())
        {
            _entries.emplace(request.scopeDigest,
                             Entry{request.requestDigest,
                                   request.invocationId, {}});
            update();
            return {InvocationJournalClaimStatus::acquired,
                    request.invocationId, {}, {}};
        }
        if (found->second.requestDigest != request.requestDigest)
        {
            ++_snapshot.conflicts;
            return {InvocationJournalClaimStatus::conflict,
                    found->second.invocationId, {}, "request conflict"};
        }
        if (found->second.completion)
        {
            ++_snapshot.replays;
            return {InvocationJournalClaimStatus::replayCompleted,
                    found->second.invocationId,
                    found->second.completion, {}};
        }
        ++_snapshot.indeterminate;
        return {InvocationJournalClaimStatus::indeterminate,
                found->second.invocationId, {}, "in-flight"};
    }

    void complete(const std::string& scopeDigest,
                  const std::string& requestDigest,
                  const std::string& invocationId,
                  const InvocationCompletion& completion,
                  std::int64_t) override
    {
        std::lock_guard<std::mutex> lock(_mutex);
        if (_failNextComplete)
        {
            _failNextComplete = false;
            throw std::runtime_error("simulated journal commit failure");
        }
        const auto found = _entries.find(scopeDigest);
        if (found == _entries.end() ||
            found->second.requestDigest != requestDigest ||
            found->second.invocationId != invocationId ||
            found->second.completion)
            throw std::runtime_error("journal completion ownership mismatch");
        found->second.completion =
            std::make_shared<const InvocationCompletion>(completion);
        update();
    }

    bool release(const std::string& scopeDigest,
                 const std::string& requestDigest,
                 const std::string& invocationId) override
    {
        std::lock_guard<std::mutex> lock(_mutex);
        const auto found = _entries.find(scopeDigest);
        if (found == _entries.end() || found->second.completion ||
            found->second.requestDigest != requestDigest ||
            found->second.invocationId != invocationId)
            return false;
        _entries.erase(found);
        update();
        return true;
    }

    InvocationJournalSnapshot snapshot() const override
    {
        std::lock_guard<std::mutex> lock(_mutex);
        return _snapshot;
    }

    void failNextComplete()
    {
        std::lock_guard<std::mutex> lock(_mutex);
        _failNextComplete = true;
    }

private:
    struct Entry
    {
        std::string requestDigest;
        std::string invocationId;
        std::shared_ptr<const InvocationCompletion> completion;
    };

    void update()
    {
        _snapshot.enabled = true;
        _snapshot.healthy = true;
        _snapshot.backend = "memory-test";
        _snapshot.maximumEntries = 64;
        _snapshot.entries = _entries.size();
        _snapshot.inFlight = 0;
        _snapshot.completed = 0;
        for (const auto& [_, entry] : _entries)
            entry.completion ? ++_snapshot.completed : ++_snapshot.inFlight;
    }

    mutable std::mutex _mutex;
    std::map<std::string, Entry> _entries;
    InvocationJournalSnapshot _snapshot;
    bool _failNextComplete{false};
};

Advertisement advertisement(std::string instance, std::string runtime)
{
    Advertisement value;
    value.serviceName = "orders.v1";
    value.instanceId = std::move(instance);
    value.runtimeId = std::move(runtime);
    value.runtimeIncarnation = 1;
    value.revision = 1;
    value.endpoint = "loopback://" + value.instanceId;
    value.protocol = "loopback";
    value.tags = {"json"};
    return value;
}
} // namespace

int main()
{
    try
    {
        Poco::AutoPtr<DirectoryService> directory = new DirectoryService;
        require(static_cast<bool>(directory->observe(
                    advertisement("orders-a", "runtime-a"))),
                "orders-a advertisement rejected");
        require(static_cast<bool>(directory->observe(
                    advertisement("orders-b", "runtime-b"))),
                "orders-b advertisement rejected");
        Poco::AutoPtr<GovernorService> governor = new GovernorService;

        RuntimeOptions options;
        options.resourceOwner = "test.service-client";
        options.client.maximumAttempts = 2;
        options.client.timeout = 500ms;
        options.client.initialBackoff = 0ms;
        options.client.maximumBackoff = 0ms;
        options.client.circuitFailureThreshold = 1;
        options.client.circuitResetTimeout = 100ms;
        options.client.circuitIdleRetention = 1000ms;
        options.maximumPayloadBytes = 8;
        options.maximumMetadataEntries = 2;
        options.maximumMetadataBytes = 32;
        auto journal = std::make_shared<MemoryJournal>();
        options.invocationJournal = journal;
        std::mutex auditMutex;
        std::vector<InvocationAuditEvent> auditEvents;
        options.auditSink = [&](const InvocationAuditEvent& event) {
            if (event.workId == "audit-sink-error")
                throw std::runtime_error("audit sink failure");
            std::lock_guard<std::mutex> lock(auditMutex);
            auditEvents.push_back(event);
        };
        options.authorizationRequired = true;
        options.authorizer = [](const InvocationAuthorizationRequest& request) {
            if (request.principal == "authorizer-error")
                throw std::runtime_error("authorizer unavailable");
            const bool allowed = request.principal == "orders-reader" &&
                request.serviceName == "orders.v1" &&
                request.operation == "read-order";
            return InvocationAuthorizationDecision{
                allowed,
                allowed ? "CAPABILITY_ALLOWED" : "CAPABILITY_DEFAULT_DENY",
                allowed ? "test allow" : "test deny", 7};
        };
        RuntimeCoordinator coordinator(options, directory, governor);

        std::mutex observedMutex;
        std::map<std::string, std::string> observedInvocationIds;
        std::map<std::string, std::int64_t> observedDeadlines;
        std::promise<void> concurrentStartedPromise;
        auto concurrentStarted = concurrentStartedPromise.get_future().share();
        std::promise<void> concurrentReleasePromise;
        auto concurrentRelease = concurrentReleasePromise.get_future().share();
        std::atomic<bool> concurrentSignalled{false};
        std::atomic<std::uint64_t> concurrentProviderCalls{0};
        ServiceInvocationProvider::Ptr provider = new Provider(
            [&](const ProviderInvocationRequest& request) {
                require(!request.invocationId.empty(),
                        "Provider did not receive invocation ID");
                {
                    std::lock_guard<std::mutex> lock(observedMutex);
                    auto& observed = observedInvocationIds[
                        request.attempt.idempotencyKey];
                    if (observed.empty()) observed = request.invocationId;
                    require(observed == request.invocationId,
                            "Provider attempts used different invocation IDs");
                    auto& deadline = observedDeadlines[
                        request.attempt.idempotencyKey];
                    if (deadline == 0)
                        deadline = request.deadlineUnixMicroseconds;
                    require(deadline == request.deadlineUnixMicroseconds &&
                                deadline >
                                    Poco::Timestamp().epochMicroseconds(),
                            "Provider attempts lost the Runtime deadline");
                }
                require(request.input && request.input->payload.size() == 2,
                        "Provider did not receive shared payload");
                require(request.input->metadata.count("trace") == 1,
                        "Provider did not receive metadata");
                if (request.attempt.idempotencyKey == "concurrent-key")
                {
                    ++concurrentProviderCalls;
                    if (!concurrentSignalled.exchange(true))
                        concurrentStartedPromise.set_value();
                    concurrentRelease.wait();
                    return AttemptResult::success({0x4f, 0x4b});
                }
                if (request.attempt.instance.advertisement.instanceId ==
                    "orders-a")
                    return AttemptResult::retryable(
                        "transport", "first instance unavailable");
                return AttemptResult::success({0x4f, 0x4b});
            });
        require(static_cast<bool>(coordinator.attach(provider)),
                "Runtime Provider attach failed");

        RuntimeInvocationRequest request;
        request.workId = "work-1";
        request.principal = "orders-reader";
        request.invocation.route.serviceName = "orders.v1";
        request.invocation.operation = "read-order";
        request.invocation.idempotencyKey = "request-1";
        request.input.payload = {0x01, 0x02};
        request.input.metadata.emplace("trace", "abc");

        RuntimeInvocationRequest denied = request;
        denied.workId = "work-denied";
        denied.principal = "untrusted-bundle";
        const auto deniedSubmission = coordinator.submit(std::move(denied));
        require(deniedSubmission.admission.status == AdmissionStatus::invalid &&
                    deniedSubmission.completion.wait_for(0ms) ==
                        std::future_status::ready &&
                    deniedSubmission.completion.get().governance.message.find(
                        "CAPABILITY_DEFAULT_DENY") != std::string::npos &&
                    coordinator.snapshot().resourceLane.submitted == 0 &&
                    coordinator.snapshot().resourceLane.accepted == 0,
                "capability-denied invocation consumed ResourceGovernor capacity");

        RuntimeInvocationRequest unavailable = request;
        unavailable.workId = "work-authorizer-error";
        unavailable.principal = "authorizer-error";
        const auto unavailableSubmission = coordinator.submit(
            std::move(unavailable));
        require(unavailableSubmission.admission.status ==
                    AdmissionStatus::invalid &&
                    unavailableSubmission.completion.get().governance.message.find(
                        "SERVICE_CLIENT_AUTHORIZATION_ERROR") !=
                        std::string::npos &&
                    coordinator.snapshot().resourceLane.submitted == 0,
                "authorizer failure did not fail closed before admission");

        auto submission = coordinator.submit(request);
        require(static_cast<bool>(submission),
                "governed invocation was not admitted");
        require(submission.completion.wait_for(2s) == std::future_status::ready,
                "governed invocation did not complete");
        const auto completion = submission.completion.get();
        require(completion.governance.status == CompletionStatus::succeeded &&
                    !submission.invocationId.empty() &&
                    submission.invocationId == completion.invocationId &&
                    completion.invocationId ==
                        observedInvocationIds["request-1"] &&
                    completion.invocation && *completion.invocation &&
                    completion.invocation->attempts == 2 &&
                    completion.invocation->history[0].instanceId == "orders-a" &&
                    completion.invocation->history[1].instanceId == "orders-b",
                "Runtime invocation did not combine governance and failover");
        auto state = coordinator.snapshot();
        require(state.providerRegistry.providers.size() == 1 &&
                    state.providerRegistry.providers[0].dispatched == 2 &&
                    state.resourceLane.succeeded == 1 &&
                    state.authorizationRequired &&
                    state.authorizationAllowed == 1 &&
                    state.authorizationDenied == 1 &&
                    state.authorizationErrors == 1 &&
                    state.auditEnabled &&
                    state.auditEvents >= 12 &&
                    state.auditErrors == 0 &&
                    state.invocationJournal.enabled &&
                    state.invocationJournal.completed == 1,
                "Runtime snapshot did not expose Provider/lane evidence");
        {
            std::lock_guard<std::mutex> lock(auditMutex);
            std::sort(auditEvents.begin(), auditEvents.end(),
                [](const auto& left, const auto& right) {
                    return left.sequence < right.sequence;
                });
            std::vector<InvocationAuditStage> stages;
            std::uint64_t previousSequence = 0;
            for (const auto& event : auditEvents)
            {
                require(event.sequence > previousSequence,
                        "audit event sequence is not monotonic");
                previousSequence = event.sequence;
                if (event.invocationId == submission.invocationId)
                {
                    require(event.serviceName == "orders.v1" &&
                                event.operation == "read-order" &&
                                event.principal == "orders-reader",
                            "audit event lost invocation identity fields");
                    stages.push_back(event.stage);
                }
            }
            for (const auto expected : {
                     InvocationAuditStage::received,
                     InvocationAuditStage::authorizationAllowed,
                     InvocationAuditStage::admitted,
                     InvocationAuditStage::attemptStarted,
                     InvocationAuditStage::attemptCompleted,
                     InvocationAuditStage::completed})
                require(std::find(stages.begin(), stages.end(), expected) !=
                            stages.end(),
                        "governed invocation audit chain is incomplete");
        }

        const auto beforeReplay = coordinator.snapshot();
        RuntimeInvocationRequest replayRequest = request;
        replayRequest.workId = "work-replay";
        replayRequest.input.metadata["tracestate"] = "v=x";
        const auto replaySubmission = coordinator.submit(
            std::move(replayRequest));
        require(replaySubmission.idempotentReplay &&
                    !replaySubmission.idempotentJoined &&
                    replaySubmission.invocationId == submission.invocationId &&
                    replaySubmission.completion.wait_for(0ms) ==
                        std::future_status::ready &&
                    replaySubmission.completion.get().invocation &&
                    coordinator.snapshot().providerRegistry.providers[0]
                            .dispatched ==
                        beforeReplay.providerRegistry.providers[0].dispatched &&
                    coordinator.snapshot().resourceLane.submitted ==
                        beforeReplay.resourceLane.submitted,
                "completed idempotent invocation was executed again");

        RuntimeInvocationRequest conflict = request;
        conflict.workId = "work-idempotency-conflict";
        conflict.input.payload = {0x03, 0x04};
        const auto conflictSubmission = coordinator.submit(
            std::move(conflict));
        require(conflictSubmission.admission.status ==
                    AdmissionStatus::invalid &&
                    conflictSubmission.completion.get().governance.message.find(
                        "SERVICE_CLIENT_IDEMPOTENCY_CONFLICT") !=
                        std::string::npos &&
                    coordinator.snapshot().resourceLane.submitted ==
                        beforeReplay.resourceLane.submitted,
                "same idempotency key with different payload was not rejected");

        RuntimeInvocationRequest concurrent = request;
        concurrent.workId = "work-concurrent-owner";
        concurrent.invocation.idempotencyKey = "concurrent-key";
        const auto concurrentOwner = coordinator.submit(concurrent);
        require(concurrentStarted.wait_for(2s) == std::future_status::ready,
                "concurrent idempotency owner did not reach Provider");
        concurrent.workId = "work-concurrent-join";
        concurrent.input.metadata["tracestate"] = "vendor=value";
        const auto concurrentJoin = coordinator.submit(std::move(concurrent));
        require(concurrentJoin.idempotentJoined &&
                    !concurrentJoin.idempotentReplay &&
                    concurrentJoin.invocationId ==
                        concurrentOwner.invocationId &&
                    concurrentProviderCalls.load() == 1,
                "concurrent duplicate did not join the in-flight invocation");
        concurrentReleasePromise.set_value();
        require(concurrentOwner.completion.wait_for(2s) ==
                    std::future_status::ready &&
                    concurrentJoin.completion.wait_for(0ms) ==
                        std::future_status::ready &&
                    concurrentOwner.completion.get().invocation &&
                    concurrentJoin.completion.get().invocation &&
                    concurrentProviderCalls.load() == 1 &&
                    coordinator.snapshot().idempotencyJoined == 1,
                "joined invocation did not share one completed execution");

        journal->failNextComplete();
        RuntimeInvocationRequest commitFailure = request;
        commitFailure.workId = "work-journal-commit-failure";
        commitFailure.invocation.idempotencyKey = "commit-failure-key";
        const auto commitFailureSubmission = coordinator.submit(commitFailure);
        require(commitFailureSubmission.completion.wait_for(2s) ==
                    std::future_status::ready &&
                    commitFailureSubmission.completion.get().invocation &&
                    coordinator.snapshot().idempotencyErrors == 1,
                "journal commit failure altered the completed business result");
        const auto dispatchesAfterCommitFailure =
            coordinator.snapshot().providerRegistry.providers[0].dispatched;
        commitFailure.workId = "work-journal-fail-closed";
        const auto failClosed = coordinator.submit(commitFailure);
        require(failClosed.admission.status == AdmissionStatus::invalid &&
                    failClosed.completion.get().governance.message.find(
                        "SERVICE_CLIENT_IDEMPOTENCY_INDETERMINATE") !=
                        std::string::npos &&
                    coordinator.snapshot().providerRegistry.providers[0]
                            .dispatched == dispatchesAfterCommitFailure,
                "uncommitted invocation was executed again without explicit recovery");

        commitFailure.workId = "work-journal-explicit-recovery";
        commitFailure.invocation.idempotent = true;
        {
            std::lock_guard<std::mutex> lock(observedMutex);
            observedInvocationIds.erase("commit-failure-key");
        }
        const auto recovered = coordinator.submit(std::move(commitFailure));
        require(static_cast<bool>(recovered) &&
                    recovered.completion.wait_for(2s) ==
                        std::future_status::ready &&
                    recovered.completion.get().invocation &&
                    coordinator.snapshot().idempotencyRecovered == 1,
                "explicitly idempotent request did not recover an indeterminate claim");

        const auto dispatchesBeforeGovernorFailure =
            coordinator.snapshot().providerRegistry.providers[0].dispatched;
        RuntimeInvocationRequest governorFailure = request;
        governorFailure.workId = "governor-throws";
        governorFailure.invocation.idempotencyKey = "governor-failure-key";
        const auto governorRejected = coordinator.submit(governorFailure);
        require(governorRejected.admission.status == AdmissionStatus::invalid &&
                    governorRejected.completion.wait_for(0ms) ==
                        std::future_status::ready &&
                    governorRejected.completion.get().governance.message ==
                        "Service Client ResourceGovernor submission failed" &&
                    coordinator.snapshot().providerRegistry.providers[0]
                            .dispatched == dispatchesBeforeGovernorFailure,
                "ResourceGovernor submit exception escaped or invoked Provider");
        governorFailure.workId = "governor-throws-retry";
        const auto governorRetry = coordinator.submit(
            std::move(governorFailure));
        require(governorRetry.admission.status == AdmissionStatus::invalid &&
                    governorRetry.completion.get().governance.message.find(
                        "SERVICE_CLIENT_IDEMPOTENCY_INDETERMINATE") !=
                        std::string::npos &&
                    coordinator.snapshot().providerRegistry.providers[0]
                            .dispatched == dispatchesBeforeGovernorFailure,
                "ambiguous ResourceGovernor submission was not fail-closed");

        RuntimeInvocationRequest oversized = request;
        oversized.workId = "oversized";
        oversized.input.payload.resize(9);
        const auto rejected = coordinator.submit(std::move(oversized));
        require(rejected.admission.status == AdmissionStatus::invalid &&
                    rejected.completion.wait_for(0ms) ==
                        std::future_status::ready &&
                    !rejected.completion.get().invocation,
                "oversized payload was not rejected before admission");

        RuntimeInvocationRequest auditSinkFailure = request;
        auditSinkFailure.workId = "audit-sink-error";
        auditSinkFailure.input.payload.resize(9);
        require(coordinator.submit(std::move(auditSinkFailure)).admission.status ==
                    AdmissionStatus::invalid &&
                    coordinator.snapshot().auditErrors == 1,
                "audit sink failure altered request rejection semantics");

        require(coordinator.detach("loopback-provider"),
                "Runtime Provider detach failed");
        ServiceInvocationProvider::Ptr throwing = new Provider(
            [](const ProviderInvocationRequest&) -> AttemptResult {
                throw std::runtime_error("provider bug");
            });
        require(static_cast<bool>(coordinator.attach(throwing)),
                "throwing Runtime Provider attach failed");
        RuntimeInvocationRequest providerFailure = request;
        providerFailure.workId = "provider-failure";
        providerFailure.invocation.idempotencyKey = "provider-failure-key";
        const auto failedSubmission = coordinator.submit(
            std::move(providerFailure));
        require(static_cast<bool>(failedSubmission) &&
                    failedSubmission.completion.wait_for(2s) ==
                        std::future_status::ready,
                "Provider failure invocation did not complete");
        const auto failedCompletion = failedSubmission.completion.get();
        require(failedCompletion.governance.status == CompletionStatus::failed &&
                    failedCompletion.invocation,
                "Provider exception did not fail the ResourceGovernor work item");

        coordinator.shutdown();
        RuntimeInvocationRequest stopped = request;
        stopped.workId = "stopped";
        require(coordinator.submit(std::move(stopped)).admission.status ==
                    AdmissionStatus::shuttingDown,
                "stopped coordinator accepted new work");

        std::cout << "SERVICE_CLIENT_RUNTIME_COORDINATOR_PASS attempts="
                  << state.client.attempts
                  << " providerDispatches="
                  << state.providerRegistry.providers[0].dispatched
                  << " laneSucceeded=" << state.resourceLane.succeeded << '\n';
        return 0;
    }
    catch (const std::exception& exception)
    {
        std::cerr << "SERVICE_CLIENT_RUNTIME_COORDINATOR_ERROR: "
                  << exception.what() << '\n';
        return 1;
    }
}
