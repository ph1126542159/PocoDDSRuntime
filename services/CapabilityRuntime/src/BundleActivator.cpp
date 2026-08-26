#include "PocoDDS/Capabilities/CapabilityRuntimeService.h"
#include "PocoDDS/Capabilities/SqlitePolicyStore.h"

#include <Poco/AutoPtr.h>
#include <Poco/ClassLibrary.h>
#include <Poco/Exception.h>
#include <Poco/OSP/Bundle.h>
#include <Poco/OSP/BundleActivator.h>
#include <Poco/OSP/BundleContext.h>
#include <Poco/OSP/PreferencesService.h>
#include <Poco/OSP/Properties.h>
#include <Poco/OSP/ServiceFinder.h>
#include <Poco/OSP/ServiceRef.h>
#include <Poco/OSP/ServiceRegistry.h>
#include <Poco/Util/AbstractConfiguration.h>

#include <memory>
#include <string>
#include <utility>

namespace PocoDDS::Capabilities
{
class RuntimeServiceImpl final : public CapabilityRuntimeService
{
public:
    RuntimeServiceImpl(std::unique_ptr<SqlitePolicyStore> store,
                       const std::vector<Rule>& seedRules,
                       std::size_t memoryAuditCapacity,
                       DecisionLeaseOptions leaseOptions)
        : _store(std::move(store))
    {
        if (!_store) throw Poco::InvalidArgumentException("Capability policy store is required");
        const auto persisted = _store->initialize(seedRules);
        _engine = std::make_unique<PolicyEngine>(
            persisted.rules, persisted.snapshot.generation, memoryAuditCapacity,
            [this](const AuditRecord& record) { _store->appendAudit(record); });
        _leases = std::make_unique<DecisionLeaseAuthorizer>(
            [this](const Request& request) { return _engine->decide(request); },
            [this] { return _engine->snapshot(); }, leaseOptions,
            [this] { return _store->operational(); });
    }

    PolicySnapshot snapshot() const override { return _engine->snapshot(); }
    Decision decide(const Request& request) const override { return _engine->decide(request); }
    void require(const Request& request) const override { _engine->require(request); }
    Decision decideLeased(const Request& request) const override
    {
        return _leases->authorize(request);
    }
    void requireLeased(const Request& request) const override { _leases->require(request); }
    DecisionLeaseSnapshot leases() const override { return _leases->snapshot(); }
    ReplaceResult replace(const ReplaceRequest& request) override
    {
        _engine->require(
            {request.actor, ResourceKind::service, SERVICE_NAME, Action::use});
        const auto result = _store->replace(request);
        if (!result.idempotentReplay)
        {
            _engine->restore(request.rules, result.snapshot.generation);
            _leases->invalidate();
        }
        return result;
    }
    std::vector<AuditRecord> audit(std::size_t limit) const override
    {
        return _store->audit(limit);
    }
    PersistenceSnapshot persistence() const override { return _store->snapshot(); }

private:
    std::unique_ptr<SqlitePolicyStore> _store;
    std::unique_ptr<PolicyEngine> _engine;
    std::unique_ptr<DecisionLeaseAuthorizer> _leases;
};

class CapabilityRuntimeBundleActivator final : public Poco::OSP::BundleActivator
{
public:
    void start(Poco::OSP::BundleContext::Ptr context) override
    {
        try
        {
            auto preferences =
                Poco::OSP::ServiceFinder::find<Poco::OSP::PreferencesService>(context);
            const auto policyPath = preferences->configuration()->getString(
                "pdr.capabilityRuntime.policy");
            const auto seedRules = loadPolicyFile(policyPath);
            Poco::Path defaultDatabase(context->persistentDirectory());
            defaultDatabase.append("capabilities.sqlite");
            const auto database = preferences->configuration()->getString(
                "pdr.capabilityRuntime.database", defaultDatabase.toString());
            const auto maximumAuditRecords = preferences->configuration()->getInt(
                "pdr.capabilityRuntime.auditMaximumRecords", 10000);
            const auto memoryAuditCapacity = preferences->configuration()->getInt(
                "pdr.capabilityRuntime.memoryAuditCapacity", 2048);
            DecisionLeaseOptions leaseOptions;
            leaseOptions.enabled = preferences->configuration()->getBool(
                "pdr.capabilityRuntime.leaseEnabled", true);
            const auto leaseDurationMilliseconds = preferences->configuration()->getInt(
                "pdr.capabilityRuntime.leaseDurationMilliseconds", 250);
            const auto leaseMaximumUses = preferences->configuration()->getInt(
                "pdr.capabilityRuntime.leaseMaximumUses", 1024);
            const auto leaseCapacity = preferences->configuration()->getInt(
                "pdr.capabilityRuntime.leaseCapacity", 4096);
            if (maximumAuditRecords <= 0 || memoryAuditCapacity <= 0)
                throw Poco::InvalidArgumentException(
                    "Capability audit capacities must be positive");
            if (leaseDurationMilliseconds <= 0 || leaseMaximumUses <= 0 || leaseCapacity <= 0)
                throw Poco::InvalidArgumentException(
                    "Capability decision lease settings must be positive");
            leaseOptions.durationMilliseconds =
                static_cast<Poco::UInt64>(leaseDurationMilliseconds);
            leaseOptions.maximumUses = static_cast<Poco::UInt64>(leaseMaximumUses);
            leaseOptions.capacity = static_cast<std::size_t>(leaseCapacity);
            _service = new RuntimeServiceImpl(
                std::make_unique<SqlitePolicyStore>(
                    database, static_cast<std::size_t>(maximumAuditRecords)),
                seedRules, static_cast<std::size_t>(memoryAuditCapacity), leaseOptions);
            const auto snapshot = _service->snapshot();
            const bool sourceDrift = snapshot.digest != policyDigest(seedRules);

            Poco::OSP::Properties properties;
            properties.set("pdr.service", "capabilityRuntime");
            properties.set("pdr.capability.defaultEffect", "deny");
            properties.set("pdr.capability.generation", std::to_string(snapshot.generation));
            properties.set("pdr.capability.digest", snapshot.digest);
            properties.set("pdr.capability.persistence", "sqlite-wal-full");
            properties.set("pdr.capability.decisionLease",
                           leaseOptions.enabled ? "enabled" : "disabled");
            properties.set("pdr.capability.leaseDurationMilliseconds",
                           std::to_string(leaseOptions.durationMilliseconds));
            properties.set("pdr.capability.sourceDrift", sourceDrift ? "true" : "false");
            properties.set("pdr.bundle", context->thisBundle()->symbolicName());
            _serviceRef = context->registry().registerService(
                CapabilityRuntimeService::SERVICE_NAME, _service, properties);
            context->logger().information(
                "Bundle capability runtime started with default deny, " +
                std::to_string(snapshot.ruleCount) + " rule(s), generation " +
                std::to_string(snapshot.generation) + ", database " + database +
                ", decision leases " + (leaseOptions.enabled ? "enabled" : "disabled") + ".");
            if (sourceDrift)
                context->logger().warning(
                    "Capability policy file differs from persisted generation; "
                    "the persisted policy remains authoritative.");
        }
        catch (...)
        {
            stop(context);
            throw;
        }
    }

    void stop(Poco::OSP::BundleContext::Ptr context) override
    {
        if (_serviceRef)
        {
            try { context->registry().unregisterService(_serviceRef); }
            catch (...) {}
        }
        _serviceRef = nullptr;
        _service = nullptr;
    }

private:
    Poco::AutoPtr<RuntimeServiceImpl> _service;
    Poco::OSP::ServiceRef::Ptr _serviceRef;
};
} // namespace PocoDDS::Capabilities

POCO_BEGIN_MANIFEST(Poco::OSP::BundleActivator)
    POCO_EXPORT_CLASS(PocoDDS::Capabilities::CapabilityRuntimeBundleActivator)
POCO_END_MANIFEST
