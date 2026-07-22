#include "PocoDDS/Admin/AdminService.h"

#include "PocoDDS/Observability/BusinessTracer.h"

#include <algorithm>
#include <iterator>
#include <stdexcept>
#include <unordered_set>
#include <utility>

namespace PocoDDS::Admin
{
AdminService::AdminService(Core::ComponentRegistry& registry, Core::Configuration& configuration,
                           LifecycleHandler lifecycleHandler, std::size_t logCapacity,
                           std::size_t traceCapacity)
    : _registry(registry), _configuration(configuration),
      _lifecycleHandler(std::move(lifecycleHandler)), _logCapacity(logCapacity),
      _traceCapacity(traceCapacity)
{
    if (!_lifecycleHandler)
        throw std::invalid_argument("lifecycle handler must not be empty");
    if (_logCapacity == 0 || _traceCapacity == 0)
        throw std::invalid_argument("admin storage capacity must be greater than zero");
}

std::vector<Core::Component> AdminService::topology() const { return _registry.snapshot(); }

Core::Configuration::Values AdminService::configuration() const
{
    return _configuration.snapshot();
}

std::uint64_t AdminService::configurationRevision() const
{
    std::lock_guard lock(_configurationMutex);
    return _localConfigurationRevision;
}

void AdminService::applyConfiguration(const Core::Configuration::Values& changes)
{
    std::lock_guard lock(_configurationMutex);
    _configuration.apply(changes);
    ++_localConfigurationRevision;
}

ConfigurationResult AdminService::applyConfiguration(const std::string& targetId,
                                                     const Core::Configuration::Values& changes,
                                                     std::uint64_t expectedRevision)
{
    if (targetId.empty())
    {
        std::lock_guard lock(_configurationMutex);
        if (expectedRevision != _localConfigurationRevision)
            return {false, "configuration revision conflict", _localConfigurationRevision};
        _configuration.apply(changes);
        return {true, {}, ++_localConfigurationRevision};
    }
    ConfigurationHandler handler;
    {
        std::lock_guard lock(_mutex);
        handler = _configurationHandler;
    }
    if (!handler)
        return {false, "remote configuration routing is unavailable", expectedRevision};
    return handler(targetId, changes, expectedRevision);
}

void AdminService::routeConfiguration(ConfigurationHandler handler)
{
    if (!handler)
        throw std::invalid_argument("configuration handler must not be empty");
    std::lock_guard lock(_mutex);
    _configurationHandler = std::move(handler);
}

LifecycleResult AdminService::execute(const std::string& targetId, const std::string& action)
{
    static const std::unordered_set<std::string> supported{"start", "stop", "restart", "uninstall"};
    if (targetId.empty())
        return {false, "targetId must not be empty"};
    if (supported.count(action) == 0)
        return {false, "unsupported lifecycle action"};
    return _lifecycleHandler(targetId, action);
}

void AdminService::appendLog(LogRecord record)
{
    std::lock_guard lock(_mutex);
    _logs.push_back(std::move(record));
    while (_logs.size() > _logCapacity)
        _logs.pop_front();
}

std::vector<LogRecord> AdminService::logs(const std::optional<std::string>& componentId,
                                          const std::optional<std::string>& traceId) const
{
    std::lock_guard lock(_mutex);
    std::vector<LogRecord> result;
    std::copy_if(_logs.begin(), _logs.end(), std::back_inserter(result),
                 [&](const auto& record)
                 {
                     return (!componentId || record.componentId == *componentId) &&
                            (!traceId || record.traceId == *traceId);
                 });
    return result;
}

void AdminService::appendTrace(TraceNode node)
{
    std::lock_guard lock(_mutex);
    _traces.push_back(std::move(node));
    while (_traces.size() > _traceCapacity)
        _traces.pop_front();
}

void AdminService::appendTrace(const Observability::CompletedSpan& span)
{
    TraceNode node;
    node.traceId = span.traceId;
    node.spanId = span.spanId;
    node.parentSpanId = span.parentSpanId;
    node.operation = span.name;
    node.componentId = span.serviceName;
    node.status = span.status;
    node.durationNanoseconds = span.durationNanoseconds;
    node.inputs = span.inputs;
    node.outputs = span.outputs;
    const auto timestamp = std::chrono::system_clock::now();
    for (const auto& message : span.logs)
    {
        LogRecord record{timestamp, span.serviceName, "info", message, span.traceId, span.spanId};
        node.logs.push_back(record);
        appendLog(std::move(record));
    }
    appendTrace(std::move(node));
}

std::vector<TraceNode> AdminService::trace(const std::string& traceId) const
{
    std::lock_guard lock(_mutex);
    std::vector<TraceNode> result;
    std::copy_if(_traces.begin(), _traces.end(), std::back_inserter(result),
                 [&](const auto& node) { return node.traceId == traceId; });
    return result;
}

std::vector<std::string> AdminService::recentTraceIds() const
{
    std::lock_guard lock(_mutex);
    std::vector<std::string> result;
    std::unordered_set<std::string> seen;
    for (auto it = _traces.rbegin(); it != _traces.rend(); ++it)
        if (seen.insert(it->traceId).second)
            result.push_back(it->traceId);
    return result;
}
} // namespace PocoDDS::Admin
