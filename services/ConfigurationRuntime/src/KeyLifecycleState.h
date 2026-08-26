#pragma once

#include "ParticipantExpectationState.h"

#include "PocoDDS/ConfigTransaction/ConfigurationParticipantCatalog.h"
#include "PocoDDS/Health/Health.h"

#include <Poco/Types.h>

#include <mutex>
#include <string>
#include <vector>

namespace PocoDDS::ConfigTransaction
{
struct KeyLifecycleDocument
{
    std::string owner;
    bool ownerActive{false};
    std::string json;
};

struct KeyLifecycleEntry
{
    std::string owner;
    bool ownerActive{false};
    std::string id;
    std::string participantId;
    std::string operation;
    std::string sourceKey;
    std::string replacementKey;
    std::string deprecatedSince;
    std::string removalAllowedFrom;
    std::string status;
    std::string code;
};

struct KeyLifecycleIssue
{
    std::string owner;
    std::string code;
    bool blocking{false};
};

struct KeyLifecycleSnapshot
{
    Poco::UInt64 generation{0};
    bool ready{true};
    std::size_t declarationCount{0};
    std::vector<KeyLifecycleEntry> entries;
    std::vector<KeyLifecycleIssue> issues;
};

class KeyLifecycleState final
{
public:
    static constexpr std::size_t MAXIMUM_DOCUMENT_BYTES = 64 * 1024;
    static constexpr std::size_t MAXIMUM_ENTRIES = 1024;

    void replace(
        const std::vector<KeyLifecycleDocument>& documents,
        const ConfigurationParticipantCatalogSnapshot& catalog,
        const std::vector<AdmittedParticipantObservation>& observations,
        const std::string& runtimeVersion);
    void reset();

    [[nodiscard]] KeyLifecycleSnapshot snapshot() const;
    [[nodiscard]] Health::Report health() const;

private:
    mutable std::mutex _mutex;
    KeyLifecycleSnapshot _snapshot;
};
} // namespace PocoDDS::ConfigTransaction
