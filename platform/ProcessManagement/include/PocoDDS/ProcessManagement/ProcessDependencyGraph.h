#pragma once

#include <cstdint>
#include <string>
#include <vector>

#if defined(_WIN32)
#if defined(PDR_PROCESS_GRAPH_EXPORTS)
#define PDR_PROCESS_GRAPH_API __declspec(dllexport)
#else
#define PDR_PROCESS_GRAPH_API __declspec(dllimport)
#endif
#else
#define PDR_PROCESS_GRAPH_API
#endif

namespace PocoDDS::ProcessManagement
{
struct ProcessDependencyNode
{
    std::string name;
    std::string location{"local"};
    std::string state{"stopped"};
    unsigned long processId{0};
    bool manageable{true};
    bool required{true};
    bool desiredRunning{false};
    std::vector<std::string> dependencies;
};

struct ProcessDesiredStatePersistenceStatus
{
    bool enabled{false};
    bool healthy{true};
    bool leaseHeld{false};
    bool recoveredFromPrevious{false};
    bool primaryValid{true};
    bool previousAvailable{false};
    bool previousValid{false};
    std::uint64_t generation{0};
    std::uint64_t lastIntegrityCheckEpochMicroseconds{0};
    std::string state{"disabled"};
    std::string integrityState{"disabled"};
};

struct ProcessDependencyGraphSnapshot
{
    std::uint32_t schemaVersion{1};
    std::uint64_t generation{0};
    bool available{false};
    ProcessDesiredStatePersistenceStatus desiredStatePersistence;
    std::vector<ProcessDependencyNode> nodes;
};

/// Returns one immutable, topologically ordered snapshot of the active
/// Runtime's managed-process dependency graph. The function is safe to call
/// before ProcessManagement initialization; available is then false.
PDR_PROCESS_GRAPH_API ProcessDependencyGraphSnapshot
activeProcessDependencyGraph();
} // namespace PocoDDS::ProcessManagement
