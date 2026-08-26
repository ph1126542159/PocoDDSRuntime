#include "PocoDDS/SchemaRegistry/Registry.h"
#include "PocoDDS/SchemaRegistry/SchemaProviderService.h"
#include "PocoDDS/SchemaRegistry/SchemaRegistryService.h"
#include "PocoDDS/SchemaRegistry/SqliteSchemaStore.h"
#include "PocoDDS/Capabilities/CapabilityRuntimeService.h"

#include <Poco/AutoPtr.h>
#include <Poco/ClassLibrary.h>
#include <Poco/Delegate.h>
#include <Poco/Exception.h>
#include <Poco/OSP/Bundle.h>
#include <Poco/OSP/BundleActivator.h>
#include <Poco/OSP/BundleContext.h>
#include <Poco/OSP/PreferencesService.h>
#include <Poco/OSP/Properties.h>
#include <Poco/OSP/ServiceFinder.h>
#include <Poco/OSP/ServiceListener.h>
#include <Poco/OSP/ServiceRef.h>
#include <Poco/OSP/ServiceRegistry.h>
#include <Poco/Path.h>
#include <Poco/Util/AbstractConfiguration.h>

#include <algorithm>
#include <memory>
#include <mutex>
#include <string>
#include <utility>
#include <vector>

namespace PocoDDS::SchemaRegistry
{
namespace
{
SchemaDescriptor builtInTopicContract()
{
    return {
        "pdr.runtime.topic-contract", "1.0.0", SchemaKind::configuration,
        "json-schema-draft-07", CompatibilityMode::backward, "pdr.runtime-core",
        R"({"type":"object","additionalProperties":false,"required":["name","messageType","schemaVersion","delivery","durable"],"properties":{"name":{"type":"string","minLength":1},"messageType":{"type":"string","minLength":1},"schemaVersion":{"type":"string","minLength":1},"delivery":{"type":"string","enum":["best-effort","reliable"]},"durable":{"type":"boolean"}}})"};
}
} // namespace

class RuntimeServiceImpl final : public SchemaRegistryService
{
public:
    RuntimeServiceImpl(
        std::shared_ptr<SchemaStore> store,
        Poco::AutoPtr<PocoDDS::Capabilities::CapabilityRuntimeService> capabilities)
        : _capabilities(std::move(capabilities)), _registry(std::move(store))
    {
        _registry.initialize();
        const auto result = _registry.registerSchema(builtInTopicContract());
        if (!result.accepted)
            throw Poco::IllegalStateException("Cannot register built-in topic schema", result.message);
    }

    RegistrationResult registerSchema(SchemaDescriptor schema,
                                      const std::string& principal) override
    {
        authorize(principal, schema.subject, PocoDDS::Capabilities::Action::registerSchema);
        return _registry.registerSchema(std::move(schema));
    }
    BatchRegistrationResult registerSchemas(std::vector<SchemaDescriptor> schemas,
                                             const std::string& principal) override
    {
        for (const auto& schema : schemas)
            authorize(principal, schema.subject, PocoDDS::Capabilities::Action::registerSchema);
        return _registry.registerSchemas(std::move(schemas));
    }
    std::optional<SchemaDescriptor> find(const std::string& subject,
                                         const std::string& version) const override
    {
        return _registry.find(subject, version);
    }
    std::optional<SchemaDescriptor> latest(const std::string& subject) const override
    {
        return _registry.latest(subject);
    }
    std::vector<SchemaDescriptor> versions(const std::string& subject) const override
    {
        return _registry.versions(subject);
    }
    std::vector<SchemaDescriptor> schemas() const override { return _registry.schemas(); }
    bool deprecate(const std::string& subject, const std::string& version,
                   const std::string& principal) override
    {
        authorize(principal, subject, PocoDDS::Capabilities::Action::deprecate);
        return _registry.deprecate(subject, version);
    }

private:
    void authorize(const std::string& principal, const std::string& subject,
                   PocoDDS::Capabilities::Action action) const
    {
        _capabilities->require({principal, PocoDDS::Capabilities::ResourceKind::schema,
                                subject, action});
    }

    Poco::AutoPtr<PocoDDS::Capabilities::CapabilityRuntimeService> _capabilities;
    Registry _registry;
};

class SchemaRegistryBundleActivator final : public Poco::OSP::BundleActivator
{
public:
    void start(Poco::OSP::BundleContext::Ptr context) override
    {
        try
        {
            _context = context;
            auto preferences =
                Poco::OSP::ServiceFinder::find<Poco::OSP::PreferencesService>(context);
            Poco::Path defaultDatabase(context->persistentDirectory());
            defaultDatabase.append("schemas.sqlite");
            const std::string database = preferences->configuration()->getString(
                "pdr.schemaRegistry.database", defaultDatabase.toString());
            auto capabilities = Poco::OSP::ServiceFinder::find<
                PocoDDS::Capabilities::CapabilityRuntimeService>(context);
            _service = new RuntimeServiceImpl(
                std::make_shared<SqliteSchemaStore>(database), capabilities);

            _providerListener = context->registry().createListener(
                "pdr.schema.provider.kind == \"registry\"",
                Poco::delegate(this, &SchemaRegistryBundleActivator::onProviderRegistered),
                Poco::delegate(this, &SchemaRegistryBundleActivator::onProviderUnregistered));

            Poco::OSP::Properties properties;
            properties.set("pdr.service", "schemaRegistry");
            properties.set("pdr.schema.registry", "true");
            properties.set("pdr.bundle", context->thisBundle()->symbolicName());
            _serviceRef = context->registry().registerService(
                SchemaRegistryService::SERVICE_NAME, _service, properties);
            context->logger().information(
                "Schema registry started with " + std::to_string(_service->schemas().size()) +
                " immutable schema(s) at " + database + ".");
        }
        catch (...)
        {
            stop(context);
            throw;
        }
    }

    void stop(Poco::OSP::BundleContext::Ptr context) override
    {
        _providerListener = nullptr;
        if (_serviceRef)
        {
            try { context->registry().unregisterService(_serviceRef); }
            catch (...) {}
        }
        _serviceRef = nullptr;
        {
            std::lock_guard<std::mutex> lock(_providerMutex);
            _providers.clear();
        }
        _service = nullptr;
        _context = nullptr;
    }

private:
    struct ProviderEntry
    {
        Poco::OSP::ServiceRef::Ptr reference;
        std::string id;
    };

    void onProviderRegistered(const Poco::OSP::ServiceRef::Ptr& reference)
    {
        std::lock_guard<std::mutex> lock(_providerMutex);
        if (!_service) return;
        if (std::any_of(_providers.begin(), _providers.end(), [&](const auto& entry) {
                return entry.reference->name() == reference->name();
            })) return;
        try
        {
            const auto provider = reference->castedInstance<SchemaProviderService>();
            const auto id = provider->providerId();
            const auto propertyId = reference->properties().get(
                SchemaProviderService::PROPERTY_ID, "");
            if (id.empty() || propertyId != id)
                throw Poco::InvalidArgumentException(
                    "Schema provider property/id mismatch", reference->name());
            auto schemas = provider->schemas();
            if (schemas.empty())
                throw Poco::InvalidArgumentException("Schema provider has no schemas", id);
            for (const auto& schema : schemas)
                if (schema.owner != id)
                    throw Poco::InvalidArgumentException(
                        "Schema owner must equal provider id", schema.subject);
            const auto result = _service->registerSchemas(std::move(schemas), id);
            if (!result.accepted)
            {
                const auto message = result.results.empty() ? "unknown rejection" :
                                     result.results.back().code + ": " +
                                         result.results.back().message;
                throw Poco::InvalidArgumentException("Schema provider batch rejected", message);
            }
            _providers.push_back({reference, id});
            if (_context)
                _context->logger().information("Schema provider " + id + " attached.");
        }
        catch (const Poco::Exception& exception)
        {
            logError("Schema provider registration failed: " + exception.displayText());
        }
        catch (const std::exception& exception)
        {
            logError("Schema provider registration failed: " + std::string(exception.what()));
        }
    }

    void onProviderUnregistered(const Poco::OSP::ServiceRef::Ptr& reference)
    {
        std::lock_guard<std::mutex> lock(_providerMutex);
        const auto found = std::find_if(_providers.begin(), _providers.end(),
            [&](const auto& entry) { return entry.reference->name() == reference->name(); });
        if (found == _providers.end()) return;
        const auto id = found->id;
        _providers.erase(found);
        if (_context)
            _context->logger().information(
                "Schema provider " + id + " detached; immutable schemas remain registered.");
    }

    void logError(const std::string& message) const
    {
        if (_context) _context->logger().error(message);
    }

    Poco::OSP::BundleContext::Ptr _context;
    Poco::AutoPtr<RuntimeServiceImpl> _service;
    Poco::OSP::ServiceRef::Ptr _serviceRef;
    Poco::OSP::ServiceListener::Ptr _providerListener;
    std::mutex _providerMutex;
    std::vector<ProviderEntry> _providers;
};
} // namespace PocoDDS::SchemaRegistry

POCO_BEGIN_MANIFEST(Poco::OSP::BundleActivator)
    POCO_EXPORT_CLASS(PocoDDS::SchemaRegistry::SchemaRegistryBundleActivator)
POCO_END_MANIFEST
