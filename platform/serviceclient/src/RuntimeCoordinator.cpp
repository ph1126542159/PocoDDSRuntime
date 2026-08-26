#include "PocoDDS/ServiceClient/RuntimeCoordinator.h"

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdint>
#include <future>
#include <mutex>
#include <Poco/DigestEngine.h>
#include <Poco/SHA2Engine.h>
#include <Poco/Timestamp.h>
#include <Poco/UUIDGenerator.h>
#include <sstream>
#include <stdexcept>
#include <unordered_map>
#include <utility>

namespace PocoDDS::ServiceClient
{
const char* toString(InvocationAuditStage value) noexcept
{
    switch (value)
    {
    case InvocationAuditStage::received: return "received";
    case InvocationAuditStage::validationRejected: return "validation-rejected";
    case InvocationAuditStage::authorizationAllowed: return "authorization-allowed";
    case InvocationAuditStage::authorizationDenied: return "authorization-denied";
    case InvocationAuditStage::authorizationError: return "authorization-error";
    case InvocationAuditStage::idempotencyAcquired: return "idempotency-acquired";
    case InvocationAuditStage::idempotencyJoined: return "idempotency-joined";
    case InvocationAuditStage::idempotencyReplayed: return "idempotency-replayed";
    case InvocationAuditStage::idempotencyRecovered: return "idempotency-recovered";
    case InvocationAuditStage::idempotencyConflict: return "idempotency-conflict";
    case InvocationAuditStage::idempotencyError: return "idempotency-error";
    case InvocationAuditStage::admitted: return "admitted";
    case InvocationAuditStage::admissionRejected: return "admission-rejected";
    case InvocationAuditStage::attemptStarted: return "attempt-started";
    case InvocationAuditStage::attemptCompleted: return "attempt-completed";
    case InvocationAuditStage::completed: return "completed";
    }
    return "unknown";
}

const char* toString(InvocationJournalClaimStatus value) noexcept
{
    switch (value)
    {
    case InvocationJournalClaimStatus::acquired: return "acquired";
    case InvocationJournalClaimStatus::replayCompleted: return "replay-completed";
    case InvocationJournalClaimStatus::conflict: return "conflict";
    case InvocationJournalClaimStatus::indeterminate: return "indeterminate";
    case InvocationJournalClaimStatus::capacityExceeded: return "capacity-exceeded";
    }
    return "unknown";
}

namespace
{
bool safeText(const std::string& value, std::size_t maximum, bool required)
{
    if ((required && value.empty()) || value.size() > maximum) return false;
    return std::all_of(value.begin(), value.end(), [](unsigned char character) {
        return character >= 0x21 && character <= 0x7e;
    });
}

bool safeMetadataValue(const std::string& value, std::size_t maximum)
{
    if (value.size() > maximum) return false;
    return std::all_of(value.begin(), value.end(), [](unsigned char character) {
        return character >= 0x20 && character != 0x7f;
    });
}

void digestField(Poco::SHA2Engine& engine, const void* data, std::size_t size)
{
    const auto length = std::to_string(size);
    engine.update(length);
    engine.update(":", 1);
    if (size != 0) engine.update(data, size);
    engine.update(";", 1);
}

void digestField(Poco::SHA2Engine& engine, const std::string& value)
{
    digestField(engine, value.data(), value.size());
}

std::string scopeDigest(const RuntimeInvocationRequest& request)
{
    Poco::SHA2Engine engine(Poco::SHA2Engine::SHA_256);
    digestField(engine, request.principal);
    digestField(engine, request.invocation.route.serviceName);
    digestField(engine, request.invocation.operation);
    digestField(engine, request.invocation.idempotencyKey);
    return Poco::DigestEngine::digestToHex(engine.digest());
}

std::string requestDigest(const RuntimeInvocationRequest& request)
{
    Poco::SHA2Engine engine(Poco::SHA2Engine::SHA_256);
    digestField(engine, request.invocation.route.serviceName);
    digestField(engine, request.invocation.operation);
    digestField(engine, request.input.payload.data(),
                request.input.payload.size());
    for (const auto& [key, value] : request.input.metadata)
    {
        // Correlation context changes between legitimate retries and must not
        // turn the same business request into an idempotency conflict.
        if (key == "traceparent" || key == "tracestate") continue;
        digestField(engine, key);
        digestField(engine, value);
    }
    return Poco::DigestEngine::digestToHex(engine.digest());
}

struct WorkState
{
    RuntimeInvocationRequest request;
    std::shared_ptr<const InvocationInput> input;
    std::mutex mutex;
    std::optional<InvocationResult> invocation;
    bool providerFailure{false};
    std::promise<InvocationCompletion> promise;
    std::promise<void> admissionAuditPromise;
    std::shared_future<void> admissionAudited;
    std::promise<ResourceGovernance::Admission> admissionPromise;
    std::shared_future<ResourceGovernance::Admission> admissionReady;
    std::string journalScopeDigest;
    std::string journalRequestDigest;
    bool journalClaimed{false};
    std::int64_t deadlineUnixMicroseconds{0};
};

struct ActiveInvocation
{
    std::string requestDigest;
    std::string invocationId;
    std::shared_future<ResourceGovernance::Admission> admission;
    std::shared_future<InvocationCompletion> completion;
};
} // namespace

class RuntimeCoordinator::Impl
{
public:
    Impl(RuntimeOptions value,
         ServiceDirectory::ServiceDirectoryRuntimeService::Ptr directory,
         ResourceGovernance::ResourceGovernorService::Ptr governor)
        : options(std::move(value)), directory(std::move(directory)),
          governor(std::move(governor)), providers(options.maximumProviders)
    {
        if (!this->directory || !this->governor)
            throw std::invalid_argument(
                "Service Directory and ResourceGovernor services are required");
        if (!safeText(options.resourceOwner, 128, true))
            throw std::invalid_argument(
                "resourceOwner must contain 1..128 visible ASCII characters");
        if (options.maximumProviders == 0 || options.maximumProviders > 4096 ||
            options.maximumPayloadBytes == 0 ||
            options.maximumPayloadBytes > 16 * 1024 * 1024 ||
            options.maximumMetadataEntries > 256 ||
            options.maximumMetadataBytes == 0 ||
            options.maximumMetadataBytes > 1024 * 1024)
            throw std::invalid_argument("Service Client input limits are invalid");
        if (options.authorizationRequired && !options.authorizer)
            throw std::invalid_argument(
                "Service Client authorization requires an authorizer");
        auto directoryService = this->directory;
        client = std::make_unique<Client>(
            options.client,
            [directoryService](const ServiceDirectory::RouteRequest& request) mutable {
                return directoryService->route(request);
            });
        lane = std::make_unique<ResourceGovernance::ManagedWorkLane>(
            this->governor, options.resourceOwner);
    }

    std::string validate(const RuntimeInvocationRequest& request) const
    {
        if (!safeText(request.workId, 128, true))
            return "workId must contain 1..128 visible ASCII characters";
        if (!safeText(request.invocationId, 128, true))
            return "invocationId must contain 1..128 visible ASCII characters";
        if (options.authorizationRequired &&
            !safeText(request.principal, 128, true))
            return "principal must contain 1..128 visible ASCII characters when authorization is required";
        if (!safeText(request.invocation.route.serviceName, 128, true))
            return "serviceName must contain 1..128 visible ASCII characters";
        if (!safeText(request.invocation.operation, 128, true))
            return "operation must contain 1..128 visible ASCII characters";
        if (!safeText(request.invocation.idempotencyKey, 128, false))
            return "idempotencyKey must contain at most 128 visible ASCII characters";
        if (request.input.payload.size() > options.maximumPayloadBytes)
            return "Invocation payload exceeds configured capacity";
        if (request.input.metadata.size() > options.maximumMetadataEntries)
            return "Invocation metadata entry count exceeds configured capacity";
        std::size_t total = 0;
        for (const auto& [key, value] : request.input.metadata)
        {
            if (!safeText(key, 64, true) || !safeMetadataValue(value, 4096))
                return "Invocation metadata key or value is invalid";
            if (total > options.maximumMetadataBytes ||
                key.size() > options.maximumMetadataBytes - total)
                return "Invocation metadata exceeds configured byte capacity";
            total += key.size();
            if (value.size() > options.maximumMetadataBytes - total)
                return "Invocation metadata exceeds configured byte capacity";
            total += value.size();
        }
        return {};
    }

    InvocationSubmission rejected(ResourceGovernance::AdmissionStatus status,
                                  std::string invocationId,
                                  std::string workId,
                                  std::string detail) const
    {
        if (workId.empty()) workId = "service-client-rejected";
        std::promise<InvocationCompletion> promise;
        auto future = promise.get_future().share();
        InvocationCompletion completion;
        completion.invocationId = invocationId;
        completion.governance = {
            options.resourceOwner, workId,
            ResourceGovernance::CompletionStatus::cancelled, detail,
            std::chrono::microseconds{0}, std::chrono::microseconds{0}};
        promise.set_value(std::move(completion));
        return {std::move(invocationId),
                {status, options.resourceOwner, workId, detail},
                std::move(future), false, false};
    }

    void audit(const RuntimeInvocationRequest& request,
               InvocationAuditStage stage,
               std::string code = {}, std::string detail = {},
               const AttemptContext* attempt = nullptr,
               std::uint64_t policyGeneration = 0) noexcept
    {
        if (!options.auditSink) return;
        InvocationAuditEvent event;
        event.timestampUnixMicroseconds = Poco::Timestamp().epochMicroseconds();
        event.invocationId = safeText(request.invocationId, 128, true)
            ? request.invocationId : std::string{};
        event.workId = safeText(request.workId, 128, true)
            ? request.workId : std::string{};
        event.principal = safeText(request.principal, 128, false)
            ? request.principal : std::string{};
        event.serviceName = safeText(
            request.invocation.route.serviceName, 128, false)
            ? request.invocation.route.serviceName : std::string{};
        event.operation = safeText(request.invocation.operation, 128, false)
            ? request.invocation.operation : std::string{};
        event.stage = stage;
        event.code = safeText(code, 128, false) ? std::move(code) : std::string{};
        event.detail = safeMetadataValue(detail, 512)
            ? std::move(detail) : std::string{};
        event.policyGeneration = policyGeneration;
        if (attempt)
        {
            event.attempt = attempt->attempt;
            event.instanceId = safeText(
                attempt->instance.advertisement.instanceId, 128, false)
                ? attempt->instance.advertisement.instanceId : std::string{};
            event.runtimeId = safeText(
                attempt->instance.advertisement.runtimeId, 128, false)
                ? attempt->instance.advertisement.runtimeId : std::string{};
            event.runtimeIncarnation =
                attempt->instance.advertisement.runtimeIncarnation;
        }
        event.sequence = ++auditSequence;
        try
        {
            options.auditSink(event);
            ++auditEvents;
        }
        catch (...)
        {
            ++auditErrors;
        }
    }

    void forgetActive(const WorkState& state) noexcept
    {
        if (!state.journalClaimed) return;
        std::lock_guard<std::mutex> lock(idempotencyMutex);
        const auto active = activeInvocations.find(state.journalScopeDigest);
        if (active != activeInvocations.end() &&
            active->second.invocationId == state.request.invocationId)
            activeInvocations.erase(active);
    }

    void releaseClaim(const WorkState& state) noexcept
    {
        if (!state.journalClaimed) return;
        try
        {
            options.invocationJournal->release(
                state.journalScopeDigest, state.journalRequestDigest,
                state.request.invocationId);
        }
        catch (...) { ++idempotencyErrors; }
        forgetActive(state);
    }

    RuntimeOptions options;
    ServiceDirectory::ServiceDirectoryRuntimeService::Ptr directory;
    ResourceGovernance::ResourceGovernorService::Ptr governor;
    std::unique_ptr<Client> client;
    ProviderRegistry providers;
    std::unique_ptr<ResourceGovernance::ManagedWorkLane> lane;
    std::atomic<bool> stopping{false};
    std::atomic<std::uint64_t> workSequence{0};
    std::atomic<std::uint64_t> authorizationAllowed{0};
    std::atomic<std::uint64_t> authorizationDenied{0};
    std::atomic<std::uint64_t> authorizationErrors{0};
    std::atomic<std::uint64_t> auditEvents{0};
    std::atomic<std::uint64_t> auditErrors{0};
    std::atomic<std::uint64_t> auditSequence{0};
    std::mutex idempotencyMutex;
    std::unordered_map<std::string, ActiveInvocation> activeInvocations;
    std::atomic<std::uint64_t> idempotencyJoined{0};
    std::atomic<std::uint64_t> idempotencyRecovered{0};
    std::atomic<std::uint64_t> idempotencyErrors{0};
};

RuntimeCoordinator::RuntimeCoordinator(
    RuntimeOptions options,
    ServiceDirectory::ServiceDirectoryRuntimeService::Ptr directory,
    ResourceGovernance::ResourceGovernorService::Ptr governor)
    : _impl(std::make_unique<Impl>(std::move(options), std::move(directory),
                                  std::move(governor)))
{
}

RuntimeCoordinator::~RuntimeCoordinator()
{
    shutdown();
}

ProviderAttachResult RuntimeCoordinator::attach(
    ServiceInvocationProvider::Ptr provider)
{
    if (_impl->stopping.load())
        return {ProviderAttachStatus::closing, "", "",
                "Service Client Runtime is stopping"};
    return _impl->providers.attach(std::move(provider));
}

bool RuntimeCoordinator::detach(const std::string& providerId)
{
    return _impl->providers.detach(providerId);
}

InvocationSubmission RuntimeCoordinator::submit(RuntimeInvocationRequest request)
{
    // Invocation identity is Runtime-owned. Never trust or reuse a caller value,
    // otherwise concurrent callers could merge audit and remote correlation.
    request.invocationId =
        Poco::UUIDGenerator::defaultGenerator().createRandom().toString();
    if (request.workId.empty())
        request.workId = "service-client-" +
            std::to_string(++_impl->workSequence);
    if (_impl->stopping.load())
    {
        _impl->audit(request, InvocationAuditStage::admissionRejected,
                     "SERVICE_CLIENT_STOPPING");
        return _impl->rejected(
            ResourceGovernance::AdmissionStatus::shuttingDown,
            request.invocationId,
            request.workId, "Service Client Runtime is stopping");
    }
    const auto validation = _impl->validate(request);
    if (!validation.empty())
    {
        _impl->audit(request, InvocationAuditStage::validationRejected,
                     "SERVICE_CLIENT_INVALID_REQUEST");
        return _impl->rejected(ResourceGovernance::AdmissionStatus::invalid,
                               request.invocationId, request.workId, validation);
    }

    std::optional<InvocationAuthorizationDecision> authorizationDecision;
    if (_impl->options.authorizationRequired)
    {
        InvocationAuthorizationDecision decision;
        try
        {
            decision = _impl->options.authorizer({
                request.principal,
                request.invocation.route.serviceName,
                request.invocation.operation});
        }
        catch (const std::exception& exception)
        {
            ++_impl->authorizationErrors;
            _impl->audit(request, InvocationAuditStage::received);
            _impl->audit(request, InvocationAuditStage::authorizationError,
                         "SERVICE_CLIENT_AUTHORIZATION_ERROR",
                         "authorizer failed");
            return _impl->rejected(
                ResourceGovernance::AdmissionStatus::invalid,
                request.invocationId,
                request.workId,
                std::string("SERVICE_CLIENT_AUTHORIZATION_ERROR: ") +
                    exception.what());
        }
        catch (...)
        {
            ++_impl->authorizationErrors;
            _impl->audit(request, InvocationAuditStage::received);
            _impl->audit(request, InvocationAuditStage::authorizationError,
                         "SERVICE_CLIENT_AUTHORIZATION_ERROR",
                         "authorizer failed");
            return _impl->rejected(
                ResourceGovernance::AdmissionStatus::invalid,
                request.invocationId,
                request.workId,
                "SERVICE_CLIENT_AUTHORIZATION_ERROR: unknown authorizer failure");
        }
        if (!decision.allowed)
        {
            ++_impl->authorizationDenied;
            _impl->audit(request, InvocationAuditStage::received);
            _impl->audit(request, InvocationAuditStage::authorizationDenied,
                         decision.code, "capability decision denied",
                         nullptr, decision.policyGeneration);
            auto detail = decision.code.empty()
                ? std::string("SERVICE_CLIENT_CAPABILITY_DENIED")
                : decision.code;
            if (!decision.detail.empty()) detail += ": " + decision.detail;
            return _impl->rejected(
                ResourceGovernance::AdmissionStatus::invalid,
                request.invocationId, request.workId, std::move(detail));
        }
        ++_impl->authorizationAllowed;
        authorizationDecision = std::move(decision);
    }

    auto state = std::make_shared<WorkState>();
    auto future = state->promise.get_future().share();
    state->admissionReady = state->admissionPromise.get_future().share();
    state->admissionAudited =
        state->admissionAuditPromise.get_future().share();

    const auto auditPrelude = [&] {
        _impl->audit(request, InvocationAuditStage::received);
        if (authorizationDecision)
            _impl->audit(request,
                         InvocationAuditStage::authorizationAllowed,
                         authorizationDecision->code,
                         "capability decision allowed", nullptr,
                         authorizationDecision->policyGeneration);
    };

    ActiveInvocation joined;
    InvocationJournalClaim journalClaim;
    bool joinedExisting = false;
    bool journalConflict = false;
    bool journalFailure = false;
    bool recoveredIndeterminate = false;
    std::string journalFailureCode;
    std::string journalFailureDetail;
    const bool journalRequested =
        _impl->options.invocationJournal &&
        !request.invocation.idempotencyKey.empty();
    if (journalRequested)
    {
        state->journalScopeDigest = scopeDigest(request);
        state->journalRequestDigest = requestDigest(request);
        std::lock_guard<std::mutex> lock(_impl->idempotencyMutex);
        const auto active = _impl->activeInvocations.find(
            state->journalScopeDigest);
        if (active != _impl->activeInvocations.end())
        {
            if (active->second.requestDigest != state->journalRequestDigest)
                journalConflict = true;
            else
            {
                joined = active->second;
                joinedExisting = true;
            }
        }
        else
        {
            const InvocationJournalClaimRequest claimRequest{
                state->journalScopeDigest, state->journalRequestDigest,
                request.invocationId,
                Poco::Timestamp().epochMicroseconds()};
            try
            {
                journalClaim = _impl->options.invocationJournal->claim(
                    claimRequest);
                if (journalClaim.status ==
                        InvocationJournalClaimStatus::indeterminate &&
                    request.invocation.idempotent)
                {
                    if (!_impl->options.invocationJournal->release(
                            state->journalScopeDigest,
                            state->journalRequestDigest,
                            journalClaim.invocationId))
                        throw std::runtime_error(
                            "indeterminate invocation claim changed during recovery");
                    journalClaim = _impl->options.invocationJournal->claim(
                        claimRequest);
                    recoveredIndeterminate =
                        journalClaim.status ==
                        InvocationJournalClaimStatus::acquired;
                }
            }
            catch (const std::exception&)
            {
                journalFailure = true;
                journalFailureCode = "SERVICE_CLIENT_IDEMPOTENCY_UNAVAILABLE";
                journalFailureDetail = "Invocation journal is unavailable";
                ++_impl->idempotencyErrors;
            }
            catch (...)
            {
                journalFailure = true;
                journalFailureCode = "SERVICE_CLIENT_IDEMPOTENCY_UNAVAILABLE";
                journalFailureDetail = "unknown invocation journal failure";
                ++_impl->idempotencyErrors;
            }

            if (!journalFailure &&
                journalClaim.status == InvocationJournalClaimStatus::acquired)
            {
                state->journalClaimed = true;
                _impl->activeInvocations.emplace(
                    state->journalScopeDigest,
                    ActiveInvocation{state->journalRequestDigest,
                                     request.invocationId,
                                     state->admissionReady, future});
            }
        }
    }

    if (joinedExisting)
    {
        request.invocationId = joined.invocationId;
        auditPrelude();
        _impl->audit(request, InvocationAuditStage::idempotencyJoined,
                     "SERVICE_CLIENT_IDEMPOTENCY_JOINED");
        ++_impl->idempotencyJoined;
        try
        {
            return {request.invocationId, joined.admission.get(),
                    joined.completion, false, true};
        }
        catch (...)
        {
            ++_impl->idempotencyErrors;
            _impl->audit(request, InvocationAuditStage::idempotencyError,
                         "SERVICE_CLIENT_IDEMPOTENCY_JOIN_FAILED", "rejected");
            return _impl->rejected(
                ResourceGovernance::AdmissionStatus::invalid,
                request.invocationId, request.workId,
                "SERVICE_CLIENT_IDEMPOTENCY_JOIN_FAILED: active submission state is unavailable");
        }
    }

    if (journalConflict ||
        (!journalFailure && journalRequested &&
         journalClaim.status == InvocationJournalClaimStatus::conflict))
    {
        auditPrelude();
        _impl->audit(request, InvocationAuditStage::idempotencyConflict,
                     "SERVICE_CLIENT_IDEMPOTENCY_CONFLICT",
                     "same key was used for a different request");
        return _impl->rejected(
            ResourceGovernance::AdmissionStatus::invalid,
            request.invocationId, request.workId,
            "SERVICE_CLIENT_IDEMPOTENCY_CONFLICT: same key was used for a different request");
    }

    if (!journalFailure && journalRequested &&
        journalClaim.status == InvocationJournalClaimStatus::replayCompleted)
    {
        if (!journalClaim.completion)
        {
            journalFailure = true;
            journalFailureCode = "SERVICE_CLIENT_IDEMPOTENCY_INVALID_REPLAY";
            journalFailureDetail = "Journal replay did not include a completion";
            ++_impl->idempotencyErrors;
        }
        else
        {
            request.invocationId = journalClaim.invocationId;
            auditPrelude();
            _impl->audit(request, InvocationAuditStage::idempotencyReplayed,
                         "SERVICE_CLIENT_IDEMPOTENCY_REPLAYED");
            std::promise<InvocationCompletion> replayPromise;
            auto replayFuture = replayPromise.get_future().share();
            auto replay = *journalClaim.completion;
            const auto code = replay.invocation &&
                                      !replay.invocation->code.empty()
                ? replay.invocation->code
                : std::string(replay.invocation
                    ? toString(replay.invocation->status)
                    : "SERVICE_CLIENT_GOVERNANCE_COMPLETION");
            const auto status = replay.invocation
                ? std::string(toString(replay.invocation->status))
                : std::string(ResourceGovernance::toString(
                    replay.governance.status));
            _impl->audit(request, InvocationAuditStage::completed,
                         code, status);
            replayPromise.set_value(std::move(replay));
            return {request.invocationId,
                    {ResourceGovernance::AdmissionStatus::accepted,
                     _impl->options.resourceOwner, request.workId,
                     "idempotent replay"},
                    std::move(replayFuture), true, false};
        }
    }

    if (!journalFailure && journalRequested &&
        journalClaim.status == InvocationJournalClaimStatus::indeterminate)
    {
        journalFailure = true;
        journalFailureCode = "SERVICE_CLIENT_IDEMPOTENCY_INDETERMINATE";
        journalFailureDetail =
            "a prior Runtime stopped before the invocation completion was journaled";
    }
    if (!journalFailure && journalRequested &&
        journalClaim.status == InvocationJournalClaimStatus::capacityExceeded)
    {
        journalFailure = true;
        journalFailureCode = "SERVICE_CLIENT_IDEMPOTENCY_CAPACITY_EXCEEDED";
        journalFailureDetail = journalClaim.detail.empty()
            ? "Invocation journal capacity is exhausted"
            : journalClaim.detail;
    }
    if (journalFailure)
    {
        auditPrelude();
        _impl->audit(request, InvocationAuditStage::idempotencyError,
                     journalFailureCode, "rejected");
        return _impl->rejected(
            journalFailureCode ==
                    "SERVICE_CLIENT_IDEMPOTENCY_CAPACITY_EXCEEDED"
                ? ResourceGovernance::AdmissionStatus::queueFull
                : ResourceGovernance::AdmissionStatus::invalid,
            request.invocationId, request.workId,
            journalFailureCode + ": " + journalFailureDetail);
    }

    auditPrelude();
    if (state->journalClaimed)
    {
        _impl->audit(request,
                     recoveredIndeterminate
                         ? InvocationAuditStage::idempotencyRecovered
                         : InvocationAuditStage::idempotencyAcquired,
                     recoveredIndeterminate
                         ? "SERVICE_CLIENT_IDEMPOTENCY_RECOVERED"
                         : "SERVICE_CLIENT_IDEMPOTENCY_ACQUIRED");
        if (recoveredIndeterminate) ++_impl->idempotencyRecovered;
    }

    state->input = std::make_shared<const InvocationInput>(
        std::move(request.input));
    state->request = std::move(request);

    ResourceGovernance::WorkItem work;
    work.id = state->request.workId;
    work.run = [this, state](const ResourceGovernance::CancellationToken& token) {
        state->admissionAudited.wait();
        state->deadlineUnixMicroseconds =
            Poco::Timestamp().epochMicroseconds() +
            std::chrono::duration_cast<std::chrono::microseconds>(
                _impl->options.client.timeout).count();
        const auto cancelled = [token] { return token.requested(); };
        auto result = _impl->client->invoke(
            state->request.invocation,
            [this, state, cancelled](const AttemptContext& attempt) {
                _impl->audit(state->request,
                             InvocationAuditStage::attemptStarted,
                             {}, {}, &attempt);
                ProviderInvocationRequest providerRequest;
                providerRequest.invocationId = state->request.invocationId;
                providerRequest.deadlineUnixMicroseconds =
                    state->deadlineUnixMicroseconds;
                providerRequest.attempt = attempt;
                providerRequest.input = state->input;
                providerRequest.cancellationRequested = cancelled;
                auto dispatched = _impl->providers.dispatch(providerRequest);
                _impl->audit(state->request,
                             InvocationAuditStage::attemptCompleted,
                             dispatched.result.code, {}, &attempt);
                if (dispatched.status ==
                    ProviderDispatchStatus::providerFailure)
                {
                    std::lock_guard<std::mutex> lock(state->mutex);
                    state->providerFailure = true;
                }
                return std::move(dispatched.result);
            }, cancelled);
        bool providerFailure = false;
        {
            std::lock_guard<std::mutex> lock(state->mutex);
            state->invocation = std::move(result);
            providerFailure = state->providerFailure;
        }
        if (providerFailure)
            throw std::runtime_error(
                "An invocation Provider threw during governed execution");
    };
    work.complete = [this, state](
        const ResourceGovernance::Completion& completion) {
        InvocationCompletion result;
        result.invocationId = state->request.invocationId;
        result.governance = completion;
        {
            std::lock_guard<std::mutex> lock(state->mutex);
            result.invocation = std::move(state->invocation);
        }
        const auto code = result.invocation &&
                                  !result.invocation->code.empty()
            ? result.invocation->code
            : std::string(result.invocation
                ? toString(result.invocation->status)
                : "SERVICE_CLIENT_GOVERNANCE_COMPLETION");
        const auto status = result.invocation
            ? std::string(toString(result.invocation->status))
            : std::string(ResourceGovernance::toString(completion.status));
        if (state->journalClaimed)
        {
            try
            {
                _impl->options.invocationJournal->complete(
                    state->journalScopeDigest,
                    state->journalRequestDigest,
                    state->request.invocationId, result,
                    Poco::Timestamp().epochMicroseconds());
            }
            catch (...)
            {
                ++_impl->idempotencyErrors;
                _impl->audit(state->request,
                             InvocationAuditStage::idempotencyError,
                             "SERVICE_CLIENT_IDEMPOTENCY_COMMIT_FAILED",
                             "completion-persistence-failed");
            }
            _impl->forgetActive(*state);
        }
        _impl->audit(state->request, InvocationAuditStage::completed,
                     code, status);
        try { state->promise.set_value(std::move(result)); }
        catch (...) {}
    };
    ResourceGovernance::Admission admission;
    try
    {
        admission = _impl->lane->submit(std::move(work));
    }
    catch (...)
    {
        admission = {ResourceGovernance::AdmissionStatus::invalid,
                     _impl->options.resourceOwner, state->request.workId,
                     "Service Client ResourceGovernor submission failed"};
        try { state->admissionPromise.set_value(admission); }
        catch (...) {}
        _impl->audit(state->request,
                     InvocationAuditStage::admissionRejected,
                     "SERVICE_CLIENT_GOVERNOR_SUBMIT_FAILED");
        // submit() threw at an ambiguous external boundary. Keep the durable
        // claim in-flight so a duplicate cannot execute unless the caller has
        // explicitly declared recovery safe.
        _impl->forgetActive(*state);
        InvocationCompletion completion;
        completion.invocationId = state->request.invocationId;
        completion.governance = {
            _impl->options.resourceOwner, state->request.workId,
            ResourceGovernance::CompletionStatus::cancelled,
            admission.message, std::chrono::microseconds{0},
            std::chrono::microseconds{0}};
        try { state->promise.set_value(std::move(completion)); }
        catch (...) {}
        try { state->admissionAuditPromise.set_value(); }
        catch (...) {}
        return {state->request.invocationId, std::move(admission),
                std::move(future), false, false};
    }
    try { state->admissionPromise.set_value(admission); }
    catch (...) {}
    if (admission.status == ResourceGovernance::AdmissionStatus::accepted)
        _impl->audit(state->request, InvocationAuditStage::admitted);
    else
    {
        _impl->audit(state->request,
                     InvocationAuditStage::admissionRejected,
                     "SERVICE_CLIENT_ADMISSION_REJECTED");
        InvocationCompletion completion;
        completion.invocationId = state->request.invocationId;
        completion.governance = {
            _impl->options.resourceOwner, state->request.workId,
            admission.status == ResourceGovernance::AdmissionStatus::circuitOpen
                ? ResourceGovernance::CompletionStatus::circuitOpen
                : ResourceGovernance::CompletionStatus::cancelled,
            admission.message, std::chrono::microseconds{0},
            std::chrono::microseconds{0}};
        if (state->journalClaimed)
            _impl->releaseClaim(*state);
        try { state->promise.set_value(std::move(completion)); }
        catch (...) {}
    }
    try { state->admissionAuditPromise.set_value(); }
    catch (...) {}
    return {state->request.invocationId, std::move(admission),
            std::move(future), false, false};
}

RuntimeSnapshot RuntimeCoordinator::snapshot() const
{
    InvocationJournalSnapshot journal;
    if (_impl->options.invocationJournal)
    {
        try
        {
            journal = _impl->options.invocationJournal->snapshot();
        }
        catch (const std::exception& exception)
        {
            journal.enabled = true;
            journal.healthy = false;
            journal.backend = "unavailable";
            journal.lastError = exception.what();
            ++_impl->idempotencyErrors;
        }
        catch (...)
        {
            journal.enabled = true;
            journal.healthy = false;
            journal.backend = "unavailable";
            journal.lastError = "unknown invocation journal failure";
            ++_impl->idempotencyErrors;
        }
    }
    return {_impl->client->snapshot(), _impl->providers.snapshot(),
            _impl->governor->snapshot(_impl->options.resourceOwner),
            _impl->options.maximumProviders,
            _impl->options.maximumPayloadBytes,
            _impl->options.maximumMetadataEntries,
            _impl->options.maximumMetadataBytes,
            _impl->options.authorizationRequired,
            _impl->authorizationAllowed.load(),
            _impl->authorizationDenied.load(),
            _impl->authorizationErrors.load(),
            static_cast<bool>(_impl->options.auditSink),
            _impl->auditEvents.load(),
            _impl->auditErrors.load(),
            std::move(journal),
            _impl->idempotencyJoined.load(),
            _impl->idempotencyRecovered.load(),
            _impl->idempotencyErrors.load()};
}

void RuntimeCoordinator::shutdown() noexcept
{
    if (!_impl || _impl->stopping.exchange(true)) return;
    if (_impl->lane) _impl->lane->closeAndWait();
    try { _impl->providers.closeAndWait(); }
    catch (...) {}
}
} // namespace PocoDDS::ServiceClient
