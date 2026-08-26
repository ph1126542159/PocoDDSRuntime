#include "PocoDDS/Configuration/IndexedConfiguration.h"
#include "PocoDDS/Gateways/FactoryService.h"
#include "PocoDDS/Protocols/ProtocolService.h"

#include <Poco/ClassLibrary.h>
#include <Poco/Delegate.h>
#include <Poco/Exception.h>
#include <Poco/OSP/Bundle.h>
#include <Poco/OSP/BundleActivator.h>
#include <Poco/OSP/BundleContext.h>
#include <Poco/OSP/PreferencesService.h>
#include <Poco/OSP/Properties.h>
#include <Poco/OSP/ServiceFinder.h>
#include <Poco/OSP/ServiceRef.h>
#include <Poco/OSP/ServiceRegistry.h>
#include <Poco/OSP/ServiceListener.h>
#include <Poco/Util/AbstractConfiguration.h>

#include <cstddef>
#include <algorithm>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <unordered_set>
#include <utility>
#include <vector>

namespace PocoDDS::Services
{
class ProtocolGatewayActivator final : public Poco::OSP::BundleActivator
{
public:
    void start(Poco::OSP::BundleContext::Ptr context) override
    {
        auto preferences =
            Poco::OSP::ServiceFinder::find<Poco::OSP::PreferencesService>(context);
        auto configuration = preferences->configuration();
        try
        {
            _context = context;
            _configuration = configuration;
            _factoryListener = context->registry().createListener(
                "pdr.gateway.factory.kind == \"protocol\"",
                Poco::delegate(this, &ProtocolGatewayActivator::onFactoryRegistered),
                Poco::delegate(this, &ProtocolGatewayActivator::onFactoryUnregistered));

            context->logger().information(
                "Protocol gateway started with " + std::to_string(_protocols.size()) +
                " protocol instance(s).");
            ensureRecoveryThread();
        }
        catch (...)
        {
            stop(context);
            throw;
        }
    }

    void stop(Poco::OSP::BundleContext::Ptr context) override
    {
        _factoryListener = nullptr;
        _stopping = true;
        _recoveryChanged.notify_all();
        if (_recoveryThread.joinable()) _recoveryThread.join();
        std::lock_guard<std::mutex> lock(_protocolMutex);
        for (auto iterator = _services.rbegin(); iterator != _services.rend(); ++iterator)
            context->registry().unregisterService(*iterator);
        for (auto iterator = _services.rbegin(); iterator != _services.rend(); ++iterator)
        {
            try
            {
                (*iterator)->castedInstance<PocoDDS::Protocols::ProtocolService>()->close();
            }
            catch (...) {}
        }
        _services.clear();
        _protocols.clear();
        _factoryServices.clear();
        _factoryTypes.clear();
        _recoveries.clear();
        _ids.clear();
        _configuration = nullptr;
        _context = nullptr;
    }

private:
    void ensureRecoveryThread()
    {
        if (_recoveryThread.joinable() || !_context) return;
        if (!std::any_of(_recoveries.begin(), _recoveries.end(),
                         [](const auto& recovery) { return recovery.enabled; })) return;
        _stopping = false;
        const auto context = _context;
        _recoveryThread = std::thread([this, context] { recoveryLoop(context); });
    }

    void onFactoryRegistered(const Poco::OSP::ServiceRef::Ptr& reference)
    {
        std::lock_guard<std::mutex> lock(_protocolMutex);
        if (!_context || !_configuration) return;
        if (std::any_of(_factoryServices.begin(), _factoryServices.end(),
                        [&](const auto& current) {
                            return current->name() == reference->name();
                        })) return;

        auto factory = reference->castedInstance<
            PocoDDS::Gateways::ProtocolFactoryService>();
        const auto descriptor = factory->descriptor();
        if (descriptor.type.empty() || descriptor.configurationBase.empty() ||
            descriptor.defaultIdPrefix.empty())
            throw Poco::InvalidArgumentException(
                "Incomplete protocol factory descriptor", reference->name());
        const auto registeredType = reference->properties().get(
            PocoDDS::Gateways::ProtocolFactoryService::PROPERTY_TYPE, "");
        if (registeredType != descriptor.type)
            throw Poco::InvalidArgumentException(
                "Protocol factory property/type mismatch", reference->name());
        if (!_factoryTypes.insert(descriptor.type).second)
            throw Poco::ExistsException(
                "Duplicate protocol factory type", descriptor.type);

        const auto serviceBase = _services.size();
        const auto protocolBase = _protocols.size();
        const auto recoveryBase = _recoveries.size();
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
                auto protocol = factory->create(*_configuration, request);
                if (!protocol)
                    throw Poco::NullPointerException(
                        "Protocol factory returned null", descriptor.type);
                add(_context, instance.id, descriptor.type,
                    _configuration->getBool(instance.prefix + ".required", false),
                    _configuration->getBool(instance.prefix + ".autoReconnect", true),
                    _configuration->getUInt(
                        instance.prefix + ".reconnectDelayMilliseconds", 1000),
                    _configuration->getUInt(
                        instance.prefix + ".reconnectMaximumDelayMilliseconds", 30000),
                    std::move(protocol));
            }
            _factoryServices.push_back(reference);
            ensureRecoveryThread();
            _context->logger().information(
                "Protocol factory " + descriptor.type + " attached through registry.");
        }
        catch (...)
        {
            for (std::size_t index = _services.size(); index > serviceBase; --index)
            {
                const auto& service = _services[index - 1];
                try
                {
                    service->castedInstance<PocoDDS::Protocols::ProtocolService>()->close();
                }
                catch (...) {}
                _context->registry().unregisterService(service);
            }
            for (std::size_t index = recoveryBase; index < _recoveries.size(); ++index)
                _ids.erase(_recoveries[index].id);
            _services.resize(serviceBase);
            _protocols.resize(protocolBase);
            _recoveries.resize(recoveryBase);
            _factoryTypes.erase(descriptor.type);
            throw;
        }
    }

    void onFactoryUnregistered(const Poco::OSP::ServiceRef::Ptr& reference)
    {
        std::lock_guard<std::mutex> lock(_protocolMutex);
        if (!_context) return;
        const auto found = std::find_if(
            _factoryServices.begin(), _factoryServices.end(),
            [&](const auto& current) { return current->name() == reference->name(); });
        if (found != _factoryServices.end())
            _context->logger().critical(
                "Protocol factory unregistered while created protocols are active: " +
                reference->name());
    }

    void add(Poco::OSP::BundleContext::Ptr context,
             const std::string& id,
             const std::string& type,
             bool required,
             bool autoReconnect,
             unsigned reconnectDelayMilliseconds,
             unsigned reconnectMaximumDelayMilliseconds,
             std::unique_ptr<PocoDDS::Protocols::DiagnosticProtocol> protocol)
    {
        if (!_ids.insert(id).second)
            throw Poco::InvalidArgumentException("Duplicate protocol id", id);
        try
        {
            protocol->open();
        }
        catch (const std::exception& error)
        {
            if (required)
            {
                _ids.erase(id);
                throw;
            }
            context->logger().warning(
                "Optional protocol " + id + " failed to open: " + error.what());
        }

        Poco::OSP::Properties properties;
        properties.set("pdr.protocol", id);
        properties.set("pdr.protocol.id", id);
        properties.set("pdr.protocol.type", type);
        properties.set("pdr.protocol.required", required ? "true" : "false");
        properties.set("pdr.protocol.autoReconnect", autoReconnect ? "true" : "false");
        properties.set("pdr.bundle", context->thisBundle()->symbolicName());
        Poco::OSP::ServiceRef::Ptr service;
        bool serviceStored = false;
        bool protocolStored = false;
        bool recoveryStored = false;
        try
        {
            service = context->registry().registerService(
                "pdr.protocol." + id,
                new PocoDDS::Protocols::ProtocolService(*protocol), properties);
            _services.push_back(service);
            serviceStored = true;
            _protocols.push_back(std::move(protocol));
            protocolStored = true;
            const auto delay = std::chrono::milliseconds(reconnectDelayMilliseconds);
            _recoveries.push_back(Recovery{
                id, service, autoReconnect, delay,
                std::chrono::milliseconds(reconnectMaximumDelayMilliseconds), delay,
                std::chrono::steady_clock::now() + delay});
            recoveryStored = true;
        }
        catch (...)
        {
            if (service) context->registry().unregisterService(service);
            if (service)
            {
                try
                {
                    service->castedInstance<PocoDDS::Protocols::ProtocolService>()->close();
                }
                catch (...) {}
            }
            if (recoveryStored) _recoveries.pop_back();
            if (protocolStored) _protocols.pop_back();
            if (serviceStored) _services.pop_back();
            if (protocol) protocol->close();
            _ids.erase(id);
            throw;
        }
    }

    struct Recovery
    {
        std::string id;
        Poco::OSP::ServiceRef::Ptr service;
        bool enabled;
        std::chrono::milliseconds initialDelay;
        std::chrono::milliseconds maximumDelay;
        std::chrono::milliseconds currentDelay;
        std::chrono::steady_clock::time_point nextAttempt;
    };

    void recoveryLoop(Poco::OSP::BundleContext::Ptr context)
    {
        std::unique_lock<std::mutex> waitLock(_recoveryMutex);
        while (!_stopping)
        {
            _recoveryChanged.wait_for(waitLock, std::chrono::milliseconds(100),
                                      [&] { return _stopping.load(); });
            if (_stopping) break;
            waitLock.unlock();
            const auto now = std::chrono::steady_clock::now();
            std::lock_guard<std::mutex> protocolLock(_protocolMutex);
            for (auto& recovery : _recoveries)
            {
                if (!recovery.enabled || now < recovery.nextAttempt) continue;
                auto provider = recovery.service
                    ->castedInstance<PocoDDS::Protocols::ProtocolService>();
                try
                {
                    if (provider->recoverIfDesired())
                    {
                        context->logger().information(
                            "Protocol " + recovery.id + " recovered automatically.");
                        recovery.currentDelay = recovery.initialDelay;
                    }
                    recovery.nextAttempt = now + recovery.initialDelay;
                }
                catch (const std::exception& error)
                {
                    context->logger().warning(
                        "Protocol " + recovery.id + " automatic recovery failed: " +
                        error.what());
                    recovery.nextAttempt = now + recovery.currentDelay;
                    recovery.currentDelay = std::min(
                        recovery.maximumDelay, recovery.currentDelay * 2);
                }
            }
            waitLock.lock();
        }
    }

    std::unordered_set<std::string> _ids;
    std::vector<std::unique_ptr<PocoDDS::Protocols::DiagnosticProtocol>> _protocols;
    std::vector<Poco::OSP::ServiceRef::Ptr> _services;
    std::vector<Recovery> _recoveries;
    Poco::OSP::BundleContext::Ptr _context;
    Poco::AutoPtr<Poco::Util::AbstractConfiguration> _configuration;
    Poco::OSP::ServiceListener::Ptr _factoryListener;
    std::vector<Poco::OSP::ServiceRef::Ptr> _factoryServices;
    std::unordered_set<std::string> _factoryTypes;
    std::atomic<bool> _stopping{false};
    std::mutex _recoveryMutex;
    std::condition_variable _recoveryChanged;
    std::thread _recoveryThread;
    std::mutex _protocolMutex;
};
}

POCO_BEGIN_MANIFEST(Poco::OSP::BundleActivator)
    POCO_EXPORT_CLASS(PocoDDS::Services::ProtocolGatewayActivator)
POCO_END_MANIFEST
