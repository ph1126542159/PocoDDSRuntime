#pragma once

#include "PocoDDS/ServiceClient/Client.h"
#include "PocoDDS/ServiceClient/InvocationJournal.h"
#include "PocoDDS/ServiceClient/ProviderRegistry.h"

#include <PocoDDS/ResourceGovernance/ManagedWorkLane.h>
#include <PocoDDS/ServiceDirectory/ServiceDirectoryRuntimeService.h>

#include <cstddef>
#include <cstdint>
#include <functional>
#include <future>
#include <memory>
#include <optional>
#include <string>

namespace PocoDDS::ServiceClient
{
struct InvocationAuthorizationRequest
{
    std::string principal;
    std::string serviceName;
    std::string operation;
};

struct InvocationAuthorizationDecision
{
    bool allowed{false};
    std::string code;
    std::string detail;
    std::uint64_t policyGeneration{0};
};

using InvocationAuthorizer = std::function<InvocationAuthorizationDecision(
    const InvocationAuthorizationRequest&)>;

enum class InvocationAuditStage
{
    received,
    validationRejected,
    authorizationAllowed,
    authorizationDenied,
    authorizationError,
    idempotencyAcquired,
    idempotencyJoined,
    idempotencyReplayed,
    idempotencyRecovered,
    idempotencyConflict,
    idempotencyError,
    admitted,
    admissionRejected,
    attemptStarted,
    attemptCompleted,
    completed
};

struct InvocationAuditEvent
{
    std::uint64_t sequence{0};
    std::int64_t timestampUnixMicroseconds{0};
    std::string invocationId;
    std::string workId;
    std::string principal;
    std::string serviceName;
    std::string operation;
    InvocationAuditStage stage{InvocationAuditStage::received};
    std::string code;
    std::string detail;
    std::size_t attempt{0};
    std::string instanceId;
    std::string runtimeId;
    std::uint64_t runtimeIncarnation{0};
    std::uint64_t policyGeneration{0};
};

using InvocationAuditSink = std::function<void(const InvocationAuditEvent&)>;

PDR_SERVICE_CLIENT_OSP_API const char* toString(
    InvocationAuditStage value) noexcept;

struct RuntimeOptions
{
    Policy client;
    std::string resourceOwner{"pdr.service.serviceClientRuntime"};
    std::size_t maximumProviders{256};
    std::size_t maximumPayloadBytes{1024 * 1024};
    std::size_t maximumMetadataEntries{64};
    std::size_t maximumMetadataBytes{64 * 1024};
    bool authorizationRequired{false};
    InvocationAuthorizer authorizer;
    InvocationAuditSink auditSink;
    InvocationJournal::Ptr invocationJournal;
};

struct RuntimeInvocationRequest
{
    std::string workId;
    // Output-owned internal field: submit() always replaces caller input.
    std::string invocationId;
    std::string principal;
    InvocationRequest invocation;
    InvocationInput input;
};

struct InvocationCompletion
{
    std::string invocationId;
    ResourceGovernance::Completion governance;
    std::optional<InvocationResult> invocation;
};

struct InvocationSubmission
{
    std::string invocationId;
    ResourceGovernance::Admission admission;
    std::shared_future<InvocationCompletion> completion;
    bool idempotentReplay{false};
    bool idempotentJoined{false};

    explicit operator bool() const noexcept
    {
        return admission.status == ResourceGovernance::AdmissionStatus::accepted &&
               completion.valid();
    }
};

struct RuntimeSnapshot
{
    Snapshot client;
    ProviderRegistrySnapshot providerRegistry;
    ResourceGovernance::Snapshot resourceLane;
    std::size_t maximumProviders{0};
    std::size_t maximumPayloadBytes{0};
    std::size_t maximumMetadataEntries{0};
    std::size_t maximumMetadataBytes{0};
    bool authorizationRequired{false};
    std::uint64_t authorizationAllowed{0};
    std::uint64_t authorizationDenied{0};
    std::uint64_t authorizationErrors{0};
    bool auditEnabled{false};
    std::uint64_t auditEvents{0};
    std::uint64_t auditErrors{0};
    InvocationJournalSnapshot invocationJournal;
    std::uint64_t idempotencyJoined{0};
    std::uint64_t idempotencyRecovered{0};
    std::uint64_t idempotencyErrors{0};
};

class PDR_SERVICE_CLIENT_OSP_API RuntimeCoordinator
{
public:
    RuntimeCoordinator(
        RuntimeOptions options,
        ServiceDirectory::ServiceDirectoryRuntimeService::Ptr directory,
        ResourceGovernance::ResourceGovernorService::Ptr governor);
    ~RuntimeCoordinator();

    RuntimeCoordinator(const RuntimeCoordinator&) = delete;
    RuntimeCoordinator& operator=(const RuntimeCoordinator&) = delete;

    ProviderAttachResult attach(ServiceInvocationProvider::Ptr provider);
    bool detach(const std::string& providerId);
    InvocationSubmission submit(RuntimeInvocationRequest request);
    [[nodiscard]] RuntimeSnapshot snapshot() const;
    void shutdown() noexcept;

private:
    class Impl;
    std::unique_ptr<Impl> _impl;
};
} // namespace PocoDDS::ServiceClient
