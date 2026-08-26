#pragma once

#include "PocoDDS/ProcessManagement/ProcessDependencyGraph.h"

#include <cstdint>
#include <string>

namespace PocoDDS::ProcessManagement
{
struct ProcessDesiredStateRecommitResult
{
    bool accepted{false};
    bool changed{false};
    bool healthy{false};
    std::uint64_t expectedGeneration{0};
    std::uint64_t previousGeneration{0};
    std::uint64_t generation{0};
    std::string code{"manager-unavailable"};
    std::string integrityState{"disabled"};
};

/// Rewrites the active manager's in-memory desired authorization as one new
/// durable generation without starting, stopping or restarting any process.
/// The operation is compare-and-swap: expectedGeneration must match the
/// current persistence generation. Healthy stores are accepted as no-ops.
PDR_PROCESS_GRAPH_API ProcessDesiredStateRecommitResult
recommitActiveProcessDesiredState(std::uint64_t expectedGeneration);
} // namespace PocoDDS::ProcessManagement
