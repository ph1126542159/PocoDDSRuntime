#pragma once

#include "PocoDDS/ProcessManagement/ProcessDependencyGraph.h"
#include "PocoDDS/ProcessManagement/ProcessDesiredStateMaintenance.h"

#include <functional>

namespace PocoDDS::ProcessManagement::Detail
{
using ProcessDependencyGraphCallback =
    std::function<ProcessDependencyGraphSnapshot()>;
using ProcessDesiredStateMaintenanceCallback =
    std::function<ProcessDesiredStateRecommitResult(std::uint64_t)>;

PDR_PROCESS_GRAPH_API void registerProcessDependencyGraphProvider(
    const void* owner, ProcessDependencyGraphCallback callback);
PDR_PROCESS_GRAPH_API void unregisterProcessDependencyGraphProvider(
    const void* owner);
PDR_PROCESS_GRAPH_API void registerProcessDesiredStateMaintenanceProvider(
    const void* owner, ProcessDesiredStateMaintenanceCallback callback);
PDR_PROCESS_GRAPH_API void unregisterProcessDesiredStateMaintenanceProvider(
    const void* owner);
} // namespace PocoDDS::ProcessManagement::Detail
