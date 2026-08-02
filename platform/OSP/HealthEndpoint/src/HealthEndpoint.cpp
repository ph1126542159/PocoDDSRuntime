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
#include "PocoDDS/Protocols/ProtocolService.h"
#if defined(PDR_HEALTH_METRICS)
#include "PocoDDS/Observability/Metrics.h"
#endif

#include <algorithm>
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

void addReportJson(Poco::JSON::Array& components, const Health::Report& component)
{
    Poco::JSON::Object item;
    item.set("name", component.component);
    item.set("status", statusName(component.status));
    item.set("detail", component.detail);
    if (!component.code.empty()) item.set("code", component.code);
    if (!component.remediation.empty()) item.set("remediation", component.remediation);
    Poco::JSON::Array affected;
    for (const auto& instance : component.affected) affected.add(instance);
    item.set("affected", affected);
    components.add(item);
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
        const bool bundlesUp = active > 0;
        registry.add(std::make_shared<StaticContributor>(Health::Report{
            "bundles", bundlesUp ? Health::Status::up : Health::Status::down,
            std::to_string(active) + "/" + std::to_string(bundles.size()) + " active",
            bundlesUp ? "" : "PDR-HEALTH-BUNDLE-NONE_ACTIVE",
            bundlesUp ? "" : "Inspect Bundle startup logs and required Bundle dependencies."}));

        if (auto* manager = ProcessManagement::SubprocessManager::active())
        {
            const auto processes = manager->processes();
            const auto required = static_cast<std::size_t>(std::count_if(
                processes.begin(), processes.end(),
                [](const auto& process) { return process.required; }));
            const auto runningRequired = static_cast<std::size_t>(std::count_if(
                processes.begin(), processes.end(), [](const auto& process) {
                    return process.required && process.state == "running";
                }));
            std::vector<std::string> affected;
            for (const auto& process : processes)
                if (process.required && process.state != "running") affected.push_back(process.name);
            const bool requiredRunning = runningRequired == required;
            registry.add(std::make_shared<StaticContributor>(Health::Report{
                "subprocesses",
                requiredRunning ? Health::Status::up : Health::Status::degraded,
                std::to_string(manager->runningCount()) + "/" +
                    std::to_string(processes.size()) + " running, " +
                    std::to_string(runningRequired) + "/" +
                    std::to_string(required) + " required",
                requiredRunning ? "" : "PDR-HEALTH-SUBPROCESS-REQUIRED_NOT_RUNNING",
                requiredRunning ? "" : "Inspect the affected process log, then restart it from process management.",
                std::move(affected)}));
        }
        else
        {
            registry.add(std::make_shared<StaticContributor>(Health::Report{
                "subprocesses", Health::Status::degraded, "manager not initialized",
                "PDR-HEALTH-SUBPROCESS-MANAGER_UNAVAILABLE",
                "Verify ProcessManagement Bundle startup and Runtime configuration."}));
        }

        std::size_t requiredDevices = 0;
        std::size_t readyDevices = 0;
        std::size_t faultDevices = 0;
        std::vector<std::string> affectedDevices;
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
                else
                {
                    if (state == PocoDDS::Devices::DeviceState::fault) ++faultDevices;
                    affectedDevices.push_back(service->properties().get(
                        "pdr.device", service->name()));
                }
            }
            catch (...)
            {
                ++faultDevices;
                affectedDevices.push_back(service->properties().get(
                    "pdr.device", service->name()));
            }
        }
        if (requiredDevices > 0)
        {
            const bool devicesReady = readyDevices == requiredDevices;
            registry.add(std::make_shared<StaticContributor>(Health::Report{
                "devices",
                devicesReady ? Health::Status::up : Health::Status::degraded,
                std::to_string(readyDevices) + "/" +
                    std::to_string(requiredDevices) + " required ready, " +
                    std::to_string(faultDevices) + " fault",
                devicesReady ? "" : "PDR-HEALTH-DEVICE-REQUIRED_NOT_READY",
                devicesReady ? "" : "Open device diagnostics, inspect the last error, then verify wiring and transport.",
                std::move(affectedDevices)}));
        }

        const auto protocolServices = _context->registry().find("pdr.protocol");
        std::size_t openProtocols = 0;
        std::size_t requiredProtocols = 0;
        std::size_t openRequiredProtocols = 0;
        std::vector<std::string> affectedProtocols;
        for (const auto& service : protocolServices)
        {
            const bool required = service->properties().getBool("pdr.protocol.required", false);
            if (required) ++requiredProtocols;
            try
            {
                const auto provider = service->castedInstance<PocoDDS::Protocols::ProtocolService>();
                if (provider->isOpen())
                {
                    ++openProtocols;
                    if (required) ++openRequiredProtocols;
                }
                else if (required)
                    affectedProtocols.push_back(service->properties().get(
                        "pdr.protocol.id", service->name()));
            }
            catch (...)
            {
                if (required) affectedProtocols.push_back(service->properties().get(
                    "pdr.protocol.id", service->name()));
            }
        }
        const bool protocolsReady = openRequiredProtocols == requiredProtocols;
        registry.add(std::make_shared<StaticContributor>(Health::Report{
            "protocols", protocolsReady ? Health::Status::up : Health::Status::degraded,
            std::to_string(openProtocols) + "/" + std::to_string(protocolServices.size()) +
                " open; " + std::to_string(openRequiredProtocols) + "/" +
                std::to_string(requiredProtocols) + " required open",
            protocolsReady ? "" : "PDR-HEALTH-PROTOCOL-REQUIRED_CLOSED",
            protocolsReady ? "" : "Inspect protocol diagnostics and endpoint connectivity, then restart the affected instance.",
            std::move(affectedProtocols)}));

        for (const auto& service : _context->registry().find("pdr.healthContributor"))
        {
            try
            {
                auto instance = service->instance();
                auto* contributor = dynamic_cast<Health::IHealthContributor*>(instance.get());
                if (contributor)
                    registry.add(std::make_shared<StaticContributor>(contributor->health()));
            }
            catch (const std::exception& exception)
            {
                registry.add(std::make_shared<StaticContributor>(Health::Report{
                    service->properties().get("pdr.healthContributor.component", service->name()),
                    Health::Status::degraded, exception.what(),
                    "PDR-HEALTH-CONTRIBUTOR_FAILED",
                    "Inspect the contributing Bundle logs and service registration."}));
            }
        }

        const auto report = registry.collect();
#if defined(PDR_HEALTH_METRICS)
        for (const auto& component : report.components)
        {
            PocoDDS::Observability::MetricAttributes attributes{
                {"component", component.component},
                {"status", statusName(component.status)}};
            if (!component.code.empty()) attributes.emplace("code", component.code);
            PocoDDS::Observability::Metrics::global().addCounter(
                "pdr.health.component.samples", 1, std::move(attributes),
                "Health probe samples by component, status and stable fault code", "{sample}");
        }
#endif
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
                addReportJson(components, component);
            root.set("components", components);
            root.set("schemaVersion", 2);
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
