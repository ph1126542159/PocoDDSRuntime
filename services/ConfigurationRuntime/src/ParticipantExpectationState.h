#pragma once

#include "PocoDDS/ConfigTransaction/ConfigurationParticipantCatalog.h"
#include "PocoDDS/Health/Health.h"

#include <Poco/Types.h>

#include <mutex>
#include <string>
#include <vector>

namespace PocoDDS::ConfigTransaction
{
struct ParticipantDeclarationDocument
{
    std::string owner;
    bool ownerActive{false};
    std::string json;
};

struct AdmittedParticipantObservation
{
    std::string id;
    std::string owner;
    std::string serviceName;
};

class ParticipantExpectationState final
{
public:
    static constexpr std::size_t MAXIMUM_DOCUMENT_BYTES = 64 * 1024;
    static constexpr std::size_t MAXIMUM_DECLARATIONS = 1024;

    void replace(
        const std::vector<ParticipantDeclarationDocument>& documents,
        const ConfigurationParticipantCatalogSnapshot& catalog,
        const std::vector<AdmittedParticipantObservation>& observations);
    void reset();

    [[nodiscard]] ConfigurationParticipantExpectationSnapshot snapshot() const;
    [[nodiscard]] Health::Report health() const;

private:
    mutable std::mutex _mutex;
    ConfigurationParticipantExpectationSnapshot _snapshot;
};
} // namespace PocoDDS::ConfigTransaction
