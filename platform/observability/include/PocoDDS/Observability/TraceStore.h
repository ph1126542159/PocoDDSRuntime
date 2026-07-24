#pragma once

#include "PocoDDS/Observability/BusinessTracer.h"

#include <cstddef>
#include <deque>
#include <memory>
#include <mutex>
#include <optional>
#include <string>
#include <vector>

namespace PocoDDS::Observability
{
#if defined(_WIN32)
#if defined(PDRObservability_EXPORTS)
#define PDR_OBSERVABILITY_API __declspec(dllexport)
#else
#define PDR_OBSERVABILITY_API __declspec(dllimport)
#endif
#else
#define PDR_OBSERVABILITY_API
#endif

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

struct TraceHistoryQuery
{
    long long fromUnixMicroseconds{0};
    long long toUnixMicroseconds{0};
    std::string businessName;
    std::string status;
    std::size_t limit{100};
    std::size_t offset{0};
};

struct TraceHistoryResult
{
    std::vector<TraceSummary> records;
    bool hasMore{false};
};

class TraceStore
{
public:
    explicit TraceStore(std::size_t spanCapacity = 10000);
    ~TraceStore();

    void upsert(const SpanSnapshot& span);
    std::vector<TraceSummary> recent(std::size_t limit = 200) const;
    std::vector<SpanSnapshot> trace(const std::string& traceId) const;
    std::optional<SpanSnapshot> span(const std::string& traceId,
                                     const std::string& spanId) const;
    void configurePersistence(const std::string& directory,
                              unsigned retentionDays = 10);
    TraceHistoryResult history(const TraceHistoryQuery& query) const;
    void clear();

private:
    class Persistence;
    std::size_t _capacity;
    mutable std::mutex _mutex;
    std::deque<SpanSnapshot> _spans;
    std::unique_ptr<Persistence> _persistence;
};

PDR_OBSERVABILITY_API TraceStore& globalTraceStore();

using TraceHistoryCallback = void (*)(
    void* context, const char* traceId, const char* businessName,
    const char* businessInstanceId, const char* status,
    long long startedUnixMicroseconds, long long durationNanoseconds,
    std::size_t stepCount, const char* failedOperation);

extern "C"
{
PDR_OBSERVABILITY_API void pdrConfigureTracePersistence(
    const char* directory, unsigned retentionDays);
PDR_OBSERVABILITY_API bool pdrQueryTraceHistory(
    long long fromUnixMicroseconds, long long toUnixMicroseconds,
    const char* businessName, const char* status, std::size_t limit,
    std::size_t offset, TraceHistoryCallback callback, void* context);
}

} // namespace PocoDDS::Observability
