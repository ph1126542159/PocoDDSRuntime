#pragma once

#include "PocoDDS/RuntimeCore/Contract.h"
#include "PocoDDS/RuntimeCore/Export.h"

#include <chrono>
#include <cstdint>
#include <optional>
#include <string>
#include <unordered_map>
#include <vector>

namespace PocoDDS::RuntimeCore
{

enum class RestartPolicy
{
    never,
    onFailure,
    always
};

enum class ProcessState
{
    registered,
    starting,
    running,
    stopping,
    stopped,
    exited,
    quarantined,
    failed
};

struct ProcessSpec
{
    std::string id;
    std::string executable;
    std::vector<std::string> arguments;
    std::string workingDirectory;
    std::unordered_map<std::string, std::string> environment;
    std::vector<std::string> dependencies;
    std::string standardOutputPath;
    std::string standardErrorPath;
    RestartPolicy restartPolicy{RestartPolicy::never};
    std::size_t maximumRestarts{3};
    std::chrono::milliseconds restartWindow{60000};
    std::chrono::milliseconds gracefulStopTimeout{5000};
    bool hidden{true};
};

struct ProcessSnapshot
{
    ProcessSpec spec;
    ProcessState state{ProcessState::registered};
    std::uint64_t processId{0};
    std::size_t restartCount{0};
    std::optional<int> lastExitCode;
    RuntimeError lastError;
};

class PDR_RUNTIME_CORE_API IProcessSupervisor
{
  public:
    virtual ~IProcessSupervisor() = default;
    virtual Outcome<void> registerProcess(ProcessSpec spec) = 0;
    virtual Outcome<void> start(const std::string& id) = 0;
    virtual Outcome<void> startAll() = 0;
    virtual Outcome<void> stop(const std::string& id) = 0;
    virtual void stopAll() noexcept = 0;
    virtual Outcome<void> restart(const std::string& id) = 0;
    virtual std::vector<ProcessSnapshot> snapshots() const = 0;
};

} // namespace PocoDDS::RuntimeCore
