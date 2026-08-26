#pragma once

#include "PocoDDS/Membership/Membership.h"

#include <Poco/AutoPtr.h>
#include <Poco/OSP/Service.h>

#include <typeinfo>

namespace PocoDDS::Membership
{
class MembershipRuntimeService : public Poco::OSP::Service
{
public:
    using Ptr = Poco::AutoPtr<MembershipRuntimeService>;
    static constexpr const char* SERVICE_NAME = "pdr.service.membershipRuntime";

    virtual ObservationResult observe(Heartbeat heartbeat) = 0;
    virtual bool leave(const std::string& instanceId, std::uint64_t incarnation,
                       std::uint64_t finalSequence) = 0;
    virtual Snapshot snapshot() const = 0;

    const std::type_info& type() const override
    {
        return typeid(MembershipRuntimeService);
    }

    bool isA(const std::type_info& other) const override
    {
        return std::string(other.name()) == typeid(MembershipRuntimeService).name() ||
               Poco::OSP::Service::isA(other);
    }

protected:
    ~MembershipRuntimeService() override = default;
};
} // namespace PocoDDS::Membership
