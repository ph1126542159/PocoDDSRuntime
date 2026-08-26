#pragma once

#include "PocoDDS/ConfigTransaction/ConfigurationParticipantCatalog.h"
#include "PocoDDS/Health/Health.h"

#include <Poco/Types.h>

#include <cstddef>
#include <map>
#include <mutex>
#include <string>

namespace PocoDDS::ConfigTransaction
{
class ParticipantAdmissionState final
{
public:
    static constexpr std::size_t MAX_RETAINED_FAILURES = 128;

    void recordFailure(const std::string& referenceKey,
                       const std::string& participantId,
                       const std::string& code);
    void clear(const std::string& referenceKey);
    void reset();

    [[nodiscard]] ConfigurationParticipantAdmissionSnapshot snapshot() const;
    [[nodiscard]] Health::Report health() const;

private:
    struct Entry
    {
        std::string participantId;
        std::string code;
        Poco::UInt64 observationGeneration{0};
    };

    static std::string safeParticipantId(const std::string& value);
    static std::string safeCode(const std::string& value);
    static std::string safeReferenceKey(const std::string& value);

    mutable std::mutex _mutex;
    Poco::UInt64 _generation{0};
    bool _overflow{false};
    std::map<std::string, Entry> _failures;
};
} // namespace PocoDDS::ConfigTransaction
