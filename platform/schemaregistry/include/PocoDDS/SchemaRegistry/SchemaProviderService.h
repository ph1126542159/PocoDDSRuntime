#pragma once

#include "PocoDDS/SchemaRegistry/Schema.h"

#include <Poco/OSP/Service.h>

#include <string>
#include <typeinfo>
#include <vector>

namespace PocoDDS::SchemaRegistry
{
class SchemaProviderService : public Poco::OSP::Service
{
public:
    static constexpr const char* PROPERTY_KIND = "pdr.schema.provider.kind";
    static constexpr const char* PROPERTY_ID = "pdr.schema.provider.id";
    static constexpr const char* KIND = "registry";

    virtual std::string providerId() const = 0;
    virtual std::vector<SchemaDescriptor> schemas() const = 0;

    const std::type_info& type() const override { return typeid(SchemaProviderService); }
    bool isA(const std::type_info& other) const override
    {
        return std::string(other.name()) == typeid(SchemaProviderService).name() ||
               Poco::OSP::Service::isA(other);
    }

protected:
    ~SchemaProviderService() override = default;
};
} // namespace PocoDDS::SchemaRegistry

