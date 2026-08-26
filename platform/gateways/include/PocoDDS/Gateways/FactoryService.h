#pragma once

#include "PocoDDS/Devices/Device.h"
#include "PocoDDS/Protocols/ProtocolDiagnostics.h"

#include "Poco/OSP/Service.h"

#include <cstddef>
#include <memory>
#include <string>
#include <typeinfo>

namespace Poco::Util
{
class AbstractConfiguration;
}

namespace PocoDDS::Gateways
{
/// Stable description used by a Gateway to enumerate instances owned by one
/// independently deployed factory Bundle.
struct FactoryDescriptor
{
    std::string type;
    std::string configurationBase;
    std::string defaultIdPrefix;
    bool legacyEnabledDefault{false};
    std::size_t indexedDefaultCount{0};
};

/// Per-instance identity passed to a factory. Configuration remains read-only
/// and is deliberately not hidden behind a concrete Gateway implementation.
struct FactoryInstance
{
    std::size_t index{0};
    std::string prefix;
    std::string id;
    bool legacy{false};

    [[nodiscard]] std::string key(const char* name) const
    {
        return prefix + "." + name;
    }
};

class DeviceFactoryService : public Poco::OSP::Service
{
public:
    static constexpr const char* FACTORY_KIND = "device";
    static constexpr const char* PROPERTY_KIND = "pdr.gateway.factory.kind";
    static constexpr const char* PROPERTY_TYPE = "pdr.gateway.factory.type";

    virtual FactoryDescriptor descriptor() const = 0;
    virtual std::unique_ptr<PocoDDS::Devices::Device> create(
        const Poco::Util::AbstractConfiguration& configuration,
        const FactoryInstance& instance) const = 0;

    const std::type_info& type() const override
    {
        return typeid(DeviceFactoryService);
    }

    bool isA(const std::type_info& other) const override
    {
        return std::string(other.name()) == typeid(DeviceFactoryService).name() ||
               Poco::OSP::Service::isA(other);
    }

protected:
    ~DeviceFactoryService() override = default;
};

class ProtocolFactoryService : public Poco::OSP::Service
{
public:
    static constexpr const char* FACTORY_KIND = "protocol";
    static constexpr const char* PROPERTY_KIND = "pdr.gateway.factory.kind";
    static constexpr const char* PROPERTY_TYPE = "pdr.gateway.factory.type";

    virtual FactoryDescriptor descriptor() const = 0;
    virtual std::unique_ptr<PocoDDS::Protocols::DiagnosticProtocol> create(
        const Poco::Util::AbstractConfiguration& configuration,
        const FactoryInstance& instance) const = 0;

    const std::type_info& type() const override
    {
        return typeid(ProtocolFactoryService);
    }

    bool isA(const std::type_info& other) const override
    {
        return std::string(other.name()) == typeid(ProtocolFactoryService).name() ||
               Poco::OSP::Service::isA(other);
    }

protected:
    ~ProtocolFactoryService() override = default;
};
} // namespace PocoDDS::Gateways
