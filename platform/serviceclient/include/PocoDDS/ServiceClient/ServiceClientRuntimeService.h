#pragma once

#include "PocoDDS/ServiceClient/RuntimeCoordinator.h"

#include <Poco/AutoPtr.h>
#include <Poco/OSP/Service.h>
#include <typeinfo>

namespace PocoDDS::ServiceClient
{

class ServiceClientRuntimeService : public Poco::OSP::Service
{
public:
    using Ptr = Poco::AutoPtr<ServiceClientRuntimeService>;
    static constexpr const char* SERVICE_NAME =
        "pdr.service.serviceClientRuntime";

    virtual InvocationSubmission submit(RuntimeInvocationRequest request) = 0;
    virtual RuntimeSnapshot snapshot() const = 0;

    const std::type_info& type() const override
    {
        return typeid(ServiceClientRuntimeService);
    }

    bool isA(const std::type_info& other) const override
    {
        return std::string(other.name()) ==
                   typeid(ServiceClientRuntimeService).name() ||
               Poco::OSP::Service::isA(other);
    }

protected:
    ~ServiceClientRuntimeService() override = default;
};
} // namespace PocoDDS::ServiceClient
