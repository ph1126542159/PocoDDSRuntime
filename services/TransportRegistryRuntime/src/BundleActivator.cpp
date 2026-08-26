#include "PocoDDS/TransportProviders/ProviderRegistration.h"
#include "PocoDDS/TransportProviders/TransportRegistryService.h"

#include <Poco/AutoPtr.h>
#include <Poco/ClassLibrary.h>
#include <Poco/Delegate.h>
#include <Poco/Exception.h>
#include <Poco/OSP/Bundle.h>
#include <Poco/OSP/BundleActivator.h>
#include <Poco/OSP/BundleContext.h>
#include <Poco/OSP/Properties.h>
#include <Poco/OSP/ServiceListener.h>
#include <Poco/OSP/ServiceRef.h>
#include <Poco/OSP/ServiceRegistry.h>

#include <algorithm>
#include <memory>
#include <mutex>
#include <string>
#include <utility>
#include <vector>

namespace PocoDDS::TransportProviders
{
class RuntimeServiceImpl final : public TransportRegistryService
{
public:
    RuntimeServiceImpl()
    {
        auto registered = RuntimeCore::registerInProcessTransport(_registry);
        if (!registered)
            throw Poco::IllegalStateException(
                "Cannot register built-in in-process transport",
                registered.error().message);
        _inProcess = std::move(registered).value();
    }

    RuntimeCore::Outcome<RuntimeCore::TransportRegistration> registerFactory(
        RuntimeCore::TransportDescriptor descriptor,
        RuntimeCore::TransportFactory factory) override
    {
        return _registry.registerFactory(std::move(descriptor), std::move(factory));
    }

    RuntimeCore::Outcome<std::shared_ptr<RuntimeCore::IMessageTransport>> create(
        const std::string& id,
        const RuntimeCore::TransportConfiguration& configuration = {}) const override
    {
        return _registry.create(id, configuration);
    }

    std::vector<RuntimeCore::TransportDescriptor> descriptors() const override
    {
        return _registry.descriptors();
    }

private:
    RuntimeCore::TransportRegistry _registry;
    RuntimeCore::TransportRegistration _inProcess;
};

class TransportRegistryBundleActivator final : public Poco::OSP::BundleActivator
{
public:
    void start(Poco::OSP::BundleContext::Ptr context) override
    {
        try
        {
            _context = context;
            _service = new RuntimeServiceImpl;
            _providerListener = context->registry().createListener(
                "pdr.transport.factory.kind == \"message\"",
                Poco::delegate(this, &TransportRegistryBundleActivator::onProviderRegistered),
                Poco::delegate(this, &TransportRegistryBundleActivator::onProviderUnregistered));

            Poco::OSP::Properties properties;
            properties.set("pdr.service", "transportRegistry");
            properties.set("pdr.transport.registry", "true");
            properties.set("pdr.bundle", context->thisBundle()->symbolicName());
            _serviceRef = context->registry().registerService(
                TransportRegistryService::SERVICE_NAME, _service, properties);
            context->logger().information(
                "Dynamic transport registry started with " +
                std::to_string(_service->descriptors().size()) + " transport factory/factories.");
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
            try
            {
                context->registry().unregisterService(_serviceRef);
            }
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
        std::string type;
        RuntimeCore::TransportRegistration registration;
    };

    void onProviderRegistered(const Poco::OSP::ServiceRef::Ptr& reference)
    {
        std::lock_guard<std::mutex> lock(_providerMutex);
        if (!_service) return;
        if (std::any_of(_providers.begin(), _providers.end(),
                        [&](const auto& item) {
                            return item.reference->name() == reference->name();
                        }))
            return;

        try
        {
            auto provider = reference->castedInstance<TransportFactoryService>();
            const auto descriptor = provider->descriptor();
            const auto registeredType = reference->properties().get(
                TransportFactoryService::PROPERTY_TYPE, "");
            if (registeredType != descriptor.id)
            {
                logError("Transport provider property/type mismatch for service " +
                         reference->name());
                return;
            }

            auto attached = registerTransportProvider(*_service, provider);
            if (!attached)
            {
                logError("Transport provider '" + descriptor.id +
                         "' was rejected: " + attached.error().message);
                return;
            }
            _providers.push_back(
                {reference, descriptor.id, std::move(attached).value()});
            if (_context)
                _context->logger().information(
                    "Transport provider " + descriptor.id + " attached through registry.");
        }
        catch (const Poco::Exception& exception)
        {
            logError("Transport provider registration failed: " + exception.displayText());
        }
        catch (const std::exception& exception)
        {
            logError("Transport provider registration failed: " +
                     std::string(exception.what()));
        }
    }

    void onProviderUnregistered(const Poco::OSP::ServiceRef::Ptr& reference)
    {
        std::lock_guard<std::mutex> lock(_providerMutex);
        const auto found = std::find_if(
            _providers.begin(), _providers.end(),
            [&](const auto& item) { return item.reference->name() == reference->name(); });
        if (found == _providers.end()) return;
        const auto type = found->type;
        _providers.erase(found);
        if (_context)
            _context->logger().information(
                "Transport provider " + type + " detached from registry.");
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
} // namespace PocoDDS::TransportProviders

POCO_BEGIN_MANIFEST(Poco::OSP::BundleActivator)
    POCO_EXPORT_CLASS(PocoDDS::TransportProviders::TransportRegistryBundleActivator)
POCO_END_MANIFEST
