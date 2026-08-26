#pragma once

#include "PocoDDS/ServiceDirectory/Directory.h"

#include <Poco/AutoPtr.h>
#include <Poco/OSP/Service.h>

#include <string>
#include <typeinfo>

namespace PocoDDS::ServiceDirectory
{
class ServiceDirectoryRuntimeService : public Poco::OSP::Service
{
public:
    using Ptr = Poco::AutoPtr<ServiceDirectoryRuntimeService>;
    static constexpr const char* SERVICE_NAME =
        "pdr.service.serviceDirectoryRuntime";

    virtual ObservationResult observe(Advertisement advertisement) = 0;
    virtual bool withdraw(const std::string& serviceName,
                          const std::string& instanceId,
                          const std::string& runtimeId,
                          std::uint64_t runtimeIncarnation,
                          std::uint64_t finalRevision) = 0;
    virtual Snapshot snapshot() const = 0;
    virtual RouteResult route(const RouteRequest& request) = 0;

    const std::type_info& type() const override
    {
        return typeid(ServiceDirectoryRuntimeService);
    }

    bool isA(const std::type_info& other) const override
    {
        return std::string(other.name()) ==
                   typeid(ServiceDirectoryRuntimeService).name() ||
               Poco::OSP::Service::isA(other);
    }

protected:
    ~ServiceDirectoryRuntimeService() override = default;
};
} // namespace PocoDDS::ServiceDirectory
