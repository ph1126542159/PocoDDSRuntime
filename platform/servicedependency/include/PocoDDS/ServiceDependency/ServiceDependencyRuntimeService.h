#pragma once

#include "PocoDDS/ServiceDependency/ServiceDependency.h"

#include <Poco/AutoPtr.h>
#include <Poco/OSP/Service.h>

#include <string>
#include <typeinfo>

namespace PocoDDS::ServiceDependency
{
class ServiceDependencyRuntimeService : public Poco::OSP::Service
{
public:
    using Ptr = Poco::AutoPtr<ServiceDependencyRuntimeService>;
    static constexpr const char* SERVICE_NAME =
        "pdr.service.serviceDependencyRuntime";

    virtual Snapshot snapshot() const = 0;
    virtual LifecycleDecision analyzeStart(const std::string& owner) const = 0;
    virtual LifecycleDecision analyzeStop(const std::string& owner) const = 0;
    virtual void refresh() = 0;

    const std::type_info& type() const override
    {
        return typeid(ServiceDependencyRuntimeService);
    }

    bool isA(const std::type_info& other) const override
    {
        return std::string(other.name()) ==
                   typeid(ServiceDependencyRuntimeService).name() ||
               Poco::OSP::Service::isA(other);
    }

protected:
    ~ServiceDependencyRuntimeService() override = default;
};
} // namespace PocoDDS::ServiceDependency
