#include "IoT/NetworkEnvironment/NetworkEnvironmentServiceImpl.h"
#include "PocoDDS/DDS/ServiceEndpoint.h"

#include <Poco/ClassLibrary.h>
#include <Poco/Delegate.h>
#include <Poco/JSON/Array.h>
#include <Poco/JSON/Object.h>
#include <Poco/JSON/Parser.h>
#include <Poco/OSP/Bundle.h>
#include <Poco/OSP/BundleActivator.h>
#include <Poco/OSP/BundleContext.h>
#include <Poco/OSP/PreferencesService.h>
#include <Poco/OSP/Properties.h>
#include <Poco/OSP/ServiceFinder.h>
#include <Poco/OSP/ServiceRef.h>
#include <Poco/OSP/ServiceRegistry.h>

#include <memory>
#include <sstream>

namespace IoT::NetworkEnvironment
{
namespace
{
Poco::JSON::Object::Ptr parsePayload(const std::string& value)
{
    if (value.empty())
        return new Poco::JSON::Object;
    return Poco::JSON::Parser().parse(value).extract<Poco::JSON::Object::Ptr>();
}

std::string stringify(const Poco::JSON::Object::Ptr& object)
{
    std::ostringstream stream;
    object->stringify(stream);
    return stream.str();
}

Poco::JSON::Object::Ptr toJson(const NetworkInterface& interface)
{
    auto result = new Poco::JSON::Object;
    result->set("index", interface.index);
    result->set("name", interface.name);
    result->set("displayName", interface.displayName);
    result->set("adapterName", interface.adapterName);
    result->set("macAddress", interface.macAddress);
    result->set("mtu", interface.mtu);
    result->set("isUp", interface.isUp);
    result->set("isRunning", interface.isRunning);
    result->set("isLoopback", interface.isLoopback);
    Poco::JSON::Array::Ptr addresses = new Poco::JSON::Array;
    for (const auto& address : interface.addresses)
    {
        Poco::JSON::Object::Ptr item = new Poco::JSON::Object;
        item->set("version", address.version);
        item->set("address", address.address);
        item->set("subnetMask", address.subnetMask);
        item->set("broadcastOrDestinationAddress",
                  address.broadcastOrDestinationAddress);
        addresses->add(item);
    }
    result->set("addresses", addresses);
    return result;
}
} // namespace

class BundleActivator final : public Poco::OSP::BundleActivator
{
public:
    void start(Poco::OSP::BundleContext::Ptr context) override
    {
        _service = new NetworkEnvironmentServiceImpl;
        Poco::OSP::Properties properties;
        properties.set("pdr.service", "network");
        properties.set("pdr.bundle", context->thisBundle()->symbolicName());
        _serviceRef = context->registry().registerService(
            "pdr.service.network", _service, properties);

        const auto configuration =
            Poco::OSP::ServiceFinder::find<Poco::OSP::PreferencesService>(context)
                ->configuration();
        const auto domainId =
            static_cast<std::uint32_t>(configuration->getUInt("pdr.fastdds.domainId", 0));
        _endpoint = std::make_unique<PocoDDS::FastDDS::ServiceEndpoint>(
            domainId,
            "pdr-network-service",
            "pdr.network.request",
            "pdr.network.response",
            "pdr.network.environment");
        _endpoint->start([this](const PocoDDS::FastDDS::Envelope& request) {
            PocoDDS::FastDDS::Envelope response;
            auto payload = parsePayload(request.payload);
            auto result = new Poco::JSON::Object;
            if (request.operation == "findActive")
            {
                const auto version = payload->optValue<int>("version", 0);
                result->set("interface", _service->findActiveNetworkInterface(
                    version == 4 ? IPv4_ONLY : version == 6 ? IPv6_ONLY : IPv4_OR_IPv6));
            }
            else if (request.operation == "enumerate")
            {
                Poco::JSON::Array::Ptr interfaces = new Poco::JSON::Array;
                for (const auto& item :
                     _service->enumerateInterfaces(payload->optValue<int>("options", 0)))
                    interfaces->add(toJson(item));
                result->set("interfaces", interfaces);
            }
            else
            {
                response.status = 400;
                result->set("error", "unsupported operation");
            }
            response.payload = stringify(result);
            return response;
        });
        _service->networkEnvironmentChanged +=
            Poco::delegate(this, &BundleActivator::handleNetworkChange);
        context->logger().information("NetworkEnvironment OSP/Fast DDS service started.");
    }

    void stop(Poco::OSP::BundleContext::Ptr context) override
    {
        if (_service)
            _service->networkEnvironmentChanged -=
                Poco::delegate(this, &BundleActivator::handleNetworkChange);
        if (_endpoint)
            _endpoint->stop();
        _endpoint.reset();
        if (_serviceRef)
            context->registry().unregisterService(_serviceRef);
        _serviceRef = nullptr;
        _service = nullptr;
    }

private:
    void handleNetworkChange(const void*, const ChangeType& change)
    {
        auto event = new Poco::JSON::Object;
        event->set("changeType", static_cast<int>(change));
        _endpoint->publishEvent("changed", stringify(event));
    }

    NetworkEnvironmentServiceImpl::Ptr _service;
    Poco::OSP::ServiceRef::Ptr _serviceRef;
    std::unique_ptr<PocoDDS::FastDDS::ServiceEndpoint> _endpoint;
};
} // namespace IoT::NetworkEnvironment

POCO_BEGIN_MANIFEST(Poco::OSP::BundleActivator)
POCO_EXPORT_CLASS(IoT::NetworkEnvironment::BundleActivator)
POCO_END_MANIFEST
