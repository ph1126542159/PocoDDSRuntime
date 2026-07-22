#include "PocoDDS/Supervisor/Supervisor.h"

#include <stdexcept>

namespace PocoDDS::Supervisor
{
Supervisor::Supervisor(Core::ComponentRegistry& registry, std::unique_ptr<ProcessLauncher> launcher)
    : _registry(registry), _launcher(std::move(launcher))
{
    if (!_launcher)
        throw std::invalid_argument("process launcher must not be null");
}

Supervisor::~Supervisor()
{
    std::lock_guard lock(_mutex);
    for (auto& [id, managed] : _managed)
    {
        static_cast<void>(id);
        if (managed.process && managed.process->running())
            managed.process->terminate(std::chrono::seconds(3));
    }
}

void Supervisor::add(ProcessSpec spec, RestartPolicy policy)
{
    if (spec.id.empty() || spec.executable.empty())
        throw std::invalid_argument("process id and executable are required");
    std::lock_guard lock(_mutex);
    const auto id = spec.id;
    if (!_managed.emplace(id, Managed{std::move(spec), policy}).second)
        throw std::runtime_error("process already registered");
}

void Supervisor::start(const std::string& id)
{
    std::lock_guard lock(_mutex);
    auto& managed = _managed.at(id);
    managed.desiredRunning = true;
    if (!managed.process || !managed.process->running())
        launch(managed);
}

void Supervisor::stop(const std::string& id)
{
    std::lock_guard lock(_mutex);
    auto& managed = _managed.at(id);
    managed.desiredRunning = false;
    publish(managed, Core::ComponentState::Stopping);
    if (managed.process && managed.process->running())
        managed.process->terminate(std::chrono::seconds(3));
    managed.process.reset();
    publish(managed, Core::ComponentState::Stopped);
}

void Supervisor::restart(const std::string& id)
{
    std::lock_guard lock(_mutex);
    auto& managed = _managed.at(id);
    managed.desiredRunning = true;
    publish(managed, Core::ComponentState::Stopping);
    if (managed.process && managed.process->running())
        managed.process->terminate(std::chrono::seconds(3));
    managed.process.reset();
    managed.restarts.clear();
    launch(managed);
}

void Supervisor::remove(const std::string& id)
{
    std::lock_guard lock(_mutex);
    const auto found = _managed.find(id);
    if (found == _managed.end())
        throw std::out_of_range("process is not registered");
    auto& managed = found->second;
    managed.desiredRunning = false;
    publish(managed, Core::ComponentState::Stopping);
    if (managed.process && managed.process->running())
        managed.process->terminate(std::chrono::seconds(3));
    _managed.erase(found);
    _registry.remove(id);
}

void Supervisor::heartbeat(const std::string& id)
{
    std::lock_guard lock(_mutex);
    _managed.at(id).lastHeartbeat = std::chrono::steady_clock::now();
}

void Supervisor::poll()
{
    std::lock_guard lock(_mutex);
    const auto now = std::chrono::steady_clock::now();
    for (auto& [id, managed] : _managed)
    {
        static_cast<void>(id);
        if (!managed.desiredRunning || !managed.process)
            continue;
        const auto timedOut = managed.spec.heartbeatTimeout.count() > 0 &&
                              now - managed.lastHeartbeat > managed.spec.heartbeatTimeout;
        if (managed.process->running() && timedOut)
            managed.process->terminate(std::chrono::milliseconds(0));
        if (managed.process->running())
            continue;
        publish(managed, Core::ComponentState::Failed);
        while (!managed.restarts.empty() && now - managed.restarts.front() > managed.policy.window)
            managed.restarts.pop_front();
        if (managed.restarts.size() >= managed.policy.maximumRestarts)
        {
            managed.desiredRunning = false;
            continue;
        }
        managed.restarts.push_back(now);
        launch(managed);
    }
}

void Supervisor::launch(Managed& managed)
{
    publish(managed, Core::ComponentState::Starting);
    managed.process = _launcher->start(managed.spec);
    if (!managed.process || !managed.process->running())
    {
        managed.process.reset();
        publish(managed, Core::ComponentState::Failed);
        return;
    }
    managed.lastHeartbeat = std::chrono::steady_clock::now();
    publish(managed, Core::ComponentState::Running);
}

void Supervisor::publish(const Managed& managed, Core::ComponentState state)
{
    _registry.upsert({managed.spec.id,
                      managed.spec.id,
                      "localhost",
                      managed.process ? managed.process->processId() : 0,
                      Core::ComponentKind::Process,
                      state,
                      {{"executable", managed.spec.executable}}});
}
} // namespace PocoDDS::Supervisor
