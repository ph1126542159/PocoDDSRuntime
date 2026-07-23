#include "IoT/UnitsOfMeasure/UCUMEssenceParser.h"
#include "IoT/UnitsOfMeasure/UnitsOfMeasureServiceImpl.h"
#include "PocoDDS/DDS/ServiceEndpoint.h"

#include <Poco/ClassLibrary.h>
#include <Poco/Dynamic/Var.h>
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

namespace IoT::UnitsOfMeasure
{
namespace
{
Poco::JSON::Object::Ptr parsePayload(const std::string& payload)
{
    if (payload.empty())
        return new Poco::JSON::Object;
    return Poco::JSON::Parser().parse(payload).extract<Poco::JSON::Object::Ptr>();
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
        _service = new UnitsOfMeasureServiceImpl;
        UCUMEssenceParser parser(*_service);
        std::unique_ptr<std::istream> input(
            context->thisBundle()->getResource("ucum-essence.xml"));
        parser.parse(*input);

        Poco::OSP::Properties properties;
        properties.set("pdr.service", "units");
        properties.set("pdr.bundle", context->thisBundle()->symbolicName());
        _serviceRef = context->registry().registerService(
            "pdr.service.units", _service, properties);

        const auto configuration =
            Poco::OSP::ServiceFinder::find<Poco::OSP::PreferencesService>(context)
                ->configuration();
        const auto domainId =
            static_cast<std::uint32_t>(configuration->getUInt("pdr.fastdds.domainId", 0));
        _endpoint = std::make_unique<PocoDDS::FastDDS::ServiceEndpoint>(
            domainId,
            "pdr-units-service",
            "pdr.units.request",
            "pdr.units.response");
        _endpoint->start([this](const PocoDDS::FastDDS::Envelope& request) {
            PocoDDS::FastDDS::Envelope response;
            auto payload = parsePayload(request.payload);
            auto result = new Poco::JSON::Object;
            if (request.operation == "format")
            {
                result->set("value", _service->format(payload->getValue<std::string>("code")));
            }
            else if (request.operation == "canonicalize")
            {
                const auto value = _service->canonicalize(
                    payload->getValue<double>("value"),
                    payload->getValue<std::string>("code"));
                result->set("value", value.value);
                result->set("code", value.code);
            }
            else if (request.operation == "convert")
            {
                result->set("value", _service->convert(
                    payload->getValue<double>("value"),
                    payload->getValue<std::string>("from"),
                    payload->getValue<std::string>("to")));
            }
            else if (request.operation == "findUnit")
            {
                const auto unit = _service->findUnit(payload->getValue<std::string>("code"));
                if (!unit)
                {
                    response.status = 404;
                    result->set("found", false);
                }
                else
                {
                    result->set("found", true);
                    result->set("code", unit->code);
                    result->set("name", unit->name);
                    result->set("print", unit->print);
                    result->set("property", unit->property);
                }
            }
            else
            {
                response.status = 400;
                result->set("error", "unsupported operation");
            }
            response.payload = stringify(result);
            return response;
        });
        context->logger().information("UnitsOfMeasure OSP/Fast DDS service started.");
    }

    void stop(Poco::OSP::BundleContext::Ptr context) override
    {
        if (_endpoint)
            _endpoint->stop();
        _endpoint.reset();
        if (_serviceRef)
            context->registry().unregisterService(_serviceRef);
        _serviceRef = nullptr;
        _service = nullptr;
    }

private:
    UnitsOfMeasureServiceImpl::Ptr _service;
    Poco::OSP::ServiceRef::Ptr _serviceRef;
    std::unique_ptr<PocoDDS::FastDDS::ServiceEndpoint> _endpoint;
};
} // namespace IoT::UnitsOfMeasure

POCO_BEGIN_MANIFEST(Poco::OSP::BundleActivator)
POCO_EXPORT_CLASS(IoT::UnitsOfMeasure::BundleActivator)
POCO_END_MANIFEST
