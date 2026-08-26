#pragma once

#include "PocoDDS/SchemaRegistry/SchemaStore.h"

#include <memory>
#include <string>

namespace PocoDDS::SchemaRegistry
{
class PDR_SCHEMA_REGISTRY_API SqliteSchemaStore final : public SchemaStore
{
public:
    explicit SqliteSchemaStore(std::string path);
    ~SqliteSchemaStore() override;

    void initialize() override;
    std::vector<SchemaDescriptor> all() const override;
    std::optional<SchemaDescriptor> find(const std::string& subject,
                                         const std::string& version) const override;
    void insert(const std::vector<SchemaDescriptor>& schemas) override;
    bool deprecate(const std::string& subject, const std::string& version) override;

private:
    class Impl;
    std::unique_ptr<Impl> _impl;
};
} // namespace PocoDDS::SchemaRegistry
