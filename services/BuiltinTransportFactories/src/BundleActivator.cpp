#include "PocoDDS/TransportProviders/TransportFactoryService.h"

#if defined(PDR_HAS_MQTT_TRANSPORT)
#include "PocoDDS/MqttTransport/Registration.h"
#endif
#if defined(PDR_HAS_FASTDDS_TRANSPORT)
#include "PocoDDS/FastDdsTransport/Registration.h"
#endif

#include <Poco/AutoPtr.h>
#include <Poco/ClassLibrary.h>
#include <Poco/OSP/BundleActivator.h>
#include <Poco/OSP/BundleContext.h>
#include <Poco/OSP/Properties.h>
#include <Poco/OSP/ServiceRef.h>
#include <Poco/OSP/ServiceRegistry.h>

#include <functional>
#include <memory>
#include <string>
#include <utility>
#include <vector>

namespace PocoDDS::Services
{
namespace
{
using PocoDDS::RuntimeCore::IMessageTransport;
using PocoDDS::RuntimeCore::Outcome;
using PocoDDS::RuntimeCore::TransportConfiguration;
using PocoDDS::RuntimeCore::TransportDescriptor;
using PocoDDS::TransportProviders::TransportFactoryService;

class BuiltinFactory final : public TransportFactoryService
{
public:
    using Factory = std::function<Outcome<std::shared_ptr<IMessageTransport>>(
        const TransportConfiguration&)>;

    BuiltinFactory(TransportDescriptor descriptor, Factory factory)
        : _descriptor(std::move(descriptor)), _factory(std::move(factory))
    {
    }

    TransportDescriptor descriptor() const override { return _descriptor; }

    Outcome<std::shared_ptr<IMessageTransport>> create(
        const TransportConfiguration& configuration) const override
    {
        return _factory(configuration);
    }

private:
    TransportDescriptor _descriptor;
    Factory _factory;
};
} // namespace

class BuiltinTransportFactoriesActivator final : public Poco::OSP::BundleActivator
{
public:
    void start(Poco::OSP::BundleContext::Ptr context) override
    {
        try
        {
#if defined(PDR_HAS_MQTT_TRANSPORT)
            registerFactory(context,
                new BuiltinFactory(PocoDDS::MqttTransport::mqttTransportDescriptor(),
                                   PocoDDS::MqttTransport::createMqttTransport));
#endif
#if defined(PDR_HAS_FASTDDS_TRANSPORT)
            registerFactory(context,
                new BuiltinFactory(PocoDDS::FastDdsTransport::fastDdsTransportDescriptor(),
                                   PocoDDS::FastDdsTransport::createFastDdsTransport));
#endif
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
                         TransportFactoryService* factory)
    {
        Poco::AutoPtr<TransportFactoryService> owned(factory);
        const auto descriptor = factory->descriptor();
        Poco::OSP::Properties properties;
        properties.set(TransportFactoryService::PROPERTY_KIND,
                       TransportFactoryService::FACTORY_KIND);
        properties.set(TransportFactoryService::PROPERTY_TYPE, descriptor.id);
        _references.push_back(context->registry().registerService(
            "pdr.transportFactory." + descriptor.id, owned, properties));
        _factories.push_back(std::move(owned));
    }

    std::vector<Poco::AutoPtr<TransportFactoryService>> _factories;
    std::vector<Poco::OSP::ServiceRef::Ptr> _references;
};
} // namespace PocoDDS::Services

POCO_BEGIN_MANIFEST(Poco::OSP::BundleActivator)
    POCO_EXPORT_CLASS(PocoDDS::Services::BuiltinTransportFactoriesActivator)
POCO_END_MANIFEST
