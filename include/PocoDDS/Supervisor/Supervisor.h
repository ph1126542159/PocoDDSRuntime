#pragma once

#include "PocoDDS/Core/ComponentRegistry.h"
#include "PocoDDS/Supervisor/Process.h"

#include <chrono>
#include <deque>
#include <memory>
#include <mutex>
#include <string>
#include <unordered_map>

namespace PocoDDS::Supervisor
{
struct RestartPolicy
{
    std::size_t maximumRestarts{3};
    std::chrono::milliseconds window{std::chrono::minutes(1)};
};

class Supervisor
{
  public:
    Supervisor(Core::ComponentRegistry& registry, std::unique_ptr<ProcessLauncher> launcher);
    ~Supervisor();

    void add(ProcessSpec spec, RestartPolicy policy = {});
    void start(const std::string& id);
    void stop(const std::string& id);
    void heartbeat(const std::string& id);
    void poll();

  private:
    struct Managed
    {
        ProcessSpec spec;
        RestartPolicy policy;
        std::unique_ptr<Process> process;
        std::deque<std::chrono::steady_clock::time_point> restarts;
        std::chrono::steady_clock::time_point lastHeartbeat{};
        bool desiredRunning{false};
    };

    void launch(Managed& managed);
    void publish(const Managed& managed, Core::ComponentState state);

    Core::ComponentRegistry& _registry;
    std::unique_ptr<ProcessLauncher> _launcher;
    std::mutex _mutex;
    std::unordered_map<std::string, Managed> _managed;
};
} // namespace PocoDDS::Supervisor
