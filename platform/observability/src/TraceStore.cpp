#include "PocoDDS/Observability/TraceStore.h"
#include "PocoDDS/Observability/TraceSerialization.h"

#include <Poco/Data/Session.h>
#include <Poco/Data/Statement.h>
#include <Poco/Data/SQLite/Connector.h>
#include <Poco/DateTime.h>
#include <Poco/DateTimeFormatter.h>
#include <Poco/File.h>
#include <Poco/Path.h>
#include <Poco/Timestamp.h>

#include <algorithm>
#include <chrono>
#include <iterator>
#include <map>
#include <stdexcept>

namespace PocoDDS::Observability
{
using namespace Poco::Data::Keywords;

class TraceStore::Persistence
{
public:
    Persistence(std::string directory, unsigned retentionDays)
        : _directory(std::move(directory)),
          _retentionMicroseconds(static_cast<long long>(retentionDays) * 24LL * 60LL *
                                 60LL * 1000000LL)
    {
        if (retentionDays == 0)
            throw std::invalid_argument("trace history retention must be greater than zero");
        Poco::File(_directory).createDirectories();
        Poco::Data::SQLite::Connector::registerConnector();
        Poco::Data::Session catalog("SQLite", catalogPath());
        catalog << "PRAGMA journal_mode=WAL", now;
        catalog << "PRAGMA synchronous=NORMAL", now;
        catalog << "CREATE TABLE IF NOT EXISTS shards ("
                   "hour_key TEXT PRIMARY KEY, file_name TEXT NOT NULL UNIQUE, "
                   "start_us INTEGER NOT NULL, end_us INTEGER NOT NULL, updated_us INTEGER NOT NULL)",
            now;
        catalog << "CREATE INDEX IF NOT EXISTS idx_shards_range ON shards(start_us, end_us)",
            now;
        purgeExpired();
    }

    void upsert(const SpanSnapshot& span)
    {
        if (span.startedUnixMicroseconds <
            Poco::Timestamp().epochMicroseconds() - _retentionMicroseconds)
            return;
        const std::string key = hourKey(span.startedUnixMicroseconds);
        const std::string fileName = "business-traces-" + key + ".sqlite";
        Poco::Data::Session shard("SQLite", shardPath(fileName));
        initializeShard(shard);

        const std::string payload = serializeSpanSnapshot(span);
        shard << "INSERT INTO spans(trace_id,span_id,started_us,payload) VALUES(?,?,?,?) "
                 "ON CONFLICT(trace_id,span_id) DO UPDATE SET "
                 "started_us=excluded.started_us,payload=excluded.payload",
            useRef(span.traceId), useRef(span.spanId),
            useRef(span.startedUnixMicroseconds), useRef(payload), now;

        const std::string failedOperation =
            span.status == "failed" ? span.operation : std::string{};
        shard << "INSERT INTO traces(trace_id,business_name,instance_id,status,started_us,"
                 "duration_ns,step_count,failed_operation) VALUES(?,?,?,?,?,?,1,?) "
                 "ON CONFLICT(trace_id) DO UPDATE SET "
                 "business_name=excluded.business_name,instance_id=excluded.instance_id,"
                 "status=CASE WHEN traces.status='failed' THEN traces.status "
                 "WHEN excluded.status='failed' THEN excluded.status "
                 "WHEN excluded.status='running' THEN excluded.status ELSE excluded.status END,"
                 "started_us=MIN(traces.started_us,excluded.started_us),"
                 "duration_ns=MAX(traces.duration_ns,excluded.duration_ns),"
                 "step_count=(SELECT COUNT(*) FROM spans WHERE trace_id=excluded.trace_id),"
                 "failed_operation=CASE WHEN excluded.status='failed' "
                 "THEN excluded.failed_operation ELSE traces.failed_operation END",
            useRef(span.traceId), useRef(span.businessName),
            useRef(span.businessInstanceId), useRef(span.status),
            useRef(span.startedUnixMicroseconds), useRef(span.durationNanoseconds),
            useRef(failedOperation), now;

        const long long hourStart = hourStartMicroseconds(span.startedUnixMicroseconds);
        const long long hourEnd = hourStart + 60LL * 60LL * 1000000LL - 1;
        const long long updated = Poco::Timestamp().epochMicroseconds();
        Poco::Data::Session catalog("SQLite", catalogPath());
        catalog << "INSERT INTO shards(hour_key,file_name,start_us,end_us,updated_us) "
                   "VALUES(?,?,?,?,?) ON CONFLICT(hour_key) DO UPDATE SET "
                   "file_name=excluded.file_name,updated_us=excluded.updated_us",
            useRef(key), useRef(fileName), useRef(hourStart), useRef(hourEnd),
            useRef(updated), now;

        if (++_writesSincePurge >= 1000)
        {
            _writesSincePurge = 0;
            purgeExpired();
        }
    }

    TraceHistoryResult history(const TraceHistoryQuery& configured) const
    {
        TraceHistoryQuery query = configured;
        query.limit = std::clamp<std::size_t>(query.limit, 1, 1000);
        const long long nowUs = Poco::Timestamp().epochMicroseconds();
        if (query.toUnixMicroseconds <= 0) query.toUnixMicroseconds = nowUs;
        if (query.fromUnixMicroseconds <= 0)
            query.fromUnixMicroseconds = query.toUnixMicroseconds - _retentionMicroseconds;

        std::vector<std::string> files;
        Poco::Data::Session catalog("SQLite", catalogPath());
        catalog << "SELECT file_name FROM shards WHERE end_us>=? AND start_us<=? "
                   "ORDER BY start_us DESC",
            use(query.fromUnixMicroseconds), use(query.toUnixMicroseconds), into(files), now;

        std::vector<TraceSummary> all;
        const std::string namePattern = "%" + query.businessName + "%";
        const int perShardLimit = static_cast<int>(
            std::min<std::size_t>(query.limit + query.offset + 1, 5000));
        for (const auto& file : files)
        {
            const std::string path = shardPath(file);
            if (!Poco::File(path).exists()) continue;
            Poco::Data::Session shard("SQLite", path);
            std::vector<std::string> traceIds, names, instances, statuses, failedOperations;
            std::vector<long long> starts, durations;
            std::vector<int> steps;
            shard << "SELECT trace_id,business_name,instance_id,status,started_us,duration_ns,"
                     "step_count,failed_operation FROM traces "
                     "WHERE started_us>=? AND started_us<=? "
                     "AND (?='' OR business_name LIKE ?) AND (?='' OR status=?) "
                     "ORDER BY started_us DESC LIMIT ?",
                use(query.fromUnixMicroseconds), use(query.toUnixMicroseconds),
                use(query.businessName), useRef(namePattern), use(query.status),
                use(query.status), useRef(perShardLimit), into(traceIds), into(names),
                into(instances), into(statuses), into(starts), into(durations),
                into(steps), into(failedOperations), now;
            for (std::size_t index = 0; index < traceIds.size(); ++index)
            {
                TraceSummary summary;
                summary.traceId = traceIds[index];
                summary.businessName = names[index];
                summary.businessInstanceId = instances[index];
                summary.status = statuses[index];
                summary.startedUnixMicroseconds = starts[index];
                summary.durationNanoseconds = durations[index];
                summary.stepCount = static_cast<std::size_t>(steps[index]);
                summary.failedOperation = failedOperations[index];
                all.push_back(std::move(summary));
            }
        }
        std::sort(all.begin(), all.end(), [](const auto& left, const auto& right) {
            return left.startedUnixMicroseconds > right.startedUnixMicroseconds;
        });
        const std::size_t begin = std::min(query.offset, all.size());
        const std::size_t end = std::min(begin + query.limit, all.size());
        TraceHistoryResult result;
        result.hasMore = end < all.size();
        result.records.assign(all.begin() + static_cast<std::ptrdiff_t>(begin),
                              all.begin() + static_cast<std::ptrdiff_t>(end));
        return result;
    }

private:
    static long long hourStartMicroseconds(long long value)
    {
        constexpr long long hour = 60LL * 60LL * 1000000LL;
        return (value / hour) * hour;
    }

    static std::string hourKey(long long value)
    {
        const Poco::DateTime time(Poco::Timestamp(hourStartMicroseconds(value)));
        return Poco::DateTimeFormatter::format(time, "%Y%m%d-%H");
    }

    std::string catalogPath() const
    {
        return Poco::Path(_directory, "business-traces-catalog.sqlite").toString();
    }

    std::string shardPath(const std::string& fileName) const
    {
        return Poco::Path(_directory, fileName).toString();
    }

    static void initializeShard(Poco::Data::Session& shard)
    {
        shard << "PRAGMA journal_mode=WAL", now;
        shard << "PRAGMA synchronous=NORMAL", now;
        shard << "CREATE TABLE IF NOT EXISTS spans ("
                 "trace_id TEXT NOT NULL, span_id TEXT NOT NULL, started_us INTEGER NOT NULL,"
                 "payload TEXT NOT NULL, PRIMARY KEY(trace_id,span_id))",
            now;
        shard << "CREATE TABLE IF NOT EXISTS traces ("
                 "trace_id TEXT PRIMARY KEY,business_name TEXT NOT NULL,instance_id TEXT NOT NULL,"
                 "status TEXT NOT NULL,started_us INTEGER NOT NULL,duration_ns INTEGER NOT NULL,"
                 "step_count INTEGER NOT NULL,failed_operation TEXT NOT NULL)",
            now;
        shard << "CREATE INDEX IF NOT EXISTS idx_traces_started ON traces(started_us DESC)",
            now;
        shard << "CREATE INDEX IF NOT EXISTS idx_traces_filter "
                 "ON traces(business_name,status,started_us DESC)",
            now;
    }

    void purgeExpired()
    {
        const long long cutoff = Poco::Timestamp().epochMicroseconds() - _retentionMicroseconds;
        std::vector<std::string> expired;
        Poco::Data::Session catalog("SQLite", catalogPath());
        catalog << "SELECT file_name FROM shards WHERE end_us<?", useRef(cutoff),
            into(expired), now;
        catalog << "DELETE FROM shards WHERE end_us<?", useRef(cutoff), now;
        for (const auto& file : expired)
        {
            Poco::File database(shardPath(file));
            if (database.exists()) database.remove();
            Poco::File wal(shardPath(file) + "-wal");
            if (wal.exists()) wal.remove();
            Poco::File shm(shardPath(file) + "-shm");
            if (shm.exists()) shm.remove();
        }
    }

    std::string _directory;
    long long _retentionMicroseconds;
    unsigned _writesSincePurge{0};
};

TraceStore::TraceStore(std::size_t spanCapacity) : _capacity(spanCapacity)
{
    if (_capacity == 0)
        throw std::invalid_argument("trace store capacity must be greater than zero");
}

TraceStore::~TraceStore() = default;

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
    if (_persistence)
        _persistence->upsert(span);
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

void TraceStore::configurePersistence(const std::string& directory,
                                      unsigned retentionDays)
{
    std::lock_guard<std::mutex> lock(_mutex);
    _persistence = std::make_unique<Persistence>(directory, retentionDays);
}

TraceHistoryResult TraceStore::history(const TraceHistoryQuery& query) const
{
    std::lock_guard<std::mutex> lock(_mutex);
    return _persistence ? _persistence->history(query) : TraceHistoryResult{};
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

extern "C" PDR_OBSERVABILITY_API void pdrConfigureTracePersistence(
    const char* directory, unsigned retentionDays)
{
    globalTraceStore().configurePersistence(directory ? directory : "",
                                            retentionDays);
}

extern "C" PDR_OBSERVABILITY_API bool pdrQueryTraceHistory(
    long long fromUnixMicroseconds, long long toUnixMicroseconds,
    const char* businessName, const char* status, std::size_t limit,
    std::size_t offset, TraceHistoryCallback callback, void* context)
{
    TraceHistoryQuery query;
    query.fromUnixMicroseconds = fromUnixMicroseconds;
    query.toUnixMicroseconds = toUnixMicroseconds;
    query.businessName = businessName ? businessName : "";
    query.status = status ? status : "";
    query.limit = limit;
    query.offset = offset;
    const auto result = globalTraceStore().history(query);
    if (callback)
        for (const auto& record : result.records)
            callback(context, record.traceId.c_str(), record.businessName.c_str(),
                     record.businessInstanceId.c_str(), record.status.c_str(),
                     record.startedUnixMicroseconds, record.durationNanoseconds,
                     record.stepCount, record.failedOperation.c_str());
    return result.hasMore;
}
} // namespace PocoDDS::Observability
