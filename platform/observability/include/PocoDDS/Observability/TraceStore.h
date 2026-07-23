#pragma once

#include "PocoDDS/Observability/BusinessTracer.h"

#include <cstddef>
#include <deque>
#include <mutex>
#include <optional>
#include <string>
#include <vector>

namespace PocoDDS::Observability
{
struct TraceSummary
{
    std::string traceId;
    std::string businessName;
    std::string businessInstanceId;
    std::string status;
    long long startedUnixMicroseconds{0};
    long long durationNanoseconds{0};
    std::size_t stepCount{0};
    std::string failedOperation;
};

class TraceStore
{
public:
    explicit TraceStore(std::size_t spanCapacity = 10000);

    void upsert(const SpanSnapshot& span);
    std::vector<TraceSummary> recent(std::size_t limit = 200) const;
    std::vector<SpanSnapshot> trace(const std::string& traceId) const;
    std::optional<SpanSnapshot> span(const std::string& traceId,
                                     const std::string& spanId) const;
    void clear();

private:
    std::size_t _capacity;
    mutable std::mutex _mutex;
    std::deque<SpanSnapshot> _spans;
};

TraceStore& globalTraceStore();
} // namespace PocoDDS::Observability
