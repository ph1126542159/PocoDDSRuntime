#pragma once

#include "PocoDDS/ConfigTransaction/ConfigTransaction.h"

#include <Poco/AutoPtr.h>
#include <Poco/OSP/Service.h>

#include <string>
#include <typeinfo>

namespace PocoDDS::ConfigTransaction
{
class ConfigurationRuntimeService : public Poco::OSP::Service
{
public:
    using Ptr = Poco::AutoPtr<ConfigurationRuntimeService>;
    static constexpr const char* SERVICE_NAME = "pdr.service.configurationRuntime";

    virtual Snapshot current() const = 0;
    virtual ApplyResult apply(const ApplyRequest& request) = 0;
    virtual std::vector<TransactionSummary> history(std::size_t limit = 50) const = 0;
    virtual std::vector<std::string> participantIds() const = 0;
    virtual std::size_t recover() = 0;

    const std::type_info& type() const override
    {
        return typeid(ConfigurationRuntimeService);
    }

    bool isA(const std::type_info& other) const override
    {
        return std::string(other.name()) == typeid(ConfigurationRuntimeService).name() ||
               Poco::OSP::Service::isA(other);
    }

protected:
    ~ConfigurationRuntimeService() override = default;
};
} // namespace PocoDDS::ConfigTransaction
