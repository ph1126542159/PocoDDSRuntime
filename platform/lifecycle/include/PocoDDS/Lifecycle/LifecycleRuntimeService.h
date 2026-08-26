#pragma once

#include "PocoDDS/Lifecycle/DrainParticipantService.h"
#include "PocoDDS/Lifecycle/Maintenance.h"

#include <Poco/AutoPtr.h>
#include <Poco/OSP/Service.h>

#include <chrono>
#include <string>
#include <typeinfo>
#include <vector>

namespace PocoDDS::Lifecycle
{
struct DrainParticipantSnapshot
{
    std::string owner;
    DrainSnapshot drain;
};

class LifecycleRuntimeService : public Poco::OSP::Service
{
public:
    using Ptr = Poco::AutoPtr<LifecycleRuntimeService>;
    static constexpr const char* SERVICE_NAME = "pdr.service.lifecycleRuntime";

    virtual MaintenanceOperation drain(
        const std::string& target,
        std::chrono::milliseconds timeout,
        const std::string& requestId) = 0;
    virtual MaintenanceOperation restore(
        const std::string& planId,
        const std::string& requestId) = 0;
    virtual MaintenanceOperation recover(
        const std::string& planId,
        const std::string& requestId) = 0;
    virtual std::vector<MaintenancePlan> plans() const = 0;
    virtual std::vector<DrainParticipantSnapshot> participants() const = 0;

    const std::type_info& type() const override
    {
        return typeid(LifecycleRuntimeService);
    }

    bool isA(const std::type_info& other) const override
    {
        return std::string(other.name()) == typeid(LifecycleRuntimeService).name() ||
               Poco::OSP::Service::isA(other);
    }

protected:
    ~LifecycleRuntimeService() override = default;
};
} // namespace PocoDDS::Lifecycle
