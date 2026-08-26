#pragma once

#include "PocoDDS/Capabilities/Capabilities.h"

#include <memory>
#include <string>

namespace PocoDDS::Capabilities
{
class PDR_CAPABILITIES_API SqlitePolicyStore
{
public:
    explicit SqlitePolicyStore(std::string databasePath,
                               std::size_t maximumAuditRecords = 10000);
    ~SqlitePolicyStore();
    SqlitePolicyStore(const SqlitePolicyStore&) = delete;
    SqlitePolicyStore& operator=(const SqlitePolicyStore&) = delete;

    PersistedPolicy initialize(const std::vector<Rule>& seedRules);
    PersistedPolicy current() const;
    ReplaceResult replace(const ReplaceRequest& request);
    void appendAudit(const AuditRecord& record);
    std::vector<AuditRecord> audit(std::size_t limit = 100) const;
    PersistenceSnapshot snapshot() const noexcept;
    bool operational() const noexcept;
    void verifyIntegrity() const;

private:
    class Impl;
    std::unique_ptr<Impl> _impl;
};
} // namespace PocoDDS::Capabilities
