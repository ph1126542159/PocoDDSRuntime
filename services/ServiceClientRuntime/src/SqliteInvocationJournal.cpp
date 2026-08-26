#include "SqliteInvocationJournal.h"

#include "PocoDDS/ServiceClient/RuntimeCoordinator.h"

#include <Poco/Data/SQLite/Connector.h>
#include <Poco/Data/Session.h>
#include <Poco/Data/Statement.h>
#include <Poco/Exception.h>
#include <Poco/File.h>
#include <Poco/JSON/Array.h>
#include <Poco/JSON/Object.h>
#include <Poco/JSON/Parser.h>
#include <Poco/Path.h>

#include <algorithm>
#include <cctype>
#include <limits>
#include <mutex>
#include <sstream>
#include <stdexcept>
#include <utility>
#include <vector>

namespace PocoDDS::ServiceClient
{
using namespace Poco::Data::Keywords;

namespace
{
constexpr const char* IN_FLIGHT = "in-flight";
constexpr const char* COMPLETED = "completed";

std::string hex(const std::vector<std::uint8_t>& payload)
{
    constexpr char digits[] = "0123456789abcdef";
    std::string result(payload.size() * 2, '0');
    for (std::size_t index = 0; index < payload.size(); ++index)
    {
        result[index * 2] = digits[payload[index] >> 4];
        result[index * 2 + 1] = digits[payload[index] & 0x0f];
    }
    return result;
}

std::vector<std::uint8_t> unhex(const std::string& value)
{
    if (value.size() % 2 != 0)
        throw Poco::DataFormatException(
            "Invocation journal payload has invalid hex length");
    const auto nibble = [](unsigned char character) -> std::uint8_t {
        if (character >= '0' && character <= '9') return character - '0';
        character = static_cast<unsigned char>(std::tolower(character));
        if (character >= 'a' && character <= 'f')
            return static_cast<std::uint8_t>(character - 'a' + 10);
        throw Poco::DataFormatException(
            "Invocation journal payload has invalid hex data");
    };
    std::vector<std::uint8_t> result(value.size() / 2);
    for (std::size_t index = 0; index < result.size(); ++index)
        result[index] = static_cast<std::uint8_t>(
            (nibble(value[index * 2]) << 4) |
            nibble(value[index * 2 + 1]));
    return result;
}

template <typename Enum>
Enum checkedEnum(int value, int maximum, const char* name)
{
    if (value < 0 || value > maximum)
        throw Poco::DataFormatException(
            std::string("Invocation journal has invalid ") + name);
    return static_cast<Enum>(value);
}

Poco::JSON::Object::Ptr instanceJson(
    const ServiceDirectory::InstanceSnapshot& instance)
{
    Poco::JSON::Object::Ptr result = new Poco::JSON::Object;
    const auto& advertisement = instance.advertisement;
    result->set("serviceName", advertisement.serviceName);
    result->set("instanceId", advertisement.instanceId);
    result->set("endpoint", advertisement.endpoint);
    result->set("protocol", advertisement.protocol);
    result->set("zone", advertisement.zone);
    Poco::JSON::Array::Ptr tags = new Poco::JSON::Array;
    for (const auto& tag : advertisement.tags) tags->add(tag);
    result->set("tags", tags);
    result->set("advertisedState", static_cast<int>(advertisement.state));
    result->set("runtimeId", advertisement.runtimeId);
    result->set("runtimeIncarnation",
                static_cast<Poco::UInt64>(advertisement.runtimeIncarnation));
    result->set("revision", static_cast<Poco::UInt64>(advertisement.revision));
    result->set("state", static_cast<int>(instance.state));
    result->set("ageMilliseconds",
                static_cast<Poco::Int64>(instance.age.count()));
    return result;
}

ServiceDirectory::InstanceSnapshot parseInstance(
    const Poco::JSON::Object::Ptr& value)
{
    if (!value)
        throw Poco::DataFormatException(
            "Invocation journal instance is missing");
    ServiceDirectory::InstanceSnapshot result;
    auto& advertisement = result.advertisement;
    advertisement.serviceName = value->getValue<std::string>("serviceName");
    advertisement.instanceId = value->getValue<std::string>("instanceId");
    advertisement.endpoint = value->getValue<std::string>("endpoint");
    advertisement.protocol = value->getValue<std::string>("protocol");
    advertisement.zone = value->getValue<std::string>("zone");
    const auto tags = value->getArray("tags");
    if (!tags)
        throw Poco::DataFormatException(
            "Invocation journal instance tags are missing");
    for (std::size_t index = 0; index < tags->size(); ++index)
        advertisement.tags.push_back(tags->getElement<std::string>(
            static_cast<unsigned>(index)));
    advertisement.state = checkedEnum<ServiceDirectory::AdvertisedState>(
        value->getValue<int>("advertisedState"), 1, "advertised state");
    advertisement.runtimeId = value->getValue<std::string>("runtimeId");
    advertisement.runtimeIncarnation =
        value->getValue<Poco::UInt64>("runtimeIncarnation");
    advertisement.revision = value->getValue<Poco::UInt64>("revision");
    result.state = checkedEnum<ServiceDirectory::InstanceState>(
        value->getValue<int>("state"), 2, "instance state");
    result.age = std::chrono::milliseconds(
        value->getValue<Poco::Int64>("ageMilliseconds"));
    return result;
}

std::string serialize(const InvocationCompletion& completion)
{
    Poco::JSON::Object root;
    root.set("schemaVersion", 1);
    root.set("invocationId", completion.invocationId);
    Poco::JSON::Object::Ptr governance = new Poco::JSON::Object;
    governance->set("owner", completion.governance.owner);
    governance->set("workId", completion.governance.workId);
    governance->set("status", static_cast<int>(completion.governance.status));
    governance->set("message", completion.governance.message);
    governance->set("queueMicroseconds",
                    static_cast<Poco::Int64>(
                        completion.governance.queueDuration.count()));
    governance->set("executionMicroseconds",
                    static_cast<Poco::Int64>(
                        completion.governance.executionDuration.count()));
    root.set("governance", governance);
    root.set("hasInvocation", completion.invocation.has_value());
    if (completion.invocation)
    {
        const auto& invocation = *completion.invocation;
        Poco::JSON::Object::Ptr value = new Poco::JSON::Object;
        value->set("status", static_cast<int>(invocation.status));
        value->set("attempts", static_cast<Poco::UInt64>(invocation.attempts));
        value->set("payloadHex", hex(invocation.payload));
        value->set("code", invocation.code);
        value->set("detail", invocation.detail);
        value->set("hasInstance", invocation.instance.has_value());
        if (invocation.instance)
            value->set("instance", instanceJson(*invocation.instance));
        Poco::JSON::Array::Ptr history = new Poco::JSON::Array;
        for (const auto& attempt : invocation.history)
        {
            Poco::JSON::Object::Ptr item = new Poco::JSON::Object;
            item->set("attempt", static_cast<Poco::UInt64>(attempt.attempt));
            item->set("instanceId", attempt.instanceId);
            item->set("runtimeId", attempt.runtimeId);
            item->set("runtimeIncarnation",
                      static_cast<Poco::UInt64>(attempt.runtimeIncarnation));
            item->set("disposition", static_cast<int>(attempt.disposition));
            item->set("code", attempt.code);
            history->add(item);
        }
        value->set("history", history);
        root.set("invocation", value);
    }
    std::ostringstream stream;
    root.stringify(stream);
    return stream.str();
}

InvocationCompletion deserialize(const std::string& payload)
{
    const auto root = Poco::JSON::Parser().parse(payload)
        .extract<Poco::JSON::Object::Ptr>();
    if (!root || root->getValue<int>("schemaVersion") != 1)
        throw Poco::DataFormatException(
            "Unsupported invocation journal completion schema");
    InvocationCompletion completion;
    completion.invocationId = root->getValue<std::string>("invocationId");
    const auto governance = root->getObject("governance");
    if (!governance)
        throw Poco::DataFormatException(
            "Invocation journal governance completion is missing");
    completion.governance.owner =
        governance->getValue<std::string>("owner");
    completion.governance.workId =
        governance->getValue<std::string>("workId");
    completion.governance.status =
        checkedEnum<ResourceGovernance::CompletionStatus>(
            governance->getValue<int>("status"), 5, "completion status");
    completion.governance.message =
        governance->getValue<std::string>("message");
    completion.governance.queueDuration = std::chrono::microseconds(
        governance->getValue<Poco::Int64>("queueMicroseconds"));
    completion.governance.executionDuration = std::chrono::microseconds(
        governance->getValue<Poco::Int64>("executionMicroseconds"));
    if (!root->getValue<bool>("hasInvocation")) return completion;

    const auto value = root->getObject("invocation");
    if (!value)
        throw Poco::DataFormatException(
            "Invocation journal invocation result is missing");
    InvocationResult invocation;
    invocation.status = checkedEnum<InvocationStatus>(
        value->getValue<int>("status"), 7, "invocation status");
    invocation.attempts = static_cast<std::size_t>(
        value->getValue<Poco::UInt64>("attempts"));
    invocation.payload = unhex(value->getValue<std::string>("payloadHex"));
    invocation.code = value->getValue<std::string>("code");
    invocation.detail = value->getValue<std::string>("detail");
    if (value->getValue<bool>("hasInstance"))
        invocation.instance = parseInstance(value->getObject("instance"));
    const auto history = value->getArray("history");
    if (!history)
        throw Poco::DataFormatException(
            "Invocation journal attempt history is missing");
    for (std::size_t index = 0; index < history->size(); ++index)
    {
        const auto item = history->getObject(static_cast<unsigned>(index));
        if (!item)
            throw Poco::DataFormatException(
                "Invocation journal attempt record is invalid");
        AttemptRecord attempt;
        attempt.attempt = static_cast<std::size_t>(
            item->getValue<Poco::UInt64>("attempt"));
        attempt.instanceId = item->getValue<std::string>("instanceId");
        attempt.runtimeId = item->getValue<std::string>("runtimeId");
        attempt.runtimeIncarnation =
            item->getValue<Poco::UInt64>("runtimeIncarnation");
        attempt.disposition = checkedEnum<AttemptDisposition>(
            item->getValue<int>("disposition"), 2,
            "attempt disposition");
        attempt.code = item->getValue<std::string>("code");
        invocation.history.push_back(std::move(attempt));
    }
    completion.invocation = std::move(invocation);
    return completion;
}
} // namespace

class SqliteInvocationJournal::Impl
{
public:
    Impl(std::string databasePath, std::size_t maximum,
         std::chrono::milliseconds retention)
        : path(std::move(databasePath)), maximumEntries(maximum),
          retentionMicroseconds(
              std::chrono::duration_cast<std::chrono::microseconds>(retention)
                  .count())
    {
    }

    void initialize()
    {
        if (path.empty())
            throw Poco::InvalidArgumentException(
                "Invocation journal database path is empty");
        if (maximumEntries == 0 || maximumEntries > 100000 ||
            retentionMicroseconds < 1000000)
            throw Poco::InvalidArgumentException(
                "Invocation journal limits are invalid");
        Poco::Path database(path);
        if (database.depth() > 0)
            Poco::File(database.makeParent()).createDirectories();
        Poco::Data::SQLite::Connector::registerConnector();
        session = std::make_unique<Poco::Data::Session>("SQLite", path);
        (*session) << "PRAGMA journal_mode=WAL", now;
        (*session) << "PRAGMA synchronous=FULL", now;
        (*session)
            << "CREATE TABLE IF NOT EXISTS invocation_journal_metadata ("
               "key TEXT PRIMARY KEY,value TEXT NOT NULL)", now;
        (*session)
            << "INSERT OR IGNORE INTO invocation_journal_metadata(key,value) "
               "VALUES('schema_version','1')", now;
        std::vector<std::string> versions;
        (*session)
            << "SELECT value FROM invocation_journal_metadata "
               "WHERE key='schema_version'",
            into(versions), now;
        if (versions.size() != 1 || versions.front() != "1")
            throw Poco::DataFormatException(
                "Unsupported invocation journal database schema");
        (*session)
            << "CREATE TABLE IF NOT EXISTS invocation_journal ("
               "scope_digest TEXT PRIMARY KEY,request_digest TEXT NOT NULL,"
               "invocation_id TEXT NOT NULL,state TEXT NOT NULL,"
               "created_us INTEGER NOT NULL,updated_us INTEGER NOT NULL,"
               "expires_us INTEGER NOT NULL,completion_json TEXT NOT NULL)", now;
        (*session)
            << "CREATE INDEX IF NOT EXISTS idx_invocation_journal_expiry "
               "ON invocation_journal(state,expires_us,updated_us)", now;
        refreshCounts();
        snapshotValue.enabled = true;
        snapshotValue.durable = true;
        snapshotValue.healthy = true;
        snapshotValue.backend = "sqlite-wal-full";
        snapshotValue.maximumEntries = maximumEntries;
    }

    void purgeExpired(std::int64_t timestamp)
    {
        const std::string completed = COMPLETED;
        (*session)
            << "DELETE FROM invocation_journal WHERE state=? AND expires_us<=?",
            useRef(completed), useRef(timestamp), now;
    }

    void refreshCounts()
    {
        Poco::Int64 entries = 0;
        Poco::Int64 inFlight = 0;
        Poco::Int64 completed = 0;
        const std::string activeState = IN_FLIGHT;
        const std::string completedState = COMPLETED;
        (*session) << "SELECT COUNT(*) FROM invocation_journal",
            into(entries), now;
        (*session) << "SELECT COUNT(*) FROM invocation_journal WHERE state=?",
            useRef(activeState), into(inFlight), now;
        (*session) << "SELECT COUNT(*) FROM invocation_journal WHERE state=?",
            useRef(completedState), into(completed), now;
        snapshotValue.entries = static_cast<std::size_t>(entries);
        snapshotValue.inFlight = static_cast<std::size_t>(inFlight);
        snapshotValue.completed = static_cast<std::size_t>(completed);
    }

    void markSuccess()
    {
        snapshotValue.healthy = true;
        snapshotValue.lastError.clear();
    }

    void markError(const std::string& detail)
    {
        snapshotValue.healthy = false;
        snapshotValue.lastError = detail;
        ++snapshotValue.errors;
    }

    std::string path;
    std::size_t maximumEntries;
    std::int64_t retentionMicroseconds;
    mutable std::mutex mutex;
    std::unique_ptr<Poco::Data::Session> session;
    InvocationJournalSnapshot snapshotValue;
};

SqliteInvocationJournal::SqliteInvocationJournal(
    std::string databasePath, std::size_t maximumEntries,
    std::chrono::milliseconds retention)
    : _impl(std::make_unique<Impl>(std::move(databasePath), maximumEntries,
                                  retention))
{
    _impl->initialize();
}

SqliteInvocationJournal::~SqliteInvocationJournal() = default;

InvocationJournalClaim SqliteInvocationJournal::claim(
    const InvocationJournalClaimRequest& request)
{
    std::lock_guard<std::mutex> lock(_impl->mutex);
    ++_impl->snapshotValue.claims;
    try
    {
        if (request.scopeDigest.size() != 64 ||
            request.requestDigest.size() != 64 ||
            request.invocationId.empty())
            throw Poco::InvalidArgumentException(
                "Invocation journal claim identity is invalid");
        _impl->purgeExpired(request.nowUnixMicroseconds);
        std::vector<std::string> digests;
        std::vector<std::string> invocationIds;
        std::vector<std::string> states;
        std::vector<std::string> completions;
        (*_impl->session)
            << "SELECT request_digest,invocation_id,state,completion_json "
               "FROM invocation_journal WHERE scope_digest=?",
            useRef(request.scopeDigest), into(digests), into(invocationIds),
            into(states), into(completions), now;
        if (!digests.empty())
        {
            if (digests.front() != request.requestDigest)
            {
                ++_impl->snapshotValue.conflicts;
                _impl->refreshCounts();
                _impl->markSuccess();
                return {InvocationJournalClaimStatus::conflict,
                        invocationIds.front(), {},
                        "same key was used for a different request"};
            }
            if (states.front() == COMPLETED)
            {
                auto completion = std::make_shared<const InvocationCompletion>(
                    deserialize(completions.front()));
                ++_impl->snapshotValue.replays;
                _impl->refreshCounts();
                _impl->markSuccess();
                return {InvocationJournalClaimStatus::replayCompleted,
                        invocationIds.front(), std::move(completion), {}};
            }
            if (states.front() != IN_FLIGHT)
                throw Poco::DataFormatException(
                    "Invocation journal contains an invalid state");
            ++_impl->snapshotValue.indeterminate;
            _impl->refreshCounts();
            _impl->markSuccess();
            return {InvocationJournalClaimStatus::indeterminate,
                    invocationIds.front(), {},
                    "a prior invocation has no committed completion"};
        }

        _impl->refreshCounts();
        if (_impl->snapshotValue.entries >= _impl->maximumEntries)
        {
            const std::string completed = COMPLETED;
            (*_impl->session)
                << "DELETE FROM invocation_journal WHERE scope_digest IN ("
                   "SELECT scope_digest FROM invocation_journal WHERE state=? "
                   "ORDER BY updated_us,scope_digest LIMIT 1)",
                useRef(completed), now;
            _impl->refreshCounts();
        }
        if (_impl->snapshotValue.entries >= _impl->maximumEntries)
        {
            ++_impl->snapshotValue.capacityRejected;
            _impl->markSuccess();
            return {InvocationJournalClaimStatus::capacityExceeded, {}, {},
                    "all invocation journal entries are in-flight"};
        }

        const std::string state = IN_FLIGHT;
        const std::string completion;
        const auto expires = request.nowUnixMicroseconds +
            _impl->retentionMicroseconds;
        (*_impl->session)
            << "INSERT INTO invocation_journal("
               "scope_digest,request_digest,invocation_id,state,created_us,"
               "updated_us,expires_us,completion_json) VALUES(?,?,?,?,?,?,?,?)",
            useRef(request.scopeDigest), useRef(request.requestDigest),
            useRef(request.invocationId), useRef(state),
            useRef(request.nowUnixMicroseconds),
            useRef(request.nowUnixMicroseconds), useRef(expires),
            useRef(completion), now;
        _impl->refreshCounts();
        _impl->markSuccess();
        return {InvocationJournalClaimStatus::acquired,
                request.invocationId, {}, {}};
    }
    catch (const std::exception& exception)
    {
        _impl->markError(exception.what());
        throw;
    }
    catch (...)
    {
        _impl->markError("unknown invocation journal claim failure");
        throw;
    }
}

void SqliteInvocationJournal::complete(
    const std::string& scopeDigest, const std::string& requestDigest,
    const std::string& invocationId,
    const InvocationCompletion& completion,
    std::int64_t nowUnixMicroseconds)
{
    std::lock_guard<std::mutex> lock(_impl->mutex);
    try
    {
        const std::string inFlight = IN_FLIGHT;
        const std::string completed = COMPLETED;
        const auto payload = serialize(completion);
        const auto expires = nowUnixMicroseconds +
            _impl->retentionMicroseconds;
        (*_impl->session)
            << "UPDATE invocation_journal SET state=?,updated_us=?,expires_us=?,"
               "completion_json=? WHERE scope_digest=? AND request_digest=? "
               "AND invocation_id=? AND state=?",
            useRef(completed), useRef(nowUnixMicroseconds), useRef(expires),
            useRef(payload), useRef(scopeDigest), useRef(requestDigest),
            useRef(invocationId), useRef(inFlight), now;
        Poco::Int64 changed = 0;
        (*_impl->session) << "SELECT changes()", into(changed), now;
        if (changed != 1)
            throw Poco::IllegalStateException(
                "Invocation journal completion does not own an in-flight claim");
        _impl->refreshCounts();
        _impl->markSuccess();
    }
    catch (const std::exception& exception)
    {
        _impl->markError(exception.what());
        throw;
    }
    catch (...)
    {
        _impl->markError("unknown invocation journal completion failure");
        throw;
    }
}

bool SqliteInvocationJournal::release(
    const std::string& scopeDigest, const std::string& requestDigest,
    const std::string& invocationId)
{
    std::lock_guard<std::mutex> lock(_impl->mutex);
    try
    {
        const std::string inFlight = IN_FLIGHT;
        (*_impl->session)
            << "DELETE FROM invocation_journal WHERE scope_digest=? "
               "AND request_digest=? AND invocation_id=? AND state=?",
            useRef(scopeDigest), useRef(requestDigest), useRef(invocationId),
            useRef(inFlight), now;
        Poco::Int64 changed = 0;
        (*_impl->session) << "SELECT changes()", into(changed), now;
        _impl->refreshCounts();
        _impl->markSuccess();
        return changed == 1;
    }
    catch (const std::exception& exception)
    {
        _impl->markError(exception.what());
        throw;
    }
    catch (...)
    {
        _impl->markError("unknown invocation journal release failure");
        throw;
    }
}

InvocationJournalSnapshot SqliteInvocationJournal::snapshot() const
{
    std::lock_guard<std::mutex> lock(_impl->mutex);
    return _impl->snapshotValue;
}
} // namespace PocoDDS::ServiceClient
