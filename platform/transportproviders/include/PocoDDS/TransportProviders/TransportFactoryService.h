#pragma once

#include "PocoDDS/RuntimeCore/TransportRegistry.h"

#include <Poco/OSP/Service.h>

#include <memory>
#include <string>
#include <typeinfo>

namespace PocoDDS::TransportProviders
{
/// OSP service contract implemented by an independently deployed transport
/// provider Bundle. The factory owns protocol-specific configuration parsing;
/// consumers and the registry depend only on RuntimeCore contracts.
class TransportFactoryService : public Poco::OSP::Service
{
public:
    static constexpr const char* PROPERTY_KIND = "pdr.transport.factory.kind";
    static constexpr const char* PROPERTY_TYPE = "pdr.transport.factory.type";
    static constexpr const char* FACTORY_KIND = "message";

    virtual RuntimeCore::TransportDescriptor descriptor() const = 0;
    virtual RuntimeCore::Outcome<std::shared_ptr<RuntimeCore::IMessageTransport>>
    create(const RuntimeCore::TransportConfiguration& configuration) const = 0;

    const std::type_info& type() const override
    {
        return typeid(TransportFactoryService);
    }

    bool isA(const std::type_info& other) const override
    {
        return std::string(other.name()) == typeid(TransportFactoryService).name() ||
               Poco::OSP::Service::isA(other);
    }

protected:
    ~TransportFactoryService() override = default;
};
} // namespace PocoDDS::TransportProviders
