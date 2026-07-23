#include "PocoDDS/Observability/TraceStore.h"

#include <algorithm>
#include <iterator>
#include <map>
#include <stdexcept>

namespace PocoDDS::Observability
{
TraceStore::TraceStore(std::size_t spanCapacity) : _capacity(spanCapacity)
{
    if (_capacity == 0)
        throw std::invalid_argument("trace store capacity must be greater than zero");
}

void TraceStore::upsert(const SpanSnapshot& span)
{
    std::lock_guard<std::mutex> lock(_mutex);
    const auto found = std::find_if(_spans.begin(), _spans.end(), [&](const auto& current) {
        return current.traceId == span.traceId && current.spanId == span.spanId;
    });
    if (found == _spans.end())
        _spans.push_back(span);
    else
        *found = span;
    while (_spans.size() > _capacity)
        _spans.pop_front();
}

std::vector<TraceSummary> TraceStore::recent(std::size_t limit) const
{
    std::lock_guard<std::mutex> lock(_mutex);
    std::map<std::string, TraceSummary> summaries;
    for (const auto& span : _spans)
    {
        auto& summary = summaries[span.traceId];
        summary.traceId = span.traceId;
        summary.businessName = span.businessName;
        summary.businessInstanceId = span.businessInstanceId;
        ++summary.stepCount;
        if (summary.startedUnixMicroseconds == 0 ||
            span.startedUnixMicroseconds < summary.startedUnixMicroseconds)
            summary.startedUnixMicroseconds = span.startedUnixMicroseconds;
        summary.durationNanoseconds =
            std::max(summary.durationNanoseconds, span.durationNanoseconds);
        if (span.status == "failed")
        {
            summary.status = "failed";
            summary.failedOperation = span.operation;
        }
        else if (summary.status != "failed" && span.status == "running")
            summary.status = "running";
        else if (summary.status.empty())
            summary.status = span.status;
    }
    std::vector<TraceSummary> result;
    for (auto& item : summaries)
        result.push_back(std::move(item.second));
    std::sort(result.begin(), result.end(), [](const auto& left, const auto& right) {
        return left.startedUnixMicroseconds > right.startedUnixMicroseconds;
    });
    if (result.size() > limit)
        result.resize(limit);
    return result;
}

std::vector<SpanSnapshot> TraceStore::trace(const std::string& traceId) const
{
    std::lock_guard<std::mutex> lock(_mutex);
    std::vector<SpanSnapshot> result;
    std::copy_if(_spans.begin(), _spans.end(), std::back_inserter(result),
                 [&](const auto& span) { return span.traceId == traceId; });
    std::sort(result.begin(), result.end(), [](const auto& left, const auto& right) {
        return left.startedUnixMicroseconds < right.startedUnixMicroseconds;
    });
    return result;
}

std::optional<SpanSnapshot> TraceStore::span(const std::string& traceId,
                                             const std::string& spanId) const
{
    std::lock_guard<std::mutex> lock(_mutex);
    const auto found = std::find_if(_spans.begin(), _spans.end(), [&](const auto& span) {
        return span.traceId == traceId && span.spanId == spanId;
    });
    return found == _spans.end() ? std::optional<SpanSnapshot>{} : *found;
}

void TraceStore::clear()
{
    std::lock_guard<std::mutex> lock(_mutex);
    _spans.clear();
}

TraceStore& globalTraceStore()
{
    static TraceStore store;
    return store;
}
} // namespace PocoDDS::Observability
