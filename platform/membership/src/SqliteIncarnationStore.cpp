#include "PocoDDS/Membership/IncarnationStore.h"

#include <Poco/Data/Session.h>
#include <Poco/Exception.h>
#include <Poco/Path.h>

#include <mutex>

using namespace Poco::Data::Keywords;

namespace PocoDDS::Membership
{
class SqliteIncarnationStore::Impl
{
public:
    explicit Impl(const std::string& path)
        : session("SQLite", path)
    {
        if (path.empty())
            throw Poco::InvalidArgumentException(
                "Membership incarnation database path is required");
        session << "PRAGMA journal_mode=WAL", now;
        session << "PRAGMA synchronous=FULL", now;
        session << "PRAGMA busy_timeout=5000", now;
        session << "CREATE TABLE IF NOT EXISTS membership_incarnations ("
                   "instance_id TEXT PRIMARY KEY NOT NULL, "
                   "incarnation INTEGER NOT NULL CHECK(incarnation > 0))",
            now;
    }

    Poco::Data::Session session;
    std::mutex mutex;
};

SqliteIncarnationStore::SqliteIncarnationStore(std::string databasePath)
    : _impl(std::make_unique<Impl>(databasePath))
{
}

SqliteIncarnationStore::~SqliteIncarnationStore() = default;

std::uint64_t SqliteIncarnationStore::next(const std::string& instanceId)
{
    if (instanceId.empty() || instanceId.size() > 128)
        throw Poco::InvalidArgumentException(
            "Membership instanceId must contain 1..128 characters");
    std::lock_guard<std::mutex> lock(_impl->mutex);
    // One SQLite statement is the cross-process serialization boundary. A
    // read-then-update transaction can allocate the same value in two Runtime
    // processes when it starts deferred; UPSERT performs the increment while
    // holding SQLite's writer lock and RETURNING exposes that exact generation.
    Poco::Int64 current = 0;
    _impl->session <<
        "INSERT INTO membership_incarnations(instance_id, incarnation) VALUES(?, 1) "
        "ON CONFLICT(instance_id) DO UPDATE SET incarnation = incarnation + 1 "
        "RETURNING incarnation",
        useRef(instanceId), into(current), now;
    if (current <= 0)
        throw Poco::RangeException("Membership incarnation counter is exhausted");
    return static_cast<std::uint64_t>(current);
}
} // namespace PocoDDS::Membership
