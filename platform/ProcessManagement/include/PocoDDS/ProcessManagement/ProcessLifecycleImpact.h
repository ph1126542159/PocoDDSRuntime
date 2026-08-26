#pragma once

#include "PocoDDS/ProcessManagement/ProcessDependencyGraph.h"

#include <cstdint>
#include <string>
#include <vector>

namespace PocoDDS::ProcessManagement
{
struct ProcessLifecycleImpactNode
{
    std::string name;
    std::string role;
    std::string state;
    unsigned long processId{0};
    bool desiredRunning{false};
};

struct ProcessLifecycleImpactPlan
{
    std::uint32_t schemaVersion{1};
    std::uint64_t generation{0};
    bool available{false};
    bool allowed{false};
    bool requiresConfirmation{false};
    bool noOp{false};
    std::string action;
    std::string target;
    std::string code;
    std::string detail;
    std::vector<std::string> prerequisites;
    std::vector<std::string> affectedDependents;
    std::vector<std::string> stopOrder;
    std::vector<std::string> startOrder;
    std::vector<ProcessLifecycleImpactNode> affected;
};

/// Builds a side-effect-free lifecycle plan from one immutable graph snapshot.
/// The graph order remains authoritative: stop order is reverse topological,
/// while prerequisite and recovery order are topological.
PDR_PROCESS_GRAPH_API ProcessLifecycleImpactPlan analyzeProcessLifecycleImpact(
    const ProcessDependencyGraphSnapshot& graph,
    const std::string& target,
    const std::string& action);
} // namespace PocoDDS::ProcessManagement
