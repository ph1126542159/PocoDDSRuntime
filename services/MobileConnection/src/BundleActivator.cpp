#include "IoT/MobileConnection/Legato/MobileConnectionServiceImpl.h"
#include "IoT/MobileConnection/MemoryMobileConnectionService.h"
#include "PocoDDS/DDS/ServiceEndpoint.h"

#include <Poco/ClassLibrary.h>
#include <Poco/Delegate.h>
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

namespace IoT::MobileConnection
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
} // namespace

class BundleActivator final : public Poco::OSP::BundleActivator
{
public:
    void start(Poco::OSP::BundleContext::Ptr context) override
    {
        const auto configuration =
            Poco::OSP::ServiceFinder::find<Poco::OSP::PreferencesService>(context)
                ->configuration();
        const auto backend = configuration->getString("mobile.backend", "memory");
        if (backend == "legato")
            _service = new Legato::MobileConnectionServiceImpl(
                configuration->getString(
                    "mobile.legato.cmPath",
                    Legato::MobileConnectionServiceImpl::DEFAULT_CM_PATH));
        else if (backend == "memory")
            _service = new MemoryMobileConnectionService;
        else
            throw Poco::InvalidArgumentException("Unsupported mobile.backend", backend);

        Poco::OSP::Properties properties;
        properties.set("pdr.service", "mobile");
        properties.set("pdr.bundle", context->thisBundle()->symbolicName());
        properties.set("pdr.backend", backend);
        _serviceRef = context->registry().registerService(
            "pdr.service.mobile", _service, properties);

        _endpoint = std::make_unique<PocoDDS::FastDDS::ServiceEndpoint>(
            static_cast<std::uint32_t>(
                configuration->getUInt("pdr.fastdds.domainId", 0)),
            "pdr-mobile-service",
            "pdr.mobile.request",
            "pdr.mobile.response",
            "pdr.mobile.state");
        _endpoint->start([this](const PocoDDS::FastDDS::Envelope& request) {
            PocoDDS::FastDDS::Envelope response;
            auto payload = parsePayload(request.payload);
            auto result = new Poco::JSON::Object;
            if (request.operation == "state")
            {
                result->set("deviceName", _service->deviceName());
                result->set("radioEnabled", _service->isRadioEnabled());
                result->set("dataConnected", _service->isDataConnected());
                result->set("simState", static_cast<int>(_service->simState()));
                result->set("registrationStatus",
                            static_cast<int>(_service->registrationStatus()));
                result->set("radioAccessTechnology",
                            static_cast<int>(_service->radioAccessTechnology()));
                result->set("signalStrength", _service->signalStrength());
                result->set("networkOperator", _service->networkOperator());
                result->set("apn", _service->getAPN());
                result->set("pdpType", static_cast<int>(_service->getPDPType()));
            }
            else if (request.operation == "enableRadio")
            {
                _service->enableRadio(payload->getValue<bool>("enabled"));
                result->set("radioEnabled", _service->isRadioEnabled());
            }
            else if (request.operation == "setAPN")
            {
                _service->setAPN(payload->getValue<std::string>("apn"));
                result->set("apn", _service->getAPN());
            }
            else if (request.operation == "setPDPType")
            {
                _service->setPDPType(
                    static_cast<PDPType>(payload->getValue<int>("type")));
                result->set("pdpType", static_cast<int>(_service->getPDPType()));
            }
            else if (request.operation == "authenticate")
            {
                _service->authenticate(
                    static_cast<AuthMethod>(payload->getValue<int>("method")),
                    payload->optValue<std::string>("username", ""),
                    payload->optValue<std::string>("password", ""));
                result->set("accepted", true);
            }
            else if (request.operation == "enterPIN")
            {
                _service->enterPIN(payload->getValue<std::string>("pin"));
                result->set("accepted", true);
            }
            else if (request.operation == "connect")
            {
                _service->connectData();
                result->set("dataConnected", _service->isDataConnected());
            }
            else if (request.operation == "disconnect")
            {
                _service->disconnectData();
                result->set("dataConnected", _service->isDataConnected());
            }
            else
            {
                response.status = 400;
                result->set("error", "unsupported operation");
            }
            response.payload = stringify(result);
            return response;
        });
        _service->dataConnected += Poco::delegate(this, &BundleActivator::handleConnected);
        _service->dataDisconnected +=
            Poco::delegate(this, &BundleActivator::handleDisconnected);
        context->logger().information(
            "MobileConnection OSP/Fast DDS service started with %s backend.", backend);
    }

    void stop(Poco::OSP::BundleContext::Ptr context) override
    {
        if (_service)
        {
            _service->dataConnected -=
                Poco::delegate(this, &BundleActivator::handleConnected);
            _service->dataDisconnected -=
                Poco::delegate(this, &BundleActivator::handleDisconnected);
        }
        if (_endpoint)
            _endpoint->stop();
        _endpoint.reset();
        if (_serviceRef)
            context->registry().unregisterService(_serviceRef);
        _serviceRef = nullptr;
        _service = nullptr;
    }

private:
    void handleConnected(const void*)
    {
        _endpoint->publishEvent("connected", "{\"connected\":true}");
    }

    void handleDisconnected(const void*)
    {
        _endpoint->publishEvent("disconnected", "{\"connected\":false}");
    }

    MobileConnectionService::Ptr _service;
    Poco::OSP::ServiceRef::Ptr _serviceRef;
    std::unique_ptr<PocoDDS::FastDDS::ServiceEndpoint> _endpoint;
};
} // namespace IoT::MobileConnection

POCO_BEGIN_MANIFEST(Poco::OSP::BundleActivator)
POCO_EXPORT_CLASS(IoT::MobileConnection::BundleActivator)
POCO_END_MANIFEST
