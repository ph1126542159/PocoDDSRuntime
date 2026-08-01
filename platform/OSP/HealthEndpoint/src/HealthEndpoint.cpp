#include "Poco/ClassLibrary.h"
#include "Poco/JSON/Array.h"
#include "Poco/JSON/Object.h"
#include "Poco/Net/HTTPServerRequest.h"
#include "Poco/Net/HTTPServerResponse.h"
#include "Poco/Net/HTTPRequestHandler.h"
#include "Poco/OSP/Bundle.h"
#include "Poco/OSP/BundleContext.h"
#include "Poco/OSP/ServiceRef.h"
#include "Poco/OSP/ServiceRegistry.h"
#include "Poco/OSP/Web/WebRequestHandlerFactory.h"
#include "Poco/URI.h"
#include "PocoDDS/Health/Health.h"
#include "PocoDDS/ProcessManagement/SubprocessManager.h"
#include "PocoDDS/Devices/Device.h"
#include "PocoDDS/Devices/DeviceService.h"

#include <memory>
#include <string>
#include <utility>
#include <vector>

namespace PocoDDS::HealthEndpoint
{
namespace
{
class StaticContributor final : public Health::IHealthContributor
{
public:
    explicit StaticContributor(Health::Report report): _report(std::move(report)) {}
    Health::Report health() const override { return _report; }
private:
    Health::Report _report;
};

const char* statusName(Health::Status status)
{
    switch (status)
    {
    case Health::Status::up: return "UP";
    case Health::Status::degraded: return "DEGRADED";
    case Health::Status::down: return "DOWN";
    }
    return "DOWN";
}

void sendError(Poco::Net::HTTPServerResponse& response,
               Poco::Net::HTTPResponse::HTTPStatus status,
               const std::string& message)
{
    Poco::JSON::Object result;
    result.set("error", message);
    response.setStatus(status);
    response.setContentType("application/json");
    result.stringify(response.send());
}

class HealthHandler final : public Poco::Net::HTTPRequestHandler
{
public:
    explicit HealthHandler(Poco::OSP::BundleContext::Ptr context): _context(std::move(context)) {}

    void handleRequest(Poco::Net::HTTPServerRequest& request,
                       Poco::Net::HTTPServerResponse& response) override
    {
        Health::HealthRegistry registry;
        registry.add(std::make_shared<StaticContributor>(
            Health::Report{"runtime", Health::Status::up, "HTTP server active"}));

        std::vector<Poco::OSP::Bundle::Ptr> bundles;
        _context->listBundles(bundles);
        std::size_t active = 0;
        for (const auto& bundle : bundles)
            if (bundle->state() == Poco::OSP::Bundle::BUNDLE_ACTIVE)
                ++active;
        registry.add(std::make_shared<StaticContributor>(Health::Report{
            "bundles", active > 0 ? Health::Status::up : Health::Status::down,
            std::to_string(active) + "/" + std::to_string(bundles.size()) + " active"}));

        if (auto* manager = ProcessManagement::SubprocessManager::active())
        {
            const auto processes = manager->processes();
            registry.add(std::make_shared<StaticContributor>(Health::Report{
                "subprocesses",
                manager->runningCount() == processes.size() ? Health::Status::up
                                                            : Health::Status::degraded,
                std::to_string(manager->runningCount()) + "/" +
                    std::to_string(processes.size()) + " running"}));
        }

        std::size_t requiredDevices = 0;
        std::size_t readyDevices = 0;
        std::size_t faultDevices = 0;
        for (const auto& service : _context->registry().find("pdr.device"))
        {
            if (!service->properties().getBool("pdr.deviceRequired", true))
                continue;
            ++requiredDevices;
            try
            {
                const auto provider =
                    service->castedInstance<PocoDDS::Devices::DeviceService>();
                const auto state = provider->device().snapshot().state;
                if (state == PocoDDS::Devices::DeviceState::ready)
                    ++readyDevices;
                else if (state == PocoDDS::Devices::DeviceState::fault)
                    ++faultDevices;
            }
            catch (...)
            {
                ++faultDevices;
            }
        }
        if (requiredDevices > 0)
        {
            registry.add(std::make_shared<StaticContributor>(Health::Report{
                "devices",
                readyDevices == requiredDevices ? Health::Status::up
                                                : Health::Status::degraded,
                std::to_string(readyDevices) + "/" +
                    std::to_string(requiredDevices) + " required ready, " +
                    std::to_string(faultDevices) + " fault"}));
        }

        const auto report = registry.collect();
        const std::string path = Poco::URI(request.getURI()).getPath();
        const bool live = path == "/health/live";
        const bool ready = path == "/health/ready";
        if (path != "/health" && path != "/health/" && path != "/health/detail" &&
            !live && !ready)
        {
            sendError(response, Poco::Net::HTTPResponse::HTTP_NOT_FOUND,
                      "unknown health endpoint");
            return;
        }

        Poco::JSON::Object root;
        root.set("status", statusName(report.status));
        root.set("live", report.live());
        root.set("ready", report.ready());
        if (!live && !ready)
        {
            Poco::JSON::Array components;
            for (const auto& component : report.components)
            {
                Poco::JSON::Object item;
                item.set("name", component.component);
                item.set("status", statusName(component.status));
                item.set("detail", component.detail);
                components.add(item);
            }
            root.set("components", components);
        }
        const bool acceptable = live ? report.live() : (ready ? report.ready() : true);
        response.setStatus(acceptable ? Poco::Net::HTTPResponse::HTTP_OK
                                      : Poco::Net::HTTPResponse::HTTP_SERVICE_UNAVAILABLE);
        response.setContentType("application/json; charset=utf-8");
        response.set("Cache-Control", "no-store");
        root.stringify(response.send());
    }

private:
    Poco::OSP::BundleContext::Ptr _context;
};
} // namespace

class HealthHandlerFactory final : public Poco::OSP::Web::WebRequestHandlerFactory
{
public:
    Poco::Net::HTTPRequestHandler* createRequestHandler(
        const Poco::Net::HTTPServerRequest&) override
    {
        return new HealthHandler(context());
    }
};
} // namespace PocoDDS::HealthEndpoint

POCO_BEGIN_NAMED_MANIFEST(WebServer, Poco::OSP::Web::WebRequestHandlerFactory)
    POCO_EXPORT_CLASS(PocoDDS::HealthEndpoint::HealthHandlerFactory)
POCO_END_MANIFEST
