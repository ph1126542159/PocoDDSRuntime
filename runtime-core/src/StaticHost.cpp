#include "PocoDDS/RuntimeCore/StaticHost.h"

#include <algorithm>
#include <deque>
#include <exception>
#include <mutex>
#include <stdexcept>
#include <unordered_map>
#include <utility>

namespace PocoDDS::RuntimeCore
{
namespace
{
RuntimeError failure(RuntimeErrorCode code, std::string message)
{
    return {code, std::move(message), false};
}

RuntimeError componentFailure(const std::string& phase, const ComponentDescriptor& descriptor,
                              RuntimeError error)
{
    if (!error)
        error = failure(RuntimeErrorCode::internalError, "component returned an empty error");
    error.message = phase + " failed for component '" + descriptor.id + "': " + error.message;
    return error;
}

void safeStop(const std::shared_ptr<IHostedComponent>& component) noexcept
{
    try
    {
        component->stop();
    }
    catch (...)
    {
    }
}
} // namespace

struct StaticHost::State
{
    struct Entry
    {
        ComponentDescriptor descriptor;
        std::shared_ptr<IHostedComponent> component;
    };

    mutable std::mutex mutex;
    std::mutex lifecycleMutex;
    std::vector<Entry> entries;
    std::unordered_map<std::string, std::size_t> indexes;
    std::vector<std::size_t> configuredOrder;
    HostEnvironment environment;
    HostState hostState{HostState::empty};
    RuntimeError lastError;

    Outcome<std::vector<std::size_t>> resolveOrder() const
    {
        std::vector<std::size_t> indegrees(entries.size(), 0);
        std::vector<std::vector<std::size_t>> dependents(entries.size());
        for (std::size_t componentIndex = 0; componentIndex < entries.size(); ++componentIndex)
        {
            for (const auto& dependency : entries[componentIndex].descriptor.dependencies)
            {
                const auto found = indexes.find(dependency.id);
                if (found == indexes.end())
                {
                    if (dependency.required)
                        return Outcome<std::vector<std::size_t>>::failure(
                            failure(RuntimeErrorCode::dependencyFailure,
                                    "component '" + entries[componentIndex].descriptor.id +
                                        "' requires missing dependency '" + dependency.id + "'"));
                    continue;
                }
                ++indegrees[componentIndex];
                dependents[found->second].push_back(componentIndex);
            }
        }

        std::deque<std::size_t> ready;
        for (std::size_t index = 0; index < indegrees.size(); ++index)
        {
            if (indegrees[index] == 0)
                ready.push_back(index);
        }

        std::vector<std::size_t> order;
        order.reserve(entries.size());
        while (!ready.empty())
        {
            const auto current = ready.front();
            ready.pop_front();
            order.push_back(current);
            for (const auto dependent : dependents[current])
            {
                if (--indegrees[dependent] == 0)
                    ready.push_back(dependent);
            }
        }
        if (order.size() != entries.size())
            return Outcome<std::vector<std::size_t>>::failure(
                failure(RuntimeErrorCode::dependencyFailure,
                        "component dependency graph contains a cycle"));
        return Outcome<std::vector<std::size_t>>::success(std::move(order));
    }
};

StaticHost::StaticHost() : _state(std::make_unique<State>()) {}

StaticHost::~StaticHost() { stop(); }

Outcome<void> StaticHost::registerComponent(std::shared_ptr<IHostedComponent> component)
{
    std::lock_guard<std::mutex> lifecycleLock(_state->lifecycleMutex);
    if (!component)
        return Outcome<void>::failure(
            failure(RuntimeErrorCode::invalidArgument, "host component cannot be null"));

    ComponentDescriptor descriptor;
    try
    {
        descriptor = component->descriptor();
    }
    catch (const std::exception& exception)
    {
        return Outcome<void>::failure(
            failure(RuntimeErrorCode::internalError,
                    "component descriptor failed: " + std::string(exception.what())));
    }
    catch (...)
    {
        return Outcome<void>::failure(
            failure(RuntimeErrorCode::internalError, "component descriptor failed"));
    }
    if (descriptor.id.empty())
        return Outcome<void>::failure(
            failure(RuntimeErrorCode::invalidArgument, "component id cannot be empty"));

    std::lock_guard<std::mutex> lock(_state->mutex);
    if (_state->hostState != HostState::empty && _state->hostState != HostState::stopped)
        return Outcome<void>::failure(failure(
            RuntimeErrorCode::stopped, "components can only be registered before configuration"));
    if (_state->indexes.count(descriptor.id) != 0)
        return Outcome<void>::failure(failure(RuntimeErrorCode::invalidArgument,
                                              "duplicate component id '" + descriptor.id + "'"));
    const auto index = _state->entries.size();
    _state->indexes.emplace(descriptor.id, index);
    _state->entries.push_back({std::move(descriptor), std::move(component)});
    _state->hostState = HostState::empty;
    return Outcome<void>::success();
}

Outcome<void> StaticHost::configure(HostEnvironment environment)
{
    std::lock_guard<std::mutex> lifecycleLock(_state->lifecycleMutex);
    std::vector<std::size_t> order;
    {
        std::lock_guard<std::mutex> lock(_state->mutex);
        if (_state->hostState != HostState::empty && _state->hostState != HostState::stopped)
            return Outcome<void>::failure(failure(RuntimeErrorCode::invalidArgument,
                                                  "host is not available for configuration"));
        const auto resolved = _state->resolveOrder();
        if (!resolved)
        {
            _state->hostState = HostState::failed;
            _state->lastError = resolved.error();
            return Outcome<void>::failure(resolved.error());
        }
        order = resolved.value();
        _state->environment = std::move(environment);
        _state->hostState = HostState::configuring;
        _state->lastError = {};
    }

    std::vector<std::size_t> configured;
    for (const auto index : order)
    {
        Outcome<void> result = Outcome<void>::success();
        try
        {
            result = _state->entries[index].component->configure(_state->environment);
        }
        catch (const std::exception& exception)
        {
            result =
                Outcome<void>::failure(failure(RuntimeErrorCode::internalError, exception.what()));
        }
        catch (...)
        {
            result = Outcome<void>::failure(
                failure(RuntimeErrorCode::internalError, "unknown configure exception"));
        }
        if (!result)
        {
            for (auto iterator = configured.rbegin(); iterator != configured.rend(); ++iterator)
                safeStop(_state->entries[*iterator].component);
            const auto error =
                componentFailure("configure", _state->entries[index].descriptor, result.error());
            std::lock_guard<std::mutex> lock(_state->mutex);
            _state->configuredOrder.clear();
            _state->hostState = HostState::failed;
            _state->lastError = error;
            return Outcome<void>::failure(error);
        }
        configured.push_back(index);
    }

    {
        std::lock_guard<std::mutex> lock(_state->mutex);
        _state->configuredOrder = std::move(configured);
        _state->hostState = HostState::configured;
    }
    return Outcome<void>::success();
}

Outcome<void> StaticHost::start()
{
    std::lock_guard<std::mutex> lifecycleLock(_state->lifecycleMutex);
    std::vector<std::size_t> order;
    {
        std::lock_guard<std::mutex> lock(_state->mutex);
        if (_state->hostState != HostState::configured)
            return Outcome<void>::failure(
                failure(RuntimeErrorCode::invalidArgument, "host must be configured before start"));
        order = _state->configuredOrder;
        _state->hostState = HostState::starting;
    }

    for (const auto index : order)
    {
        Outcome<void> result = Outcome<void>::success();
        try
        {
            result = _state->entries[index].component->start();
        }
        catch (const std::exception& exception)
        {
            result =
                Outcome<void>::failure(failure(RuntimeErrorCode::internalError, exception.what()));
        }
        catch (...)
        {
            result = Outcome<void>::failure(
                failure(RuntimeErrorCode::internalError, "unknown start exception"));
        }
        if (!result)
        {
            for (auto iterator = order.rbegin(); iterator != order.rend(); ++iterator)
                safeStop(_state->entries[*iterator].component);
            const auto error =
                componentFailure("start", _state->entries[index].descriptor, result.error());
            std::lock_guard<std::mutex> lock(_state->mutex);
            _state->configuredOrder.clear();
            _state->hostState = HostState::failed;
            _state->lastError = error;
            return Outcome<void>::failure(error);
        }
    }

    {
        std::lock_guard<std::mutex> lock(_state->mutex);
        _state->hostState = HostState::running;
    }
    return Outcome<void>::success();
}

void StaticHost::stop() noexcept
{
    std::lock_guard<std::mutex> lifecycleLock(_state->lifecycleMutex);
    std::vector<std::size_t> order;
    {
        std::lock_guard<std::mutex> lock(_state->mutex);
        if (_state->hostState == HostState::empty || _state->hostState == HostState::stopped)
            return;
        _state->hostState = HostState::stopping;
        order = _state->configuredOrder;
    }
    for (auto iterator = order.rbegin(); iterator != order.rend(); ++iterator)
        safeStop(_state->entries[*iterator].component);
    {
        std::lock_guard<std::mutex> lock(_state->mutex);
        _state->configuredOrder.clear();
        _state->hostState = HostState::stopped;
    }
}

HostSnapshot StaticHost::snapshot() const
{
    std::vector<State::Entry> entries;
    HostSnapshot snapshot;
    {
        std::lock_guard<std::mutex> lock(_state->mutex);
        snapshot.state = _state->hostState;
        snapshot.lastError = _state->lastError;
        entries = _state->entries;
        for (const auto index : _state->configuredOrder)
            snapshot.lifecycleOrder.push_back(_state->entries[index].descriptor.id);
    }

    snapshot.health = snapshot.state == HostState::empty     ? HealthState::unknown
                      : snapshot.state == HostState::stopped ? HealthState::stopped
                      : snapshot.state == HostState::failed  ? HealthState::unhealthy
                                                             : HealthState::healthy;
    const bool aggregateHealth = snapshot.state != HostState::empty &&
                                 snapshot.state != HostState::stopped &&
                                 snapshot.state != HostState::failed;
    for (const auto& entry : entries)
    {
        ComponentHealth health;
        try
        {
            health = entry.component->health();
        }
        catch (const std::exception& exception)
        {
            health = {HealthState::unhealthy, exception.what(), {}};
        }
        catch (...)
        {
            health = {HealthState::unhealthy, "health callback threw", {}};
        }
        if (aggregateHealth && health.state == HealthState::unhealthy)
        {
            if (entry.descriptor.required)
                snapshot.health = HealthState::unhealthy;
            else if (snapshot.health == HealthState::healthy)
                snapshot.health = HealthState::degraded;
        }
        else if (aggregateHealth && health.state == HealthState::degraded &&
                 snapshot.health == HealthState::healthy)
            snapshot.health = HealthState::degraded;
        snapshot.components.push_back({entry.descriptor, std::move(health)});
    }
    return snapshot;
}

} // namespace PocoDDS::RuntimeCore
