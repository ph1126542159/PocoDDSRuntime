#pragma once

#include "PocoDDS/Core/ComponentRegistry.h"
#include "PocoDDS/Core/Configuration.h"

#include <chrono>
#include <deque>
#include <functional>
#include <map>
#include <mutex>
#include <optional>
#include <string>
#include <vector>

namespace PocoDDS::Admin
{
struct LogRecord
{
    std::chrono::system_clock::time_point timestamp;
    std::string componentId;
    std::string level;
    std::string message;
    std::string traceId;
    std::string spanId;
};

struct TraceNode
{
    std::string traceId;
    std::string spanId;
    std::string parentSpanId;
    std::string operation;
    std::string componentId;
    std::string status;
    long long durationNanoseconds{0};
    std::map<std::string, std::string> inputs;
    std::map<std::string, std::string> outputs;
    std::vector<LogRecord> logs;
};

struct LifecycleResult
{
    bool success{false};
    std::string message;
};

class AdminService
{
  public:
    using LifecycleHandler =
        std::function<LifecycleResult(const std::string& targetId, const std::string& action)>;

    AdminService(Core::ComponentRegistry& registry, Core::Configuration& configuration,
                 LifecycleHandler lifecycleHandler, std::size_t logCapacity = 10000,
                 std::size_t traceCapacity = 10000);

    std::vector<Core::Component> topology() const;
    Core::Configuration::Values configuration() const;
    void applyConfiguration(const Core::Configuration::Values& changes);
    LifecycleResult execute(const std::string& targetId, const std::string& action);

    void appendLog(LogRecord record);
    std::vector<LogRecord> logs(const std::optional<std::string>& componentId = {},
                                const std::optional<std::string>& traceId = {}) const;
    void appendTrace(TraceNode node);
    std::vector<TraceNode> trace(const std::string& traceId) const;
    std::vector<std::string> recentTraceIds() const;

  private:
    Core::ComponentRegistry& _registry;
    Core::Configuration& _configuration;
    LifecycleHandler _lifecycleHandler;
    std::size_t _logCapacity;
    std::size_t _traceCapacity;
    mutable std::mutex _mutex;
    std::deque<LogRecord> _logs;
    std::deque<TraceNode> _traces;
};
} // namespace PocoDDS::Admin
