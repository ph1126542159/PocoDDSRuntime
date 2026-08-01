#include "PocoDDS/Configuration/IndexedConfiguration.h"
#include "PocoDDS/Protocols/MQTT/MqttClient.h"
#include "PocoDDS/Protocols/ProtocolService.h"
#include "PocoDDS/Protocols/ROS/BridgeClient.h"
#include "PocoDDS/Protocols/UDP/UdpChannel.h"

#include <Poco/ClassLibrary.h>
#include <Poco/Environment.h>
#include <Poco/Net/SocketAddress.h>
#include <Poco/OSP/Bundle.h>
#include <Poco/OSP/BundleActivator.h>
#include <Poco/OSP/BundleContext.h>
#include <Poco/OSP/PreferencesService.h>
#include <Poco/OSP/Properties.h>
#include <Poco/OSP/ServiceFinder.h>
#include <Poco/OSP/ServiceRef.h>
#include <Poco/OSP/ServiceRegistry.h>
#include <Poco/URI.h>

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
namespace
{
std::string environmentBackedValue(
    const Poco::Util::AbstractConfiguration& configuration,
    const std::string& prefix,
    const char* name)
{
    const std::string directKey = prefix + "." + name;
    const std::string environmentKey = directKey + "Environment";
    const std::string direct = configuration.getString(directKey, "");
    const std::string variable = configuration.getString(environmentKey, "");
    if (!direct.empty() && !variable.empty())
        throw Poco::InvalidArgumentException(
            directKey + " and " + environmentKey + " are mutually exclusive");
    if (variable.empty()) return direct;
    if (!Poco::Environment::has(variable))
        throw Poco::NotFoundException(
            "Environment variable configured by " + environmentKey + " is not set", variable);
    const std::string value = Poco::Environment::get(variable);
    if (value.empty())
        throw Poco::InvalidArgumentException(
            "Environment variable configured by " + environmentKey + " is empty", variable);
    return value;
}
}

class ProtocolGatewayActivator final : public Poco::OSP::BundleActivator
{
public:
    void start(Poco::OSP::BundleContext::Ptr context) override
    {
        auto preferences =
            Poco::OSP::ServiceFinder::find<Poco::OSP::PreferencesService>(context);
        auto configuration = preferences->configuration();
        const auto instances = [&](const std::string& base, const std::string& idPrefix) {
            return PocoDDS::Configuration::indexedInstances(
                *configuration, base, false, 0, idPrefix);
        };
        const auto key = [](const auto& instance, const char* name) {
            return instance.prefix + "." + name;
        };

        try
        {
            for (const auto& instance : instances("pdr.mqtt", "mqtt"))
            {
                if (!instance.enabled) continue;
                PocoDDS::Protocols::MQTT::MqttClient::Options options;
                options.serverUri = configuration->getString(key(instance, "serverUri"));
                options.clientId = configuration->getString(key(instance, "clientId"), instance.id);
                options.username = environmentBackedValue(
                    *configuration, instance.prefix, "username");
                options.password = environmentBackedValue(
                    *configuration, instance.prefix, "password");
                options.trustStore = configuration->getString(key(instance, "trustStore"), "");
                options.keyStore = configuration->getString(key(instance, "keyStore"), "");
                options.privateKey = configuration->getString(key(instance, "privateKey"), "");
                options.privateKeyPassword = environmentBackedValue(
                    *configuration, instance.prefix, "privateKeyPassword");
                options.enabledCipherSuites =
                    configuration->getString(key(instance, "enabledCipherSuites"), "");
                options.verifyServerCertificate =
                    configuration->getBool(key(instance, "verifyServerCertificate"), true);
                options.verifyHostname =
                    configuration->getBool(key(instance, "verifyHostname"), true);
                options.keepAliveSeconds = configuration->getInt(key(instance, "keepAliveSeconds"), 30);
                options.cleanSession = configuration->getBool(key(instance, "cleanSession"), true);
                options.connectTimeoutSeconds =
                    configuration->getInt(key(instance, "connectTimeoutSeconds"), 10);
                add(context, instance.id, "mqtt",
                    configuration->getBool(key(instance, "required"), false),
                    configuration->getBool(key(instance, "autoReconnect"), true),
                    configuration->getUInt(key(instance, "reconnectDelayMilliseconds"), 1000),
                    configuration->getUInt(key(instance, "reconnectMaximumDelayMilliseconds"), 30000),
                    std::make_unique<PocoDDS::Protocols::MQTT::MqttClient>(std::move(options)));
            }

            for (const auto& instance : instances("pdr.ros", "ros"))
            {
                if (!instance.enabled) continue;
                PocoDDS::Protocols::ROS::BridgeClient::Options options;
                options.uri = Poco::URI(configuration->getString(key(instance, "uri")));
                options.maximumMessageSize = static_cast<std::size_t>(
                    configuration->getUInt(key(instance, "maximumMessageSize"), 1024 * 1024));
                options.connectTimeoutSeconds =
                    configuration->getInt(key(instance, "connectTimeoutSeconds"), 10);
                options.authorization = environmentBackedValue(
                    *configuration, instance.prefix, "authorization");
                options.trustStore = configuration->getString(key(instance, "trustStore"), "");
                options.clientCertificate =
                    configuration->getString(key(instance, "clientCertificate"), "");
                options.privateKey =
                    configuration->getString(key(instance, "privateKey"), "");
                options.verifyServerCertificate =
                    configuration->getBool(key(instance, "verifyServerCertificate"), true);
                options.verifyHostname =
                    configuration->getBool(key(instance, "verifyHostname"), true);
                add(context, instance.id, "rosbridge",
                    configuration->getBool(key(instance, "required"), false),
                    configuration->getBool(key(instance, "autoReconnect"), true),
                    configuration->getUInt(key(instance, "reconnectDelayMilliseconds"), 1000),
                    configuration->getUInt(key(instance, "reconnectMaximumDelayMilliseconds"), 30000),
                    std::make_unique<PocoDDS::Protocols::ROS::BridgeClient>(std::move(options)));
            }

            for (const auto& instance : instances("pdr.udp", "udp"))
            {
                if (!instance.enabled) continue;
                PocoDDS::Protocols::UDP::UdpChannel::Options options{
                    Poco::Net::SocketAddress(
                        configuration->getString(key(instance, "localHost"), "127.0.0.1"),
                        static_cast<Poco::UInt16>(configuration->getUInt(key(instance, "localPort"), 0))),
                    Poco::Net::SocketAddress(
                        configuration->getString(key(instance, "remoteHost"), "127.0.0.1"),
                        static_cast<Poco::UInt16>(configuration->getUInt(key(instance, "remotePort"), 9)))};
                add(context, instance.id, "udp",
                    configuration->getBool(key(instance, "required"), false),
                    configuration->getBool(key(instance, "autoReconnect"), true),
                    configuration->getUInt(key(instance, "reconnectDelayMilliseconds"), 1000),
                    configuration->getUInt(key(instance, "reconnectMaximumDelayMilliseconds"), 30000),
                    std::make_unique<PocoDDS::Protocols::UDP::UdpChannel>(std::move(options)));
            }

            context->logger().information(
                "Protocol gateway started with " + std::to_string(_protocols.size()) +
                " protocol instance(s).");
            if (std::any_of(_recoveries.begin(), _recoveries.end(),
                            [](const auto& recovery) { return recovery.enabled; }))
            {
                _stopping = false;
                _recoveryThread = std::thread([this, context] { recoveryLoop(context); });
            }
        }
        catch (...)
        {
            stop(context);
            throw;
        }
    }

    void stop(Poco::OSP::BundleContext::Ptr context) override
    {
        _stopping = true;
        _recoveryChanged.notify_all();
        if (_recoveryThread.joinable()) _recoveryThread.join();
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
        _recoveries.clear();
        _ids.clear();
    }

private:
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
    std::atomic<bool> _stopping{false};
    std::mutex _recoveryMutex;
    std::condition_variable _recoveryChanged;
    std::thread _recoveryThread;
};
}

POCO_BEGIN_MANIFEST(Poco::OSP::BundleActivator)
    POCO_EXPORT_CLASS(PocoDDS::Services::ProtocolGatewayActivator)
POCO_END_MANIFEST
