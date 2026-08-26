#pragma once

#include "PocoDDS/RuntimeCore/TransportRegistry.h"

#include <Poco/OSP/Service.h>

#include <string>
#include <typeinfo>

namespace PocoDDS::TransportProviders
{
/// Runtime-facing catalog service. Client Bundles can discover transports and
/// create instances without linking MQTT, Fast DDS, or another provider.
class TransportRegistryService : public Poco::OSP::Service,
                                 public RuntimeCore::ITransportRegistry
{
public:
    static constexpr const char* SERVICE_NAME = "pdr.service.transportRegistry";

    const std::type_info& type() const override
    {
        return typeid(TransportRegistryService);
    }

    bool isA(const std::type_info& other) const override
    {
        return std::string(other.name()) == typeid(TransportRegistryService).name() ||
               Poco::OSP::Service::isA(other);
    }

protected:
    ~TransportRegistryService() override = default;
};
} // namespace PocoDDS::TransportProviders
