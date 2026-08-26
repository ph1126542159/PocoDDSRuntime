#include "Poco/ClassLibrary.h"
#include "Poco/JSON/Array.h"
#include "Poco/JSON/Object.h"
#include "Poco/Net/HTTPServerRequest.h"
#include "Poco/Net/HTTPServerResponse.h"
#include "Poco/Net/HTTPRequestHandler.h"
#include "Poco/OSP/Web/WebRequestHandlerFactory.h"
#include "Poco/Process.h"
#include "Poco/URI.h"
#include "PocoDDS/ProcessManagement/ProcessDependencyGraph.h"
#include "PocoDDS/ProcessManagement/ProcessLifecycleImpact.h"

#include <algorithm>
#include <cctype>
#include <set>
#include <string>

namespace PocoDDS::ProcessGraphEndpoint
{
namespace
{
using PocoDDS::ProcessManagement::ProcessDependencyGraphSnapshot;
using PocoDDS::ProcessManagement::ProcessDependencyNode;
using PocoDDS::ProcessManagement::ProcessLifecycleImpactPlan;

const ProcessDependencyNode* findNode(
    const ProcessDependencyGraphSnapshot& graph,
    const std::string& name)
{
    const auto node = std::find_if(
        graph.nodes.begin(), graph.nodes.end(), [&](const auto& candidate) {
            return candidate.name == name;
        });
    return node == graph.nodes.end() ? nullptr : &*node;
}

std::string edgeState(const ProcessDependencyNode* dependency)
{
    if (!dependency)
        return "failed";
    if (dependency->state == "running")
        return "satisfied";
    if (dependency->desiredRunning &&
        (dependency->state == "starting" ||
         dependency->state == "waiting-dependency" ||
         dependency->state == "restart-pending"))
        return "waiting";
    return "failed";
}

std::string blockingReason(const ProcessDependencyNode* dependency)
{
    if (!dependency)
        return "dependency-unavailable";
    if (dependency->state == "starting")
        return "dependency-starting";
    if (dependency->state == "waiting-dependency")
        return "dependency-waiting";
    if (dependency->state == "restart-pending")
        return "dependency-recovering";
    if (dependency->state == "stopped" || dependency->state == "exited")
        return "dependency-stopped";
    if (dependency->state == "failed" ||
        dependency->state == "dependency-failed")
        return "dependency-failed";
    return "dependency-not-ready";
}

void sendError(Poco::Net::HTTPServerResponse& response,
               Poco::Net::HTTPResponse::HTTPStatus status,
               const std::string& code,
               const std::string& detail)
{
    response.setStatus(status);
    response.setContentType("application/json; charset=utf-8");
    response.set("Cache-Control", "no-store");
    Poco::JSON::Object error;
    error.set("error", detail);
    error.set("code", code);
    error.set("detail", detail);
    error.stringify(response.send());
}

bool readImpactQuery(const Poco::URI& uri, std::string& target,
                     std::string& action, std::string& error)
{
    Poco::URI::QueryParameters parameters;
    try
    {
        parameters = uri.getQueryParameters();
    }
    catch (...)
    {
        error = "Malformed impact query";
        return false;
    }
    std::set<std::string> seen;
    for (const auto& parameter : parameters)
    {
        if ((parameter.first != "target" && parameter.first != "action") ||
            !seen.insert(parameter.first).second)
        {
            error = "Only one target and one action query parameter are allowed";
            return false;
        }
        if (parameter.first == "target") target = parameter.second;
        if (parameter.first == "action") action = parameter.second;
    }
    if (target.empty() || action.empty())
    {
        error = "Both target and action query parameters are required";
        return false;
    }
    if (action != "start" && action != "stop" && action != "restart")
    {
        error = "Action must be start, stop or restart";
        return false;
    }
    const auto validTargetCharacter = [](unsigned char value) {
        return std::isalnum(value) || value == '.' || value == '_' ||
            value == ':' || value == '-';
    };
    if (target.size() > 128 ||
        !std::all_of(target.begin(), target.end(), validTargetCharacter))
    {
        error = "Target must be a valid managed process identifier";
        return false;
    }
    return true;
}

void sendImpact(Poco::Net::HTTPServerResponse& response,
                const ProcessLifecycleImpactPlan& plan)
{
    Poco::JSON::Object root;
    root.set("schemaVersion", plan.schemaVersion);
    root.set("available", plan.available);
    root.set("generation", plan.generation);
    root.set("scope", "runtime-process");
    root.set("action", plan.action);
    root.set("target", plan.target);
    root.set("allowed", plan.allowed);
    root.set("code", plan.code);
    root.set("detail", plan.detail);
    root.set("requiresConfirmation", plan.requiresConfirmation);
    root.set("noOp", plan.noOp);

    const auto names = [](const std::vector<std::string>& values) {
        Poco::JSON::Array result;
        for (const auto& value : values) result.add(value);
        return result;
    };
    root.set("prerequisites", names(plan.prerequisites));
    root.set("affectedDependents", names(plan.affectedDependents));
    root.set("stopOrder", names(plan.stopOrder));
    root.set("startOrder", names(plan.startOrder));
    root.set("affectedCount", plan.affected.size());

    Poco::JSON::Array affected;
    for (const auto& node : plan.affected)
    {
        Poco::JSON::Object item;
        item.set("name", node.name);
        item.set("role", node.role);
        item.set("state", node.state);
        item.set("processId", static_cast<Poco::UInt64>(node.processId));
        item.set("desiredState", node.desiredRunning ? "running" : "stopped");
        affected.add(item);
    }
    root.set("affected", affected);

    response.setStatus(Poco::Net::HTTPResponse::HTTP_OK);
    response.setContentType("application/json; charset=utf-8");
    response.set("Cache-Control", "no-store");
    root.stringify(response.send());
}

class ProcessGraphHandler final : public Poco::Net::HTTPRequestHandler
{
  public:
    void handleRequest(Poco::Net::HTTPServerRequest& request,
                       Poco::Net::HTTPServerResponse& response) override
    {
        const Poco::URI uri(request.getURI());
        const bool impact = uri.getPath() ==
            "/api/v1/process-dependencies/impact";
        if (uri.getPath() != "/api/v1/process-dependencies" && !impact)
        {
            sendError(response, Poco::Net::HTTPResponse::HTTP_NOT_FOUND,
                      "PDR-PROCESS-GRAPH-ENDPOINT_NOT_FOUND",
                      "Unknown process dependency endpoint");
            return;
        }
        if (request.getMethod() != Poco::Net::HTTPRequest::HTTP_GET)
        {
            response.setStatus(
                Poco::Net::HTTPResponse::HTTP_METHOD_NOT_ALLOWED);
            response.set("Allow", "GET");
            response.setContentLength(0);
            response.send();
            return;
        }

        const auto graph =
            PocoDDS::ProcessManagement::activeProcessDependencyGraph();
        if (!graph.available)
        {
            response.setStatus(
                Poco::Net::HTTPResponse::HTTP_SERVICE_UNAVAILABLE);
            response.setContentType("application/json; charset=utf-8");
            response.set("Cache-Control", "no-store");
            Poco::JSON::Object unavailable;
            unavailable.set("schemaVersion", graph.schemaVersion);
            unavailable.set("available", false);
            unavailable.set("code", "PDR-PROCESS-GRAPH-MANAGER_UNAVAILABLE");
            unavailable.set("detail", "ProcessManagement is not initialized");
            unavailable.stringify(response.send());
            return;
        }
        if (impact)
        {
            std::string target;
            std::string action;
            std::string error;
            if (!readImpactQuery(uri, target, action, error))
            {
                sendError(response, Poco::Net::HTTPResponse::HTTP_BAD_REQUEST,
                          "PDR-PROCESS-IMPACT-QUERY_INVALID", error);
                return;
            }
            sendImpact(response,
                PocoDDS::ProcessManagement::analyzeProcessLifecycleImpact(
                    graph, target, action));
            return;
        }

        Poco::JSON::Object root;
        root.set("schemaVersion", graph.schemaVersion);
        root.set("available", true);
        root.set("generation", graph.generation);
        root.set("scope", "runtime-process");
        root.set("runtimeProcessId",
                 static_cast<Poco::UInt64>(Poco::Process::id()));

        Poco::JSON::Object persistence;
        persistence.set("enabled",
            graph.desiredStatePersistence.enabled);
        persistence.set("healthy",
            graph.desiredStatePersistence.healthy);
        persistence.set("leaseHeld",
            graph.desiredStatePersistence.leaseHeld);
        persistence.set("recoveredFromPrevious",
            graph.desiredStatePersistence.recoveredFromPrevious);
        persistence.set("primaryValid",
            graph.desiredStatePersistence.primaryValid);
        persistence.set("previousAvailable",
            graph.desiredStatePersistence.previousAvailable);
        persistence.set("previousValid",
            graph.desiredStatePersistence.previousValid);
        persistence.set("generation", static_cast<Poco::UInt64>(
            graph.desiredStatePersistence.generation));
        persistence.set("lastIntegrityCheckEpochMicroseconds",
            static_cast<Poco::UInt64>(graph.desiredStatePersistence.
                lastIntegrityCheckEpochMicroseconds));
        persistence.set("state",
            graph.desiredStatePersistence.state);
        persistence.set("integrityState",
            graph.desiredStatePersistence.integrityState);
        root.set("desiredStatePersistence", persistence);

        Poco::JSON::Array nodes;
        Poco::JSON::Array edges;
        Poco::JSON::Array startupOrder;
        Poco::JSON::Array shutdownOrder;
        std::size_t runningCount = 0;
        std::size_t waitingCount = 0;
        std::size_t blockedCount = 0;
        for (const auto& node : graph.nodes)
        {
            Poco::JSON::Object item;
            item.set("id", node.name);
            item.set("name", node.name);
            item.set("location", node.location);
            item.set("state", node.state);
            item.set("processId", static_cast<Poco::UInt64>(node.processId));
            item.set("manageable", node.manageable);
            item.set("required", node.required);
            item.set("desiredState",
                     node.desiredRunning ? "running" : "stopped");
            item.set("readyForDependents", node.state == "running");

            Poco::JSON::Array dependencies;
            Poco::JSON::Array dependents;
            Poco::JSON::Array blockedBy;
            std::string primaryBlockingReason = "none";
            bool failedBlocker = false;
            for (const auto& dependencyName : node.dependencies)
            {
                dependencies.add(dependencyName);
                const auto* dependency = findNode(graph, dependencyName);
                const auto state = edgeState(dependency);
                Poco::JSON::Object edge;
                edge.set("from", dependencyName);
                edge.set("to", node.name);
                edge.set("state", state);
                edge.set("reason", state == "satisfied"
                    ? "none" : blockingReason(dependency));
                edges.add(edge);
                if (state != "satisfied")
                {
                    Poco::JSON::Object blocker;
                    blocker.set("name", dependencyName);
                    blocker.set("state", dependency
                        ? dependency->state : "unavailable");
                    blocker.set("reason", blockingReason(dependency));
                    blockedBy.add(blocker);
                    if (state == "failed" || !failedBlocker)
                    {
                        primaryBlockingReason = blockingReason(dependency);
                        failedBlocker = state == "failed";
                    }
                }
            }
            for (const auto& candidate : graph.nodes)
            {
                if (std::find(candidate.dependencies.begin(),
                              candidate.dependencies.end(), node.name) !=
                    candidate.dependencies.end())
                    dependents.add(candidate.name);
            }
            item.set("dependencies", dependencies);
            item.set("dependents", dependents);
            item.set("blockedBy", blockedBy);
            item.set("blockingReason", primaryBlockingReason);
            nodes.add(item);
            startupOrder.add(node.name);
            if (node.state == "running")
                ++runningCount;
            if (node.state == "waiting-dependency" ||
                node.state == "starting" ||
                node.state == "restart-pending")
                ++waitingCount;
            if (node.state == "dependency-failed")
                ++blockedCount;
        }
        for (auto node = graph.nodes.rbegin(); node != graph.nodes.rend(); ++node)
            shutdownOrder.add(node->name);
        root.set("nodes", nodes);
        root.set("edges", edges);
        root.set("startupOrder", startupOrder);
        root.set("shutdownOrder", shutdownOrder);

        Poco::JSON::Object summary;
        summary.set("configured", graph.nodes.size());
        summary.set("running", runningCount);
        summary.set("waiting", waitingCount);
        summary.set("blocked", blockedCount);
        root.set("summary", summary);

        response.setStatus(Poco::Net::HTTPResponse::HTTP_OK);
        response.setContentType("application/json; charset=utf-8");
        response.set("Cache-Control", "no-store");
        root.stringify(response.send());
    }
};
} // namespace

class ProcessGraphHandlerFactory final
    : public Poco::OSP::Web::WebRequestHandlerFactory
{
  public:
    Poco::Net::HTTPRequestHandler* createRequestHandler(
        const Poco::Net::HTTPServerRequest&) override
    {
        return new ProcessGraphHandler;
    }
};
} // namespace PocoDDS::ProcessGraphEndpoint

POCO_BEGIN_NAMED_MANIFEST(WebServer, Poco::OSP::Web::WebRequestHandlerFactory)
    POCO_EXPORT_CLASS(PocoDDS::ProcessGraphEndpoint::ProcessGraphHandlerFactory)
POCO_END_MANIFEST
