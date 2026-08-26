#include "PocoDDS/Devices/Device.h"
#include "PocoDDS/Devices/DeviceService.h"
#include "PocoDDS/DDS/DeviceBridge.h"
#include "PocoDDS/DDS/Runtime.h"
#include "PocoDDS/Configuration/IndexedConfiguration.h"
#include "PocoDDS/Gateways/FactoryService.h"

#include "Poco/ClassLibrary.h"
#include "Poco/Exception.h"
#include "Poco/Delegate.h"
#include "Poco/OSP/Bundle.h"
#include "Poco/OSP/BundleActivator.h"
#include "Poco/OSP/BundleContext.h"
#include "Poco/OSP/Properties.h"
#include "Poco/OSP/PreferencesService.h"
#include "Poco/OSP/Service.h"
#include "Poco/OSP/ServiceFinder.h"
#include "Poco/OSP/ServiceRef.h"
#include "Poco/OSP/ServiceRegistry.h"
#include "Poco/OSP/ServiceListener.h"
#include "Poco/Util/AbstractConfiguration.h"

#include <memory>
#include <algorithm>
#include <string>
#include <unordered_set>
#include <vector>
#include <mutex>

namespace PocoDDS::Services
{
class DeviceGatewayActivator final : public Poco::OSP::BundleActivator
{
public:
    void addDevice(Poco::OSP::BundleContext::Ptr context,
                   std::unique_ptr<PocoDDS::Devices::Device> device,
                   bool required = true)
    {
        if (!_deviceIds.insert(device->id()).second)
            throw Poco::InvalidArgumentException("Duplicate device id", device->id());
        auto bridge =
            std::make_unique<PocoDDS::FastDDS::DeviceBridge>(*_runtime, *device);
        try
        {
            bridge->start();
        }
        catch (...)
        {
            _deviceIds.erase(device->id());
            throw;
        }
        Poco::OSP::Properties properties;
        properties.set("pdr.device", device->id());
        properties.set("pdr.deviceType", device->type());
        properties.set("pdr.deviceState", "ready");
        properties.set("pdr.deviceRequired", required ? "true" : "false");
        properties.set("pdr.bundle", context->thisBundle()->symbolicName());
        Poco::OSP::ServiceRef::Ptr service;
        try
        {
            service = context->registry().registerService(
                "pdr.device." + device->id(),
                new PocoDDS::Devices::DeviceService(*device), properties);
        }
        catch (...)
        {
            if (service)
                context->registry().unregisterService(service);
            bridge->stop();
            _deviceIds.erase(device->id());
            throw;
        }
        _devices.push_back(std::move(device));
        _bridges.push_back(std::move(bridge));
        _services.push_back(std::move(service));
    }

    void start(Poco::OSP::BundleContext::Ptr context) override
    {
        auto preferences =
            Poco::OSP::ServiceFinder::find<Poco::OSP::PreferencesService>(context);
        auto configuration = preferences->configuration();
        const auto domainId =
            static_cast<std::uint32_t>(configuration->getUInt("pdr.fastdds.domainId", 0));
        _runtime =
            std::make_unique<PocoDDS::FastDDS::Runtime>(domainId, "pdr-device-gateway");
        _runtime->start();
        _context = context;
        _configuration = configuration;
        _factoryListener = context->registry().createListener(
            "pdr.gateway.factory.kind == \"device\"",
            Poco::delegate(this, &DeviceGatewayActivator::onFactoryRegistered),
            Poco::delegate(this, &DeviceGatewayActivator::onFactoryUnregistered));
        context->logger().information("Fast DDS device gateway started with %z device(s) "
                                      "on domain %u.",
                                      _devices.size(), domainId);
    }

    void stop(Poco::OSP::BundleContext::Ptr context) override
    {
        _factoryListener = nullptr;
        std::lock_guard<std::mutex> lock(_factoryMutex);
        for (auto& bridge : _bridges)
            bridge->stop();
        for (auto& service : _services)
            context->registry().unregisterService(service);
        _services.clear();
        _bridges.clear();
        _devices.clear();
        _factoryServices.clear();
        _factoryTypes.clear();
        _deviceIds.clear();
        if (_runtime)
            _runtime->stop();
        _runtime.reset();
        _configuration = nullptr;
        _context = nullptr;
    }

private:
    void onFactoryRegistered(const Poco::OSP::ServiceRef::Ptr& reference)
    {
        std::lock_guard<std::mutex> lock(_factoryMutex);
        if (!_context || !_configuration) return;
        if (std::any_of(_factoryServices.begin(), _factoryServices.end(),
                        [&](const auto& current) {
                            return current->name() == reference->name();
                        })) return;

        auto factory = reference->castedInstance<
            PocoDDS::Gateways::DeviceFactoryService>();
        const auto descriptor = factory->descriptor();
        if (descriptor.type.empty() || descriptor.configurationBase.empty() ||
            descriptor.defaultIdPrefix.empty())
            throw Poco::InvalidArgumentException(
                "Incomplete device factory descriptor", reference->name());
        const auto registeredType = reference->properties().get(
            PocoDDS::Gateways::DeviceFactoryService::PROPERTY_TYPE, "");
        if (registeredType != descriptor.type)
            throw Poco::InvalidArgumentException(
                "Device factory property/type mismatch", reference->name());
        if (!_factoryTypes.insert(descriptor.type).second)
            throw Poco::ExistsException(
                "Duplicate device factory type", descriptor.type);

        const auto serviceBase = _services.size();
        const auto bridgeBase = _bridges.size();
        const auto deviceBase = _devices.size();
        try
        {
            const auto configured = PocoDDS::Configuration::indexedInstances(
                *_configuration, descriptor.configurationBase,
                descriptor.legacyEnabledDefault, descriptor.indexedDefaultCount,
                descriptor.defaultIdPrefix);
            for (const auto& instance : configured)
            {
                if (!instance.enabled) continue;
                PocoDDS::Gateways::FactoryInstance request{
                    instance.index, instance.prefix, instance.id, instance.legacy};
                auto device = factory->create(*_configuration, request);
                if (!device)
                    throw Poco::NullPointerException(
                        "Device factory returned null", descriptor.type);
                addDevice(_context, std::move(device),
                          _configuration->getBool(instance.prefix + ".required", true));
            }
            _factoryServices.push_back(reference);
            _context->logger().information(
                "Device factory " + descriptor.type + " attached through registry.");
        }
        catch (...)
        {
            for (std::size_t index = _bridges.size(); index > bridgeBase; --index)
                _bridges[index - 1]->stop();
            for (std::size_t index = _services.size(); index > serviceBase; --index)
                _context->registry().unregisterService(_services[index - 1]);
            for (std::size_t index = deviceBase; index < _devices.size(); ++index)
                _deviceIds.erase(_devices[index]->id());
            _services.resize(serviceBase);
            _bridges.resize(bridgeBase);
            _devices.resize(deviceBase);
            _factoryTypes.erase(descriptor.type);
            throw;
        }
    }

    void onFactoryUnregistered(const Poco::OSP::ServiceRef::Ptr& reference)
    {
        std::lock_guard<std::mutex> lock(_factoryMutex);
        if (!_context) return;
        const auto found = std::find_if(
            _factoryServices.begin(), _factoryServices.end(),
            [&](const auto& current) { return current->name() == reference->name(); });
        if (found != _factoryServices.end())
            _context->logger().critical(
                "Device factory unregistered while created devices are active: " +
                reference->name());
    }

    Poco::OSP::BundleContext::Ptr _context;
    Poco::AutoPtr<Poco::Util::AbstractConfiguration> _configuration;
    Poco::OSP::ServiceListener::Ptr _factoryListener;
    std::vector<Poco::OSP::ServiceRef::Ptr> _services;
    std::unique_ptr<PocoDDS::FastDDS::Runtime> _runtime;
    std::vector<std::unique_ptr<PocoDDS::Devices::Device>> _devices;
    std::unordered_set<std::string> _deviceIds;
    std::vector<std::unique_ptr<PocoDDS::FastDDS::DeviceBridge>> _bridges;
    std::vector<Poco::OSP::ServiceRef::Ptr> _factoryServices;
    std::unordered_set<std::string> _factoryTypes;
    std::mutex _factoryMutex;
};
} // namespace PocoDDS::Services

POCO_BEGIN_MANIFEST(Poco::OSP::BundleActivator)
POCO_EXPORT_CLASS(PocoDDS::Services::DeviceGatewayActivator)
POCO_END_MANIFEST
