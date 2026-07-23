#include "PocoDDS/Services/WebEventService.h"
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

namespace PocoDDS::Services
{
Poco::OSP::Service::Ptr createWebEventService();

namespace
{
std::string stringify(const Poco::JSON::Object::Ptr& object)
{
    std::ostringstream stream;
    object->stringify(stream);
    return stream.str();
}
} // namespace

class WebEventBundleActivator final : public Poco::OSP::BundleActivator
{
public:
    void start(Poco::OSP::BundleContext::Ptr context) override
    {
        auto base = createWebEventService();
        _service = base.cast<WebEventService>();
        Poco::OSP::Properties properties;
        properties.set("pdr.service", "webEvent");
        properties.set("pdr.bundle", context->thisBundle()->symbolicName());
        _serviceRef = context->registry().registerService(
            "pdr.service.webEvent", base, properties);

        const auto configuration =
            Poco::OSP::ServiceFinder::find<Poco::OSP::PreferencesService>(context)
                ->configuration();
        _endpoint = std::make_unique<PocoDDS::FastDDS::ServiceEndpoint>(
            static_cast<std::uint32_t>(
                configuration->getUInt("pdr.fastdds.domainId", 0)),
            "pdr-web-event-service",
            "pdr.web.request",
            "pdr.web.response",
            "pdr.web.event");
        _endpoint->start([this](const PocoDDS::FastDDS::Envelope& request) {
            PocoDDS::FastDDS::Envelope response;
            auto result = new Poco::JSON::Object;
            if (request.operation == "notify")
            {
                auto payload = Poco::JSON::Parser()
                                   .parse(request.payload)
                                   .extract<Poco::JSON::Object::Ptr>();
                _service->notify(payload->getValue<std::string>("subject"),
                                 payload->optValue<std::string>("data", ""));
                result->set("accepted", true);
            }
            else
            {
                response.status = 400;
                result->set("error", "unsupported operation");
            }
            response.payload = stringify(result);
            return response;
        });
        _service->eventPublished +=
            Poco::delegate(this, &WebEventBundleActivator::handleEvent);
        context->logger().information("WebEvent OSP/Fast DDS service started.");
    }

    void stop(Poco::OSP::BundleContext::Ptr context) override
    {
        if (_service)
            _service->eventPublished -=
                Poco::delegate(this, &WebEventBundleActivator::handleEvent);
        if (_endpoint)
            _endpoint->stop();
        _endpoint.reset();
        if (_serviceRef)
            context->registry().unregisterService(_serviceRef);
        _serviceRef = nullptr;
        _service = nullptr;
    }

private:
    void handleEvent(const void*, const WebEvent& event)
    {
        auto payload = new Poco::JSON::Object;
        payload->set("subject", event.subject);
        payload->set("data", event.data);
        _endpoint->publishEvent("notify", stringify(payload));
    }

    Poco::SharedPtr<WebEventService> _service;
    Poco::OSP::ServiceRef::Ptr _serviceRef;
    std::unique_ptr<PocoDDS::FastDDS::ServiceEndpoint> _endpoint;
};
} // namespace PocoDDS::Services

POCO_BEGIN_MANIFEST(Poco::OSP::BundleActivator)
POCO_EXPORT_CLASS(PocoDDS::Services::WebEventBundleActivator)
POCO_END_MANIFEST
