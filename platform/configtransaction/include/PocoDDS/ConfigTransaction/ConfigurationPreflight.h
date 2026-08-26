#pragma once

#include "PocoDDS/ConfigTransaction/ConfigTransaction.h"

#include <Poco/AutoPtr.h>
#include <Poco/OSP/Service.h>

#include <string>
#include <typeinfo>
#include <vector>

namespace PocoDDS::ConfigTransaction
{
class TransactionEngine;

struct ConfigurationPreflightRequest
{
    std::string requestId;
    Poco::UInt64 expectedGeneration{0};
    Values candidate;
    std::string principal;
};

struct ConfigurationPreflightResult
{
    std::string preflightId;
    bool accepted{false};
    bool changed{false};
    Poco::UInt64 expectedGeneration{0};
    Poco::UInt64 observedGeneration{0};
    Poco::UInt64 candidateGeneration{0};
    std::string candidateDigest;
    std::vector<std::string> changedKeys;
    std::vector<std::string> participants;
    std::string errorCode;
    std::string errorMessage;
};

PDR_CONFIG_TRANSACTION_API ConfigurationPreflightResult
preflightConfigurationTransaction(
    TransactionEngine& engine,
    const ConfigurationPreflightRequest& request);

class ConfigurationPreflightRuntimeService : public Poco::OSP::Service
{
public:
    using Ptr = Poco::AutoPtr<ConfigurationPreflightRuntimeService>;
    static constexpr const char* SERVICE_NAME =
        "pdr.service.configurationPreflightRuntime";

    virtual ConfigurationPreflightResult preflight(
        const ConfigurationPreflightRequest& request) = 0;

    const std::type_info& type() const override
    {
        return typeid(ConfigurationPreflightRuntimeService);
    }

    bool isA(const std::type_info& other) const override
    {
        return std::string(other.name()) ==
                   typeid(ConfigurationPreflightRuntimeService).name() ||
               Poco::OSP::Service::isA(other);
    }

protected:
    ~ConfigurationPreflightRuntimeService() override = default;
};
} // namespace PocoDDS::ConfigTransaction
