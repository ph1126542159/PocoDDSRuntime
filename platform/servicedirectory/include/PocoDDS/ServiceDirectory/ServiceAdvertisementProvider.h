#pragma once

#include "PocoDDS/ServiceDirectory/Directory.h"

#include <Poco/OSP/Service.h>

#include <string>
#include <typeinfo>
#include <vector>

namespace PocoDDS::ServiceDirectory
{
class ServiceAdvertisementProvider : public Poco::OSP::Service
{
public:
    static constexpr const char* PROPERTY_KIND =
        "pdr.serviceAdvertisement.provider.kind";
    static constexpr const char* PROPERTY_ID =
        "pdr.serviceAdvertisement.provider.id";
    static constexpr const char* KIND = "directory";

    virtual std::string providerId() const = 0;
    virtual std::vector<ServiceDescriptor> descriptors() const = 0;

    const std::type_info& type() const override
    {
        return typeid(ServiceAdvertisementProvider);
    }

    bool isA(const std::type_info& other) const override
    {
        return std::string(other.name()) ==
                   typeid(ServiceAdvertisementProvider).name() ||
               Poco::OSP::Service::isA(other);
    }

protected:
    ~ServiceAdvertisementProvider() override = default;
};
} // namespace PocoDDS::ServiceDirectory
