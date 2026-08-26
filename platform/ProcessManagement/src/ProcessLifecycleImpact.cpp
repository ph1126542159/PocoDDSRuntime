#include "PocoDDS/ProcessManagement/ProcessLifecycleImpact.h"

#include <algorithm>
#include <set>

namespace PocoDDS::ProcessManagement
{
namespace
{
const ProcessDependencyNode* findNode(
    const ProcessDependencyGraphSnapshot& graph, const std::string& name)
{
    const auto node = std::find_if(
        graph.nodes.begin(), graph.nodes.end(), [&](const auto& candidate) {
            return candidate.name == name;
        });
    return node == graph.nodes.end() ? nullptr : &*node;
}

bool dependsTransitivelyOn(const ProcessDependencyGraphSnapshot& graph,
                           const ProcessDependencyNode& node,
                           const std::string& dependency,
                           std::set<std::string>& visited)
{
    if (!visited.insert(node.name).second)
        return false;
    for (const auto& direct : node.dependencies)
    {
        if (direct == dependency)
            return true;
        const auto* parent = findNode(graph, direct);
        if (parent && dependsTransitivelyOn(graph, *parent, dependency, visited))
            return true;
    }
    return false;
}

bool dependsTransitivelyOn(const ProcessDependencyGraphSnapshot& graph,
                           const ProcessDependencyNode& node,
                           const std::string& dependency)
{
    std::set<std::string> visited;
    return dependsTransitivelyOn(graph, node, dependency, visited);
}

bool activeState(const std::string& state)
{
    return state == "running" || state == "starting" ||
        state == "restart-pending";
}

void appendAffected(ProcessLifecycleImpactPlan& plan,
                    const ProcessDependencyNode& node,
                    const std::string& role)
{
    const auto duplicate = std::find_if(
        plan.affected.begin(), plan.affected.end(), [&](const auto& item) {
            return item.name == node.name;
        });
    if (duplicate != plan.affected.end())
        return;
    plan.affected.push_back({node.name, role, node.state, node.processId,
                             node.desiredRunning});
}
} // namespace

ProcessLifecycleImpactPlan analyzeProcessLifecycleImpact(
    const ProcessDependencyGraphSnapshot& graph,
    const std::string& target,
    const std::string& action)
{
    ProcessLifecycleImpactPlan plan;
    plan.available = graph.available;
    plan.generation = graph.generation;
    plan.action = action;
    plan.target = target;
    if (!graph.available)
    {
        plan.code = "PDR-PROCESS-IMPACT-MANAGER_UNAVAILABLE";
        plan.detail = "ProcessManagement is not initialized";
        return plan;
    }
    if (action != "start" && action != "stop" && action != "restart")
    {
        plan.code = "PDR-PROCESS-IMPACT-ACTION_UNSUPPORTED";
        plan.detail = "Unsupported process lifecycle action";
        return plan;
    }
    const auto* targetNode = findNode(graph, target);
    if (!targetNode)
    {
        plan.code = "PDR-PROCESS-IMPACT-TARGET_NOT_FOUND";
        plan.detail = "Managed process target was not found";
        return plan;
    }
    if (targetNode->location != "local" || !targetNode->manageable)
    {
        plan.code = "PDR-PROCESS-IMPACT-TARGET_NOT_MANAGEABLE";
        plan.detail = "Remote or protected process cannot be managed locally";
        appendAffected(plan, *targetNode, "target");
        return plan;
    }

    std::set<std::string> prerequisiteNames;
    std::set<std::string> dependentNames;
    for (const auto& node : graph.nodes)
    {
        if (node.name != target &&
            dependsTransitivelyOn(graph, *targetNode, node.name))
            prerequisiteNames.insert(node.name);
        if (node.name != target &&
            dependsTransitivelyOn(graph, node, target))
            dependentNames.insert(node.name);
    }

    for (const auto& node : graph.nodes)
    {
        if (prerequisiteNames.count(node.name))
            plan.prerequisites.push_back(node.name);
        if (dependentNames.count(node.name))
            plan.affectedDependents.push_back(node.name);
    }

    if (action == "stop" || action == "restart")
    {
        for (auto node = graph.nodes.rbegin(); node != graph.nodes.rend(); ++node)
            if (node->name == target || dependentNames.count(node->name))
                plan.stopOrder.push_back(node->name);
    }
    if (action == "start" || action == "restart")
    {
        for (const auto& node : graph.nodes)
        {
            const bool prerequisite = prerequisiteNames.count(node.name) != 0;
            const bool targetMatch = node.name == target;
            const bool recoveringDependent = action == "restart" &&
                dependentNames.count(node.name) && node.desiredRunning;
            if (prerequisite || targetMatch || recoveringDependent)
                plan.startOrder.push_back(node.name);
        }
    }

    for (const auto& node : graph.nodes)
    {
        if (prerequisiteNames.count(node.name))
            appendAffected(plan, node, "prerequisite");
        else if (node.name == target)
            appendAffected(plan, node, "target");
        else if (dependentNames.count(node.name))
            appendAffected(plan, node, "dependent");
    }

    if (action == "start")
    {
        plan.noOp = std::all_of(
            plan.startOrder.begin(), plan.startOrder.end(), [&](const auto& name) {
                const auto* node = findNode(graph, name);
                return node && node->state == "running" && node->desiredRunning;
            });
        plan.requiresConfirmation = std::any_of(
            plan.prerequisites.begin(), plan.prerequisites.end(),
            [&](const auto& name) {
                const auto* node = findNode(graph, name);
                return node && node->state != "running";
            });
    }
    else if (action == "stop")
    {
        plan.noOp = !targetNode->desiredRunning && std::none_of(
            plan.stopOrder.begin(), plan.stopOrder.end(), [&](const auto& name) {
                const auto* node = findNode(graph, name);
                return node && activeState(node->state);
            });
        plan.requiresConfirmation = !plan.noOp;
    }
    else
    {
        plan.noOp = false;
        plan.requiresConfirmation = true;
    }

    plan.allowed = true;
    plan.code = plan.noOp ? "PDR-PROCESS-IMPACT-NO_CHANGE" :
                           "PDR-PROCESS-IMPACT-READY";
    plan.detail = plan.noOp ?
        "The requested action would not change managed process state" :
        "Lifecycle impact plan is ready for operator review";
    return plan;
}
} // namespace PocoDDS::ProcessManagement
