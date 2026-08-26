#pragma once

#include "PocoDDS/ConfigTransaction/Export.h"

#include <Poco/AutoPtr.h>
#include <Poco/OSP/Service.h>
#include <Poco/Types.h>

#include <string>
#include <typeinfo>
#include <vector>

namespace PocoDDS::ConfigTransaction
{
class TransactionEngine;

struct ConfigurationParticipantCatalogEntry
{
    std::string id;
    std::vector<std::string> ownedPrefixes;
    std::vector<std::string> after;
    std::vector<std::string> unresolvedAfter;
    Poco::UInt64 registrationGeneration{0};
};

struct ConfigurationParticipantCatalogSnapshot
{
    Poco::UInt64 generation{0};
    std::string digest;
    std::vector<ConfigurationParticipantCatalogEntry> participants;
};

struct ConfigurationParticipantAdmissionFailure
{
    std::string participantId;
    std::string code;
    Poco::UInt64 observationGeneration{0};
};

struct ConfigurationParticipantAdmissionSnapshot
{
    Poco::UInt64 generation{0};
    bool overflow{false};
    std::vector<ConfigurationParticipantAdmissionFailure> rejectedParticipants;
};

struct ConfigurationParticipantExpectation
{
    std::string owner;
    std::string id;
    std::string serviceName;
    bool ownerActive{false};
    std::string status;
    std::string code;
};

struct ConfigurationParticipantExpectationIssue
{
    std::string owner;
    std::string code;
};

struct ConfigurationParticipantExpectationSnapshot
{
    Poco::UInt64 generation{0};
    bool ready{true};
    std::vector<ConfigurationParticipantExpectation> expectations;
    std::vector<ConfigurationParticipantExpectationIssue> issues;
};

PDR_CONFIG_TRANSACTION_API ConfigurationParticipantCatalogSnapshot
configurationParticipantCatalog(const TransactionEngine& engine);

class ConfigurationParticipantCatalogRuntimeService : public Poco::OSP::Service
{
public:
    using Ptr = Poco::AutoPtr<ConfigurationParticipantCatalogRuntimeService>;
    static constexpr const char* SERVICE_NAME =
        "pdr.service.configurationParticipantCatalogRuntime";

    virtual ConfigurationParticipantCatalogSnapshot snapshot() const = 0;
    virtual ConfigurationParticipantAdmissionSnapshot admission() const = 0;
    virtual ConfigurationParticipantExpectationSnapshot expectations() const = 0;

    const std::type_info& type() const override
    {
        return typeid(ConfigurationParticipantCatalogRuntimeService);
    }

    bool isA(const std::type_info& other) const override
    {
        return std::string(other.name()) ==
                   typeid(ConfigurationParticipantCatalogRuntimeService).name() ||
               Poco::OSP::Service::isA(other);
    }

protected:
    ~ConfigurationParticipantCatalogRuntimeService() override = default;
};
} // namespace PocoDDS::ConfigTransaction
