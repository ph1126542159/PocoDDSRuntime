#pragma once

#include "PocoDDS/SchemaRegistry/Registry.h"

#include <Poco/OSP/Service.h>

#include <string>
#include <typeinfo>

namespace PocoDDS::SchemaRegistry
{
class SchemaRegistryService : public Poco::OSP::Service
{
public:
    static constexpr const char* SERVICE_NAME = "pdr.service.schemaRegistry";

    virtual RegistrationResult registerSchema(SchemaDescriptor schema,
                                              const std::string& principal) = 0;
    virtual BatchRegistrationResult registerSchemas(std::vector<SchemaDescriptor> schemas,
                                                     const std::string& principal) = 0;
    virtual std::optional<SchemaDescriptor> find(const std::string& subject,
                                                 const std::string& version) const = 0;
    virtual std::optional<SchemaDescriptor> latest(const std::string& subject) const = 0;
    virtual std::vector<SchemaDescriptor> versions(const std::string& subject) const = 0;
    virtual std::vector<SchemaDescriptor> schemas() const = 0;
    virtual bool deprecate(const std::string& subject, const std::string& version,
                           const std::string& principal) = 0;

    const std::type_info& type() const override { return typeid(SchemaRegistryService); }
    bool isA(const std::type_info& other) const override
    {
        return std::string(other.name()) == typeid(SchemaRegistryService).name() ||
               Poco::OSP::Service::isA(other);
    }

protected:
    ~SchemaRegistryService() override = default;
};
} // namespace PocoDDS::SchemaRegistry
