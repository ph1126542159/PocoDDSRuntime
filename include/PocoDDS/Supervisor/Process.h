#pragma once

#include <chrono>
#include <memory>
#include <string>
#include <vector>

namespace PocoDDS::Supervisor
{
struct ProcessSpec
{
    std::string id;
    std::string executable;
    std::vector<std::string> arguments;
    std::string workingDirectory;
    std::chrono::milliseconds heartbeatTimeout{0};
};

class Process
{
  public:
    virtual ~Process() = default;
    virtual bool running() = 0;
    virtual int processId() const = 0;
    virtual void terminate(std::chrono::milliseconds gracePeriod) = 0;
};

class ProcessLauncher
{
  public:
    virtual ~ProcessLauncher() = default;
    virtual std::unique_ptr<Process> start(const ProcessSpec& spec) = 0;
};

std::unique_ptr<ProcessLauncher> createNativeProcessLauncher();
} // namespace PocoDDS::Supervisor
