#pragma once

#include "PocoDDS/ServiceClient/Export.h"

#include <cstddef>
#include <cstdint>
#include <memory>
#include <string>

namespace PocoDDS::ServiceClient
{
struct InvocationCompletion;

enum class InvocationJournalClaimStatus
{
    acquired,
    replayCompleted,
    conflict,
    indeterminate,
    capacityExceeded
};

PDR_SERVICE_CLIENT_OSP_API const char* toString(
    InvocationJournalClaimStatus value) noexcept;

/// Only digests cross the persistence boundary. A Journal never receives the
/// Principal, idempotency key, request payload, metadata or target endpoint.
struct InvocationJournalClaimRequest
{
    std::string scopeDigest;
    std::string requestDigest;
    std::string invocationId;
    std::int64_t nowUnixMicroseconds{0};
};

struct InvocationJournalClaim
{
    InvocationJournalClaimStatus status{
        InvocationJournalClaimStatus::capacityExceeded};
    std::string invocationId;
    std::shared_ptr<const InvocationCompletion> completion;
    std::string detail;

    explicit operator bool() const noexcept
    {
        return status == InvocationJournalClaimStatus::acquired;
    }
};

struct InvocationJournalSnapshot
{
    bool enabled{false};
    bool durable{false};
    bool healthy{true};
    std::string backend{"disabled"};
    std::size_t maximumEntries{0};
    std::size_t entries{0};
    std::size_t inFlight{0};
    std::size_t completed{0};
    std::uint64_t claims{0};
    std::uint64_t replays{0};
    std::uint64_t conflicts{0};
    std::uint64_t indeterminate{0};
    std::uint64_t capacityRejected{0};
    std::uint64_t errors{0};
    std::string lastError;
};

/// Pluggable idempotency persistence boundary. claim() must atomically create
/// an in-flight record or return the existing state for the scope digest.
class PDR_SERVICE_CLIENT_OSP_API InvocationJournal
{
public:
    using Ptr = std::shared_ptr<InvocationJournal>;
    virtual ~InvocationJournal() = default;

    virtual InvocationJournalClaim claim(
        const InvocationJournalClaimRequest& request) = 0;

    virtual void complete(
        const std::string& scopeDigest,
        const std::string& requestDigest,
        const std::string& invocationId,
        const InvocationCompletion& completion,
        std::int64_t nowUnixMicroseconds) = 0;

    /// Releases a matching in-flight claim that was never admitted or that an
    /// explicitly idempotent caller chose to recover after a prior crash.
    virtual bool release(
        const std::string& scopeDigest,
        const std::string& requestDigest,
        const std::string& invocationId) = 0;

    virtual InvocationJournalSnapshot snapshot() const = 0;
};
} // namespace PocoDDS::ServiceClient
