#pragma once

#include "PocoDDS/StoreForward/StoreForward.h"

#include <Poco/OSP/Service.h>

#include <string>
#include <typeinfo>

namespace PocoDDS::StoreForward
{
class DeliveryProviderService : public Poco::OSP::Service
{
public:
    static constexpr const char* PROPERTY_KIND = "pdr.delivery.provider.kind";
    static constexpr const char* PROPERTY_TYPE = "pdr.delivery.provider.type";
    static constexpr const char* PROVIDER_KIND = "outbox";

    virtual ProviderDescriptor descriptor() const = 0;
    virtual DeliveryResult deliver(const DeliveryRequest& request) = 0;

    const std::type_info& type() const override
    {
        return typeid(DeliveryProviderService);
    }

    bool isA(const std::type_info& other) const override
    {
        return std::string(other.name()) == typeid(DeliveryProviderService).name() ||
               Poco::OSP::Service::isA(other);
    }

protected:
    ~DeliveryProviderService() override = default;
};
} // namespace PocoDDS::StoreForward
