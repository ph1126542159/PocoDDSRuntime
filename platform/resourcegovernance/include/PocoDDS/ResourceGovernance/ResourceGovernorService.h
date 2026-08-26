#pragma once

#include "PocoDDS/ResourceGovernance/ResourceGovernor.h"

#include <Poco/AutoPtr.h>
#include <Poco/OSP/Service.h>

#include <string>
#include <typeinfo>
#include <vector>

namespace PocoDDS::ResourceGovernance
{
class ResourceGovernorService : public Poco::OSP::Service
{
public:
    using Ptr = Poco::AutoPtr<ResourceGovernorService>;
    static constexpr const char* SERVICE_NAME = "pdr.service.resourceGovernor";

    virtual Admission submit(const std::string& owner, WorkItem item) = 0;
    virtual Snapshot snapshot(const std::string& owner) const = 0;
    virtual std::vector<Snapshot> snapshots() const = 0;

    const std::type_info& type() const override
    {
        return typeid(ResourceGovernorService);
    }

    bool isA(const std::type_info& other) const override
    {
        return std::string(other.name()) == typeid(ResourceGovernorService).name() ||
               Poco::OSP::Service::isA(other);
    }

protected:
    ~ResourceGovernorService() override = default;
};
} // namespace PocoDDS::ResourceGovernance
