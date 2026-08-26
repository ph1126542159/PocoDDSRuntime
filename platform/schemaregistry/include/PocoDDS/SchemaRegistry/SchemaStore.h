#pragma once

#include "PocoDDS/SchemaRegistry/Schema.h"

#include <optional>
#include <string>
#include <vector>

namespace PocoDDS::SchemaRegistry
{
class PDR_SCHEMA_REGISTRY_API SchemaStore
{
public:
    virtual ~SchemaStore() = default;
    virtual void initialize() = 0;
    virtual std::vector<SchemaDescriptor> all() const = 0;
    virtual std::optional<SchemaDescriptor> find(const std::string& subject,
                                                 const std::string& version) const = 0;
    virtual void insert(const std::vector<SchemaDescriptor>& schemas) = 0;
    virtual bool deprecate(const std::string& subject, const std::string& version) = 0;
};
} // namespace PocoDDS::SchemaRegistry
