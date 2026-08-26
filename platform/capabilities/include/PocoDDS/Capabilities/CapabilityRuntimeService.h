#pragma once

#include "PocoDDS/Capabilities/DecisionLease.h"

#include <Poco/AutoPtr.h>
#include <Poco/OSP/Service.h>

namespace PocoDDS::Capabilities
{
class CapabilityRuntimeService : public Poco::OSP::Service
{
public:
    using Ptr = Poco::AutoPtr<CapabilityRuntimeService>;
    static constexpr const char* SERVICE_NAME = "pdr.service.capabilityRuntime";

    virtual PolicySnapshot snapshot() const = 0;
    virtual Decision decide(const Request& request) const = 0;
    virtual void require(const Request& request) const = 0;
    virtual Decision decideLeased(const Request& request) const = 0;
    virtual void requireLeased(const Request& request) const = 0;
    virtual DecisionLeaseSnapshot leases() const = 0;
    virtual ReplaceResult replace(const ReplaceRequest& request) = 0;
    virtual std::vector<AuditRecord> audit(std::size_t limit = 100) const = 0;
    virtual PersistenceSnapshot persistence() const = 0;

    const std::type_info& type() const override { return typeid(CapabilityRuntimeService); }
    bool isA(const std::type_info& other) const override
    {
        return std::string(other.name()) == typeid(CapabilityRuntimeService).name() ||
               Poco::OSP::Service::isA(other);
    }

protected:
    ~CapabilityRuntimeService() override = default;
};
} // namespace PocoDDS::Capabilities
