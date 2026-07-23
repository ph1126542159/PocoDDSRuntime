#include "IoT/DeviceStatus/DeviceStatusServiceImpl.h"
#include "PocoDDS/DDS/ServiceEndpoint.h"

#include <Poco/ClassLibrary.h>
#include <Poco/Data/SQLite/Connector.h>
#include <Poco/DateTimeFormat.h>
#include <Poco/DateTimeFormatter.h>
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

namespace IoT::DeviceStatus
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

Poco::JSON::Object::Ptr messageJson(const StatusMessage& message)
{
    auto result = new Poco::JSON::Object;
    result->set("id", message.id);
    result->set("messageClass", message.messageClass);
    result->set("source", message.source);
    result->set("status", static_cast<int>(message.status));
    result->set("text", message.text);
    result->set("timestamp", Poco::DateTimeFormatter::format(
                                 message.timestamp, Poco::DateTimeFormat::ISO8601_FORMAT));
    result->set("acknowledgeable", message.acknowledgeable);
    result->set("acknowledged", message.acknowledged);
    return result;
}

Poco::JSON::Object::Ptr changeJson(const DeviceStatusChange& change)
{
    auto result = new Poco::JSON::Object;
    result->set("previousStatus", static_cast<int>(change.previousStatus));
    result->set("currentStatus", static_cast<int>(change.currentStatus));
    if (change.message.isSpecified())
        result->set("message", messageJson(change.message.value()));
    return result;
}
} // namespace

class BundleActivator final : public Poco::OSP::BundleActivator
{
public:
    void start(Poco::OSP::BundleContext::Ptr context) override
    {
        Poco::Data::SQLite::Connector::registerConnector();
        const auto configuration =
            Poco::OSP::ServiceFinder::find<Poco::OSP::PreferencesService>(context)
                ->configuration();
        _service = new DeviceStatusServiceImpl(
            context, configuration->getInt("deviceStatus.messages.maxAge", 30 * 24));
        Poco::OSP::Properties properties;
        properties.set("pdr.service", "deviceStatus");
        properties.set("pdr.bundle", context->thisBundle()->symbolicName());
        _serviceRef = context->registry().registerService(
            "pdr.service.deviceStatus", _service, properties);

        const auto domainId =
            static_cast<std::uint32_t>(configuration->getUInt("pdr.fastdds.domainId", 0));
        _endpoint = std::make_unique<PocoDDS::FastDDS::ServiceEndpoint>(
            domainId,
            "pdr-device-status-service",
            "pdr.status.request",
            "pdr.status.response",
            "pdr.device.status");
        _endpoint->start([this](const PocoDDS::FastDDS::Envelope& request) {
            PocoDDS::FastDDS::Envelope response;
            auto payload = parsePayload(request.payload);
            Poco::JSON::Object::Ptr result = new Poco::JSON::Object;
            if (request.operation == "status")
                result->set("status", static_cast<int>(_service->status()));
            else if (request.operation == "statusOfSource")
                result->set("status", static_cast<int>(_service->statusOfSource(
                                          payload->getValue<std::string>("source"))));
            else if (request.operation == "post")
            {
                StatusUpdate update;
                update.messageClass = payload->optValue<std::string>("messageClass", "");
                update.source = payload->optValue<std::string>("source", "");
                update.status = static_cast<DeviceStatus>(payload->getValue<int>("status"));
                update.text = payload->getValue<std::string>("text");
                update.acknowledgeable =
                    payload->optValue<bool>("acknowledgeable", true);
                const auto change = _service->postStatus(update);
                result = changeJson(change);
            }
            else if (request.operation == "clear")
                result->set("status", static_cast<int>(_service->clearStatus(
                                          payload->getValue<std::string>("messageClass"))));
            else if (request.operation == "clearSource")
                result->set("status", static_cast<int>(_service->clearStatusOfSource(
                                          payload->getValue<std::string>("source"))));
            else if (request.operation == "acknowledge")
                result->set("status", static_cast<int>(_service->acknowledge(
                                          payload->getValue<Poco::Int64>("id"))));
            else if (request.operation == "acknowledgeUpTo")
                result->set("status", static_cast<int>(_service->acknowledgeUpTo(
                                          payload->getValue<Poco::Int64>("id"))));
            else if (request.operation == "remove")
                result->set("status", static_cast<int>(_service->remove(
                                          payload->getValue<Poco::Int64>("id"))));
            else if (request.operation == "messages")
            {
                Poco::JSON::Array::Ptr messages = new Poco::JSON::Array;
                for (const auto& message :
                     _service->messages(payload->optValue<int>("maxMessages", 0)))
                    messages->add(messageJson(message));
                result->set("messages", messages);
            }
            else if (request.operation == "reset")
            {
                _service->reset();
                result->set("status", static_cast<int>(DEVICE_STATUS_OK));
            }
            else
            {
                response.status = 400;
                result->set("error", "unsupported operation");
            }
            response.payload = stringify(result);
            return response;
        });
        _service->statusUpdated += Poco::delegate(this, &BundleActivator::handleStatus);
        context->logger().information("DeviceStatus OSP/Fast DDS service started.");
    }

    void stop(Poco::OSP::BundleContext::Ptr context) override
    {
        if (_service)
            _service->statusUpdated -= Poco::delegate(this, &BundleActivator::handleStatus);
        if (_endpoint)
            _endpoint->stop();
        _endpoint.reset();
        if (_serviceRef)
            context->registry().unregisterService(_serviceRef);
        _serviceRef = nullptr;
        _service = nullptr;
        Poco::Data::SQLite::Connector::unregisterConnector();
    }

private:
    void handleStatus(const void*, const DeviceStatusChange& change)
    {
        _endpoint->publishEvent("updated", stringify(changeJson(change)));
    }

    DeviceStatusServiceImpl::Ptr _service;
    Poco::OSP::ServiceRef::Ptr _serviceRef;
    std::unique_ptr<PocoDDS::FastDDS::ServiceEndpoint> _endpoint;
};
} // namespace IoT::DeviceStatus

POCO_BEGIN_MANIFEST(Poco::OSP::BundleActivator)
POCO_EXPORT_CLASS(IoT::DeviceStatus::BundleActivator)
POCO_END_MANIFEST
