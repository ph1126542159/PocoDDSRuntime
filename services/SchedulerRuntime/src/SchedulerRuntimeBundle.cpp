#include "PocoDDS/ManagementAuth/IdentityService.h"
#include "PocoDDS/ResourceGovernance/ResourceGovernorService.h"
#include "PocoDDS/Scheduling/SchedulerService.h"

#include <Poco/AutoPtr.h>
#include <Poco/ClassLibrary.h>
#include <Poco/Dynamic/Var.h>
#include <Poco/Exception.h>
#include <Poco/JSON/Array.h>
#include <Poco/JSON/Object.h>
#include <Poco/Net/HTTPRequest.h>
#include <Poco/Net/HTTPResponse.h>
#include <Poco/Net/HTTPServerRequest.h>
#include <Poco/Net/HTTPServerResponse.h>
#include <Poco/Net/HTTPRequestHandler.h>
#include <Poco/OSP/Bundle.h>
#include <Poco/OSP/BundleActivator.h>
#include <Poco/OSP/BundleContext.h>
#include <Poco/OSP/Properties.h>
#include <Poco/OSP/ServiceFinder.h>
#include <Poco/OSP/ServiceRef.h>
#include <Poco/OSP/ServiceRegistry.h>
#include <Poco/OSP/Web/WebRequestHandlerFactory.h>
#include <Poco/URI.h>

#include <optional>
#include <string>
#include <utility>

namespace PocoDDS::Scheduling
{
namespace
{
constexpr const char* READ_PERMISSION = "resource.read";

void prepare(Poco::Net::HTTPServerResponse& response)
{
    response.setContentType("application/json; charset=utf-8");
    response.set("Cache-Control", "no-store");
    response.set("Pragma", "no-cache");
    response.set("X-Content-Type-Options", "nosniff");
}

void send(Poco::Net::HTTPServerResponse& response,
          Poco::Net::HTTPResponse::HTTPStatus status,
          const Poco::JSON::Object& body)
{
    prepare(response);
    response.setStatus(status);
    body.stringify(response.send());
}

void sendError(Poco::Net::HTTPServerResponse& response,
               Poco::Net::HTTPResponse::HTTPStatus status,
               const std::string& code, const std::string& message)
{
    Poco::JSON::Object body;
    body.set("code", code);
    body.set("error", message);
    send(response, status, body);
}

std::optional<std::string> authorize(
    const Poco::OSP::BundleContext::Ptr& context,
    Poco::Net::HTTPServerRequest& request,
    Poco::Net::HTTPServerResponse& response)
{
    const auto reference = context->registry().findByName(
        ManagementAuth::IdentityService::SERVICE_NAME);
    if (!reference)
    {
        sendError(response, Poco::Net::HTTPResponse::HTTP_SERVICE_UNAVAILABLE,
                  "SCHEDULER_IDENTITY_UNAVAILABLE",
                  "Management identity service is unavailable");
        return std::nullopt;
    }
    const auto identity = reference->castedInstance<ManagementAuth::IdentityService>();
    const auto matched = identity->authenticateAuthorizationHeader(
        request.get("Authorization", ""));
    if (!matched)
    {
        if (!identity->snapshot().required) return std::string("development-anonymous");
        response.set("WWW-Authenticate", "Bearer realm=\"pdr-scheduler\"");
        sendError(response, Poco::Net::HTTPResponse::HTTP_UNAUTHORIZED,
                  "SCHEDULER_AUTHENTICATION_REQUIRED",
                  "A valid management Bearer token is required");
        return std::nullopt;
    }
    if (!matched->authorized(READ_PERMISSION))
    {
        sendError(response, Poco::Net::HTTPResponse::HTTP_FORBIDDEN,
                  "SCHEDULER_PERMISSION_DENIED",
                  "Authenticated principal lacks resource.read");
        return std::nullopt;
    }
    response.set("X-PDR-Management-Principal", matched->id);
    return matched->id;
}

Poco::JSON::Object::Ptr snapshotObject(const TaskSnapshot& snapshot)
{
    Poco::JSON::Object::Ptr result = new Poco::JSON::Object;
    result->set("id", snapshot.spec.id);
    result->set("owner", snapshot.spec.owner);
    result->set("enabled", snapshot.spec.enabled);
    result->set("mode", toString(snapshot.spec.mode));
    result->set("misfirePolicy", toString(snapshot.spec.misfire));
    result->set("initialDelayMilliseconds", snapshot.spec.initialDelay.count());
    result->set("intervalMilliseconds", snapshot.spec.interval.count());
    result->set("jitterMilliseconds", snapshot.spec.jitter.count());
    result->set("rejectionBackoffMilliseconds", snapshot.spec.rejectionBackoff.count());
    result->set("inFlight", snapshot.inFlight);
    result->set("coalesced", snapshot.coalesced);
    if (snapshot.nextRunIn)
        result->set("nextRunInMilliseconds", snapshot.nextRunIn->count());
    else
        result->set("nextRunInMilliseconds", Poco::Dynamic::Var());
    result->set("triggered", snapshot.triggered);
    result->set("accepted", snapshot.accepted);
    result->set("rejected", snapshot.rejected);
    result->set("misfires", snapshot.misfires);
    result->set("completed", snapshot.completed);
    result->set("failed", snapshot.failed);
    if (snapshot.lastStatus)
        result->set("lastStatus", ResourceGovernance::toString(*snapshot.lastStatus));
    else
        result->set("lastStatus", Poco::Dynamic::Var());
    result->set("lastMessage", snapshot.lastMessage);
    return result;
}

class RuntimeServiceImpl final : public SchedulerService
{
public:
    explicit RuntimeServiceImpl(ResourceGovernance::ResourceGovernorService::Ptr governor)
        : _governor(std::move(governor)),
          _scheduler([this](const std::string& owner,
                            ResourceGovernance::WorkItem item) {
              return _governor->submit(owner, std::move(item));
          })
    {
    }

    Registration schedule(TaskSpec spec, TaskCallback run,
                          CompletionCallback complete) override
    {
        return _scheduler.schedule(std::move(spec), std::move(run),
                                   std::move(complete));
    }

    Reconfiguration reconfigure(TaskSpec spec) override
    {
        return _scheduler.reconfigure(std::move(spec));
    }
    bool cancelAndWait(const std::string& taskId) noexcept override
    {
        return _scheduler.cancelAndWait(taskId);
    }
    std::optional<TaskSnapshot> snapshot(const std::string& taskId) const override
    {
        return _scheduler.snapshot(taskId);
    }
    std::vector<TaskSnapshot> snapshots() const override
    {
        return _scheduler.snapshots();
    }
    void shutdown() noexcept { _scheduler.shutdown(); }

private:
    ResourceGovernance::ResourceGovernorService::Ptr _governor;
    Scheduler _scheduler;
};

SchedulerService::Ptr service(const Poco::OSP::BundleContext::Ptr& context)
{
    const auto reference = context->registry().findByName(SchedulerService::SERVICE_NAME);
    if (!reference) throw Poco::NotFoundException("Scheduler service is unavailable");
    return reference->castedInstance<SchedulerService>();
}

class Handler final : public Poco::Net::HTTPRequestHandler
{
public:
    explicit Handler(Poco::OSP::BundleContext::Ptr context): _context(std::move(context)) {}

    void handleRequest(Poco::Net::HTTPServerRequest& request,
                       Poco::Net::HTTPServerResponse& response) override
    {
        if (Poco::URI(request.getURI()).getPath() != "/api/v1/scheduled-tasks")
        {
            sendError(response, Poco::Net::HTTPResponse::HTTP_NOT_FOUND,
                      "SCHEDULER_ENDPOINT_NOT_FOUND", "Unknown scheduler endpoint");
            return;
        }
        if (request.getMethod() != Poco::Net::HTTPRequest::HTTP_GET)
        {
            response.set("Allow", "GET");
            sendError(response, Poco::Net::HTTPResponse::HTTP_METHOD_NOT_ALLOWED,
                      "SCHEDULER_METHOD_NOT_ALLOWED",
                      "Scheduler endpoint only supports GET");
            return;
        }
        const auto principal = authorize(_context, request, response);
        if (!principal) return;
        try
        {
            std::string taskId;
            for (const auto& parameter : Poco::URI(request.getURI()).getQueryParameters())
                if (parameter.first == "taskId") taskId = parameter.second;
            Poco::JSON::Array::Ptr tasks = new Poco::JSON::Array;
            const auto scheduler = service(_context);
            if (!taskId.empty())
            {
                const auto value = scheduler->snapshot(taskId);
                if (value) tasks->add(snapshotObject(*value));
            }
            else
            {
                for (const auto& value : scheduler->snapshots())
                    tasks->add(snapshotObject(value));
            }
            Poco::JSON::Object body;
            body.set("schemaVersion", 1);
            body.set("principal", *principal);
            body.set("scope", "runtime-process/managed-periodic-tasks");
            body.set("taskCount", static_cast<Poco::UInt64>(tasks->size()));
            body.set("tasks", tasks);
            send(response, Poco::Net::HTTPResponse::HTTP_OK, body);
        }
        catch (const std::exception& exception)
        {
            _context->logger().error("Scheduler status failed: " +
                                     std::string(exception.what()));
            sendError(response, Poco::Net::HTTPResponse::HTTP_SERVICE_UNAVAILABLE,
                      "SCHEDULER_STATUS_UNAVAILABLE",
                      "Scheduler status is unavailable");
        }
    }

private:
    Poco::OSP::BundleContext::Ptr _context;
};
} // namespace

class SchedulerRuntimeHandlerFactory final :
    public Poco::OSP::Web::WebRequestHandlerFactory
{
public:
    Poco::Net::HTTPRequestHandler* createRequestHandler(
        const Poco::Net::HTTPServerRequest&) override
    {
        return new Handler(context());
    }
};

class SchedulerRuntimeBundleActivator final : public Poco::OSP::BundleActivator
{
public:
    void start(Poco::OSP::BundleContext::Ptr context) override
    {
        try
        {
            auto governor = Poco::OSP::ServiceFinder::find<
                ResourceGovernance::ResourceGovernorService>(context);
            _service = new RuntimeServiceImpl(std::move(governor));
            Poco::OSP::Properties properties;
            properties.set("pdr.service", "schedulerRuntime");
            properties.set("pdr.scheduler.scope", "managed-periodic-tasks");
            properties.set("pdr.scheduler.timerThreads", "1");
            properties.set("pdr.bundle", context->thisBundle()->symbolicName());
            _serviceRef = context->registry().registerService(
                SchedulerService::SERVICE_NAME, _service, properties);
            context->logger().information(
                "Managed scheduler runtime started with one central timer thread; "
                "business work is delegated to ResourceGovernor owner lanes.");
        }
        catch (...)
        {
            stop(context);
            throw;
        }
    }

    void stop(Poco::OSP::BundleContext::Ptr context) override
    {
        if (_service) _service->shutdown();
        if (_serviceRef)
        {
            try { context->registry().unregisterService(_serviceRef); }
            catch (...) {}
        }
        _serviceRef = nullptr;
        _service = nullptr;
    }

private:
    Poco::AutoPtr<RuntimeServiceImpl> _service;
    Poco::OSP::ServiceRef::Ptr _serviceRef;
};
} // namespace PocoDDS::Scheduling

POCO_BEGIN_MANIFEST(Poco::OSP::BundleActivator)
    POCO_EXPORT_CLASS(PocoDDS::Scheduling::SchedulerRuntimeBundleActivator)
POCO_END_MANIFEST

POCO_BEGIN_NAMED_MANIFEST(WebServer, Poco::OSP::Web::WebRequestHandlerFactory)
    POCO_EXPORT_CLASS(PocoDDS::Scheduling::SchedulerRuntimeHandlerFactory)
POCO_END_MANIFEST
