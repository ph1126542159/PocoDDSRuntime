#include "PocoDDS/Gateways/FactoryService.h"
#include "PocoDDS/Protocols/MQTT/MqttClient.h"
#include "PocoDDS/Protocols/ROS/BridgeClient.h"
#include "PocoDDS/Protocols/UDP/UdpChannel.h"

#include <Poco/AutoPtr.h>
#include <Poco/ClassLibrary.h>
#include <Poco/Environment.h>
#include <Poco/Exception.h>
#include <Poco/Net/SocketAddress.h>
#include <Poco/OSP/BundleActivator.h>
#include <Poco/OSP/BundleContext.h>
#include <Poco/OSP/Properties.h>
#include <Poco/OSP/ServiceRef.h>
#include <Poco/OSP/ServiceRegistry.h>
#include <Poco/URI.h>

#include <cstddef>
#include <memory>
#include <string>
#include <utility>
#include <vector>

namespace PocoDDS::Services
{
namespace
{
using PocoDDS::Gateways::FactoryDescriptor;
using PocoDDS::Gateways::FactoryInstance;
using PocoDDS::Gateways::ProtocolFactoryService;

std::string key(const FactoryInstance& instance, const char* name)
{
    return instance.prefix + "." + name;
}

std::string environmentBackedValue(
    const Poco::Util::AbstractConfiguration& configuration,
    const FactoryInstance& instance,
    const char* name)
{
    const std::string directKey = key(instance, name);
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

class MqttFactory final : public ProtocolFactoryService
{
public:
    FactoryDescriptor descriptor() const override
    {
        return {"mqtt", "pdr.mqtt", "mqtt", false, 0};
    }

    std::unique_ptr<PocoDDS::Protocols::DiagnosticProtocol> create(
        const Poco::Util::AbstractConfiguration& configuration,
        const FactoryInstance& instance) const override
    {
        PocoDDS::Protocols::MQTT::MqttClient::Options options;
        options.serverUri = configuration.getString(key(instance, "serverUri"));
        options.clientId = configuration.getString(key(instance, "clientId"), instance.id);
        options.username = environmentBackedValue(configuration, instance, "username");
        options.password = environmentBackedValue(configuration, instance, "password");
        options.trustStore = configuration.getString(key(instance, "trustStore"), "");
        options.keyStore = configuration.getString(key(instance, "keyStore"), "");
        options.privateKey = configuration.getString(key(instance, "privateKey"), "");
        options.privateKeyPassword =
            environmentBackedValue(configuration, instance, "privateKeyPassword");
        options.enabledCipherSuites =
            configuration.getString(key(instance, "enabledCipherSuites"), "");
        options.verifyServerCertificate =
            configuration.getBool(key(instance, "verifyServerCertificate"), true);
        options.verifyHostname = configuration.getBool(key(instance, "verifyHostname"), true);
        options.keepAliveSeconds = configuration.getInt(key(instance, "keepAliveSeconds"), 30);
        options.cleanSession = configuration.getBool(key(instance, "cleanSession"), true);
        options.connectTimeoutSeconds =
            configuration.getInt(key(instance, "connectTimeoutSeconds"), 10);
        return std::make_unique<PocoDDS::Protocols::MQTT::MqttClient>(std::move(options));
    }
};

class RosFactory final : public ProtocolFactoryService
{
public:
    FactoryDescriptor descriptor() const override
    {
        return {"rosbridge", "pdr.ros", "ros", false, 0};
    }

    std::unique_ptr<PocoDDS::Protocols::DiagnosticProtocol> create(
        const Poco::Util::AbstractConfiguration& configuration,
        const FactoryInstance& instance) const override
    {
        PocoDDS::Protocols::ROS::BridgeClient::Options options;
        options.uri = Poco::URI(configuration.getString(key(instance, "uri")));
        options.maximumMessageSize = static_cast<std::size_t>(
            configuration.getUInt(key(instance, "maximumMessageSize"), 1024 * 1024));
        options.connectTimeoutSeconds =
            configuration.getInt(key(instance, "connectTimeoutSeconds"), 10);
        options.authorization = environmentBackedValue(configuration, instance, "authorization");
        options.trustStore = configuration.getString(key(instance, "trustStore"), "");
        options.clientCertificate =
            configuration.getString(key(instance, "clientCertificate"), "");
        options.privateKey = configuration.getString(key(instance, "privateKey"), "");
        options.verifyServerCertificate =
            configuration.getBool(key(instance, "verifyServerCertificate"), true);
        options.verifyHostname = configuration.getBool(key(instance, "verifyHostname"), true);
        return std::make_unique<PocoDDS::Protocols::ROS::BridgeClient>(std::move(options));
    }
};

class UdpFactory final : public ProtocolFactoryService
{
public:
    FactoryDescriptor descriptor() const override
    {
        return {"udp", "pdr.udp", "udp", false, 0};
    }

    std::unique_ptr<PocoDDS::Protocols::DiagnosticProtocol> create(
        const Poco::Util::AbstractConfiguration& configuration,
        const FactoryInstance& instance) const override
    {
        PocoDDS::Protocols::UDP::UdpChannel::Options options{
            Poco::Net::SocketAddress(
                configuration.getString(key(instance, "localHost"), "127.0.0.1"),
                static_cast<Poco::UInt16>(
                    configuration.getUInt(key(instance, "localPort"), 0))),
            Poco::Net::SocketAddress(
                configuration.getString(key(instance, "remoteHost"), "127.0.0.1"),
                static_cast<Poco::UInt16>(
                    configuration.getUInt(key(instance, "remotePort"), 9)))};
        return std::make_unique<PocoDDS::Protocols::UDP::UdpChannel>(std::move(options));
    }
};
}

class BuiltinProtocolFactoriesActivator final : public Poco::OSP::BundleActivator
{
public:
    void start(Poco::OSP::BundleContext::Ptr context) override
    {
        try
        {
            registerFactory(context, new MqttFactory);
            registerFactory(context, new RosFactory);
            registerFactory(context, new UdpFactory);
        }
        catch (...)
        {
            stop(context);
            throw;
        }
    }

    void stop(Poco::OSP::BundleContext::Ptr context) override
    {
        for (auto iterator = _references.rbegin(); iterator != _references.rend(); ++iterator)
            context->registry().unregisterService(*iterator);
        _references.clear();
        _factories.clear();
    }

private:
    void registerFactory(Poco::OSP::BundleContext::Ptr context,
                         ProtocolFactoryService* factory)
    {
        Poco::AutoPtr<ProtocolFactoryService> owned(factory);
        const auto descriptor = factory->descriptor();
        Poco::OSP::Properties properties;
        properties.set(ProtocolFactoryService::PROPERTY_KIND,
                       ProtocolFactoryService::FACTORY_KIND);
        properties.set(ProtocolFactoryService::PROPERTY_TYPE, descriptor.type);
        _references.push_back(context->registry().registerService(
            "pdr.protocolFactory." + descriptor.type, owned, properties));
        _factories.push_back(std::move(owned));
    }

    std::vector<Poco::AutoPtr<ProtocolFactoryService>> _factories;
    std::vector<Poco::OSP::ServiceRef::Ptr> _references;
};
}

POCO_BEGIN_MANIFEST(Poco::OSP::BundleActivator)
    POCO_EXPORT_CLASS(PocoDDS::Services::BuiltinProtocolFactoriesActivator)
POCO_END_MANIFEST
