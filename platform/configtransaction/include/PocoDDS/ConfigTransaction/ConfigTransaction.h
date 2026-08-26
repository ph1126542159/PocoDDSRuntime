#pragma once

#include "PocoDDS/ConfigTransaction/Export.h"

#include <Poco/Types.h>

#include <map>
#include <string>
#include <vector>

namespace PocoDDS::ConfigTransaction
{
using Values = std::map<std::string, std::string>;

struct Snapshot
{
    Poco::UInt64 generation{0};
    std::string digest;
    Values values;
    Poco::Int64 committedMicroseconds{0};
};

enum class Status
{
    preflighting,
    preflightFailed,
    committing,
    rollingBack,
    rolledBack,
    rollbackFailed,
    committed,
    recoveryPending
};

PDR_CONFIG_TRANSACTION_API const char* statusName(Status status) noexcept;
PDR_CONFIG_TRANSACTION_API Status parseStatus(const std::string& value);
PDR_CONFIG_TRANSACTION_API std::string snapshotDigest(const Values& values);
PDR_CONFIG_TRANSACTION_API bool sensitiveKey(const std::string& key);
PDR_CONFIG_TRANSACTION_API bool environmentReference(const std::string& value);
PDR_CONFIG_TRANSACTION_API bool sensitiveValueAllowed(const std::string& key,
                                                       const std::string& value);

struct ParticipantDescriptor
{
    std::string id;
    std::vector<std::string> ownedPrefixes;
    std::vector<std::string> after;
};

struct Context
{
    std::string transactionId;
    std::string requestId;
    Snapshot previous;
    Snapshot candidate;
    std::vector<std::string> changedKeys;
    std::string principal;
};

struct ParticipantResult
{
    bool success{true};
    std::string code;
    std::string message;

    static ParticipantResult accepted() { return {}; }
    static ParticipantResult rejected(std::string code, std::string message)
    {
        return {false, std::move(code), std::move(message)};
    }
};

struct ApplyRequest
{
    std::string requestId;
    Poco::UInt64 expectedGeneration{0};
    Values candidate;
    std::string principal;
    // Optional digest of the caller's stable patch/input representation.
    // When empty, candidate.digest remains the idempotency identity.
    std::string inputDigest;
};

struct ApplyResult
{
    std::string transactionId;
    Status status{Status::preflighting};
    Snapshot snapshot;
    std::vector<std::string> changedKeys;
    std::vector<std::string> participants;
    std::string errorCode;
    std::string errorMessage;
    bool idempotentReplay{false};
    bool rolledBack{false};
};

struct TransactionRecord
{
    std::string id;
    std::string requestId;
    std::string inputDigest;
    std::string principal;
    Status status{Status::preflighting};
    Snapshot previous;
    Snapshot candidate;
    std::vector<std::string> changedKeys;
    std::vector<std::string> participants;
    std::vector<std::string> commitAttempted;
    std::vector<std::string> committedParticipants;
    std::string errorCode;
    std::string errorMessage;
    Poco::Int64 createdMicroseconds{0};
    Poco::Int64 updatedMicroseconds{0};
};

struct TransactionSummary
{
    std::string id;
    std::string requestId;
    std::string principal;
    Status status{Status::preflighting};
    Poco::UInt64 previousGeneration{0};
    Poco::UInt64 candidateGeneration{0};
    std::string candidateDigest;
    std::vector<std::string> changedKeys;
    std::vector<std::string> participants;
    std::string errorCode;
    std::string errorMessage;
    Poco::Int64 createdMicroseconds{0};
    Poco::Int64 updatedMicroseconds{0};
};

PDR_CONFIG_TRANSACTION_API TransactionSummary summarize(const TransactionRecord& record);
} // namespace PocoDDS::ConfigTransaction
