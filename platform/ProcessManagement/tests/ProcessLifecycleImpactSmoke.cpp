#include "PocoDDS/ProcessManagement/ProcessLifecycleImpact.h"

#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

namespace
{
using PocoDDS::ProcessManagement::ProcessDependencyGraphSnapshot;
using PocoDDS::ProcessManagement::ProcessDependencyNode;
using PocoDDS::ProcessManagement::analyzeProcessLifecycleImpact;

void require(bool condition, const std::string& message)
{
    if (!condition) throw std::runtime_error(message);
}

ProcessDependencyNode node(std::string name,
                           std::vector<std::string> dependencies,
                           bool desired = true)
{
    ProcessDependencyNode result;
    result.name = std::move(name);
    result.state = "running";
    result.processId = 100;
    result.desiredRunning = desired;
    result.dependencies = std::move(dependencies);
    return result;
}
} // namespace

int main()
{
    try
    {
        ProcessDependencyGraphSnapshot graph;
        graph.available = true;
        graph.generation = 7;
        graph.nodes = {
            node("foundation", {}),
            node("worker", {"foundation"}),
            node("renderer", {"worker"}),
            node("observer", {"foundation"})};

        const auto stop = analyzeProcessLifecycleImpact(
            graph, "foundation", "stop");
        require(stop.allowed && stop.generation == 7 &&
                    stop.requiresConfirmation && !stop.noOp,
                "stop plan admission metadata is incorrect");
        require(stop.affectedDependents ==
                    std::vector<std::string>({"worker", "renderer", "observer"}),
                "transitive dependent closure is incorrect");
        require(stop.stopOrder ==
                    std::vector<std::string>({"observer", "renderer", "worker", "foundation"}),
                "stop plan is not reverse topological");
        require(stop.startOrder.empty(), "stop plan unexpectedly has a start phase");

        const auto start = analyzeProcessLifecycleImpact(graph, "renderer", "start");
        require(start.allowed && start.noOp && !start.requiresConfirmation,
                "already-ready start should be a no-op");
        require(start.prerequisites ==
                    std::vector<std::string>({"foundation", "worker"}) &&
                    start.startOrder ==
                    std::vector<std::string>({"foundation", "worker", "renderer"}),
                "start plan did not expose its dependency closure");

        graph.nodes[1].state = "stopped";
        graph.nodes[1].desiredRunning = false;
        const auto gatedStart = analyzeProcessLifecycleImpact(
            graph, "renderer", "start");
        require(gatedStart.allowed && !gatedStart.noOp &&
                    gatedStart.requiresConfirmation,
                "automatic prerequisite start was not marked for confirmation");

        const auto restart = analyzeProcessLifecycleImpact(
            graph, "worker", "restart");
        require(restart.stopOrder ==
                    std::vector<std::string>({"renderer", "worker"}) &&
                    restart.startOrder ==
                    std::vector<std::string>({"foundation", "worker", "renderer"}),
                "restart plan phases are incorrect");

        graph.nodes[3].location = "remote";
        graph.nodes[3].manageable = false;
        const auto remote = analyzeProcessLifecycleImpact(
            graph, "observer", "stop");
        require(!remote.allowed &&
                    remote.code == "PDR-PROCESS-IMPACT-TARGET_NOT_MANAGEABLE",
                "remote target was admitted");

        const auto missing = analyzeProcessLifecycleImpact(
            graph, "missing", "stop");
        require(!missing.allowed &&
                    missing.code == "PDR-PROCESS-IMPACT-TARGET_NOT_FOUND",
                "unknown target was admitted");

        std::cout << "PROCESS_LIFECYCLE_IMPACT_PASS stopClosure=1 "
                     "reverseOrder=1 startClosure=1 confirmation=1 remoteDenied=1\n";
        return 0;
    }
    catch (const std::exception& exception)
    {
        std::cerr << "Process lifecycle impact smoke failed: "
                  << exception.what() << '\n';
        return 1;
    }
}
