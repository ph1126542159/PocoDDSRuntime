#pragma once

#include "PocoDDS/SchemaRegistry/SchemaStore.h"

#include <memory>
#include <mutex>
#include <optional>
#include <string>
#include <vector>

namespace PocoDDS::SchemaRegistry
{
class PDR_SCHEMA_REGISTRY_API Registry
{
public:
    explicit Registry(std::shared_ptr<SchemaStore> store);

    void initialize();
    RegistrationResult registerSchema(SchemaDescriptor schema);
    BatchRegistrationResult registerSchemas(std::vector<SchemaDescriptor> schemas);
    std::optional<SchemaDescriptor> find(const std::string& subject,
                                         const std::string& version) const;
    std::optional<SchemaDescriptor> latest(const std::string& subject) const;
    std::vector<SchemaDescriptor> versions(const std::string& subject) const;
    std::vector<SchemaDescriptor> schemas() const;
    bool deprecate(const std::string& subject, const std::string& version);

private:
    std::optional<SchemaDescriptor> latestLocked(const std::string& subject) const;

    std::shared_ptr<SchemaStore> _store;
    mutable std::mutex _mutex;
    std::vector<SchemaDescriptor> _schemas;
    bool _initialized{false};
};
} // namespace PocoDDS::SchemaRegistry
