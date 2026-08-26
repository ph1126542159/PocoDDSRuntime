#pragma once

#include "PocoDDS/Capabilities/Capabilities.h"

#include <memory>
#include <functional>

namespace PocoDDS::Capabilities
{
class PDR_CAPABILITIES_API PolicyEngine
{
public:
    using AuditSink = std::function<void(const AuditRecord&)>;

    explicit PolicyEngine(std::vector<Rule> initialRules = {},
                          std::size_t auditCapacity = 2048,
                          AuditSink auditSink = {});
    PolicyEngine(std::vector<Rule> recoveredRules,
                 Poco::UInt64 recoveredGeneration,
                 std::size_t auditCapacity,
                 AuditSink auditSink = {});
    ~PolicyEngine();
    PolicyEngine(const PolicyEngine&) = delete;
    PolicyEngine& operator=(const PolicyEngine&) = delete;

    PolicySnapshot snapshot() const noexcept;
    Decision decide(const Request& request) const;
    void require(const Request& request) const;
    ReplaceResult replace(const ReplaceRequest& request);
    PolicySnapshot restore(std::vector<Rule> rules, Poco::UInt64 generation);
    std::vector<AuditRecord> audit(std::size_t limit = 100) const;

private:
    class Impl;
    std::unique_ptr<Impl> _impl;
};
} // namespace PocoDDS::Capabilities
