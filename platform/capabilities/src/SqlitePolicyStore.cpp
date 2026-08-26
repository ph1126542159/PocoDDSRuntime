#include "PocoDDS/Capabilities/SqlitePolicyStore.h"

#include <Poco/Data/SQLite/Connector.h>
#include <Poco/Data/Session.h>
#include <Poco/Data/Statement.h>
#include <Poco/Data/Transaction.h>
#include <Poco/Exception.h>
#include <Poco/File.h>
#include <Poco/Path.h>
#include <Poco/Timestamp.h>
#include <Poco/UnicodeConverter.h>

#include <mutex>
#include <optional>
#include <utility>
#include <vector>

#if defined(_WIN32)
#include <Windows.h>
#else
#include <cerrno>
#include <fcntl.h>
#include <sys/file.h>
#include <unistd.h>
#endif

namespace PocoDDS::Capabilities
{
using namespace Poco::Data::Keywords;

namespace
{
Poco::Int64 nowMicroseconds() { return Poco::Timestamp().epochMicroseconds(); }

Poco::UInt64 positiveGeneration(Poco::Int64 value)
{
    if (value <= 0)
        throw Poco::DataFormatException("Capability policy generation must be positive");
    return static_cast<Poco::UInt64>(value);
}

class ExclusiveStoreLease
{
public:
    explicit ExclusiveStoreLease(const std::string& databasePath)
        : _path(databasePath + ".lock")
    {
        Poco::Path path(_path);
        if (path.depth() > 0) Poco::File(path.makeParent()).createDirectories();
#if defined(_WIN32)
        std::wstring wide;
        Poco::UnicodeConverter::toUTF16(_path, wide);
        _handle = CreateFileW(wide.c_str(), GENERIC_READ | GENERIC_WRITE, 0, nullptr,
                              OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
        if (_handle == INVALID_HANDLE_VALUE)
            throw Poco::FileException(
                "Capability policy database is already owned by another process", _path);
#else
        _descriptor = ::open(_path.c_str(), O_CREAT | O_RDWR, 0600);
        if (_descriptor < 0 || ::flock(_descriptor, LOCK_EX | LOCK_NB) != 0)
        {
            if (_descriptor >= 0) ::close(_descriptor);
            _descriptor = -1;
            throw Poco::FileException(
                "Capability policy database is already owned by another process", _path);
        }
#endif
    }

    ~ExclusiveStoreLease()
    {
#if defined(_WIN32)
        if (_handle != INVALID_HANDLE_VALUE) CloseHandle(_handle);
#else
        if (_descriptor >= 0)
        {
            ::flock(_descriptor, LOCK_UN);
            ::close(_descriptor);
        }
#endif
    }

    ExclusiveStoreLease(const ExclusiveStoreLease&) = delete;
    ExclusiveStoreLease& operator=(const ExclusiveStoreLease&) = delete;

private:
    std::string _path;
#if defined(_WIN32)
    HANDLE _handle{INVALID_HANDLE_VALUE};
#else
    int _descriptor{-1};
#endif
};
} // namespace

class SqlitePolicyStore::Impl
{
public:
    Impl(std::string value, std::size_t maximum)
        : path(std::move(value)), maximumAuditRecords(maximum), lease(path) {}

    PersistedPolicy currentUnlocked() const
    {
        if (!session)
            throw Poco::IllegalStateException("Capability policy store is not initialized");
        std::vector<Poco::Int64> generations;
        std::vector<std::string> digests;
        std::vector<std::string> documents;
        std::vector<Poco::Int64> updated;
        (*session)
            << "SELECT generation,digest,policy_document,updated_us "
               "FROM capability_policy_state WHERE singleton=1",
            into(generations), into(digests), into(documents), into(updated), now;
        if (generations.size() != 1 || digests.size() != 1 || documents.size() != 1 ||
            updated.size() != 1)
            throw Poco::DataFormatException("Capability policy state is missing or duplicated");
        auto rules = parsePolicyDocument(documents.front());
        const auto calculated = policyDigest(rules);
        if (calculated != digests.front())
            throw Poco::DataFormatException("Capability policy state digest mismatch");
        PersistedPolicy result;
        result.snapshot = {positiveGeneration(generations.front()), calculated, rules.size(),
                           Effect::deny};
        result.rules = std::move(rules);
        result.updatedMicroseconds = updated.front();
        return result;
    }

    void markFailure(const std::string& message) const noexcept
    {
        healthy = false;
        recoveryRequired = true;
        error = message;
    }

    void ensureOperational() const
    {
        if (!session)
            throw Poco::IllegalStateException("Capability policy store is not initialized");
        if (recoveryRequired)
            throw Poco::IllegalStateException(
                "Capability policy store requires integrity verification before reuse", error);
    }

    std::string path;
    std::size_t maximumAuditRecords;
    ExclusiveStoreLease lease;
    mutable std::mutex mutex;
    mutable std::unique_ptr<Poco::Data::Session> session;
    mutable bool healthy{false};
    mutable bool recoveryRequired{false};
    mutable std::string error;
};

SqlitePolicyStore::SqlitePolicyStore(std::string databasePath,
                                     std::size_t maximumAuditRecords)
    : _impl(std::make_unique<Impl>(std::move(databasePath), maximumAuditRecords))
{
    if (_impl->path.empty())
        throw Poco::InvalidArgumentException("Capability policy database path is empty");
    if (maximumAuditRecords == 0 || maximumAuditRecords > 1000000)
        throw Poco::InvalidArgumentException(
            "Capability audit retention must contain 1..1000000 records");
}

SqlitePolicyStore::~SqlitePolicyStore() = default;

PersistedPolicy SqlitePolicyStore::initialize(const std::vector<Rule>& seedRules)
{
    const auto seedDocument = policyDocument(seedRules);
    const auto seedDigest = policyDigest(seedRules);
    std::lock_guard<std::mutex> lock(_impl->mutex);
    try
    {
        Poco::Path path(_impl->path);
        if (path.depth() > 0) Poco::File(path.makeParent()).createDirectories();
        Poco::Data::SQLite::Connector::registerConnector();
        _impl->session = std::make_unique<Poco::Data::Session>("SQLite", _impl->path);
        (*_impl->session) << "PRAGMA journal_mode=WAL", now;
        (*_impl->session) << "PRAGMA synchronous=FULL", now;
        (*_impl->session) << "PRAGMA busy_timeout=5000", now;
        (*_impl->session)
            << "CREATE TABLE IF NOT EXISTS capability_metadata ("
               "key TEXT PRIMARY KEY,value TEXT NOT NULL)", now;
        (*_impl->session)
            << "INSERT OR IGNORE INTO capability_metadata(key,value) "
               "VALUES('schema_version','1')", now;
        std::vector<std::string> versions;
        (*_impl->session)
            << "SELECT value FROM capability_metadata WHERE key='schema_version'",
            into(versions), now;
        if (versions.size() != 1 || versions.front() != "1")
            throw Poco::DataFormatException("Unsupported capability database schema version");
        (*_impl->session)
            << "CREATE TABLE IF NOT EXISTS capability_policy_state ("
               "singleton INTEGER PRIMARY KEY CHECK(singleton=1),"
               "generation INTEGER NOT NULL CHECK(generation>0),"
               "digest TEXT NOT NULL,policy_document TEXT NOT NULL,updated_us INTEGER NOT NULL)",
            now;
        (*_impl->session)
            << "CREATE TABLE IF NOT EXISTS capability_policy_requests ("
               "request_id TEXT PRIMARY KEY,actor TEXT NOT NULL,expected_generation INTEGER NOT NULL,"
               "input_digest TEXT NOT NULL,result_generation INTEGER NOT NULL,"
               "result_digest TEXT NOT NULL,result_rule_count INTEGER NOT NULL,created_us INTEGER NOT NULL)",
            now;
        (*_impl->session)
            << "CREATE TABLE IF NOT EXISTS capability_audit ("
               "id INTEGER PRIMARY KEY AUTOINCREMENT,timestamp_us INTEGER NOT NULL,"
               "principal TEXT NOT NULL,resource_kind TEXT NOT NULL,resource TEXT NOT NULL,"
               "action TEXT NOT NULL,allowed INTEGER NOT NULL,code TEXT NOT NULL,"
               "matched_rule_id TEXT NOT NULL,policy_generation INTEGER NOT NULL,"
               "policy_digest TEXT NOT NULL,explanation TEXT NOT NULL)", now;
        (*_impl->session)
            << "CREATE INDEX IF NOT EXISTS idx_capability_audit_time "
               "ON capability_audit(timestamp_us,id)", now;
        std::vector<std::string> integrity;
        (*_impl->session) << "PRAGMA integrity_check", into(integrity), now;
        if (integrity.size() != 1 || integrity.front() != "ok")
            throw Poco::DataFormatException("Capability database integrity check failed");
        const Poco::Int64 generation = 1;
        const Poco::Int64 updated = nowMicroseconds();
        (*_impl->session)
            << "INSERT OR IGNORE INTO capability_policy_state("
               "singleton,generation,digest,policy_document,updated_us) VALUES(1,?,?,?,?)",
            useRef(generation), useRef(seedDigest), useRef(seedDocument), useRef(updated), now;
        auto result = _impl->currentUnlocked();
        _impl->healthy = true;
        _impl->recoveryRequired = false;
        _impl->error.clear();
        return result;
    }
    catch (const Poco::Exception& exception)
    {
        _impl->markFailure(exception.displayText());
        throw;
    }
    catch (const std::exception& exception)
    {
        _impl->markFailure(exception.what());
        throw;
    }
}

PersistedPolicy SqlitePolicyStore::current() const
{
    std::lock_guard<std::mutex> lock(_impl->mutex);
    try
    {
        _impl->ensureOperational();
        return _impl->currentUnlocked();
    }
    catch (const Poco::Exception& exception)
    {
        _impl->markFailure(exception.displayText());
        throw;
    }
}

ReplaceResult SqlitePolicyStore::replace(const ReplaceRequest& request)
{
    if (request.requestId.empty() || request.requestId.size() > 128)
        throw Poco::InvalidArgumentException("Capability requestId must contain 1..128 characters");
    if (request.actor.empty())
        throw Poco::InvalidArgumentException("Capability policy actor cannot be empty");
    const auto inputDigest = policyDigest(request.rules);
    const auto document = policyDocument(request.rules);
    std::lock_guard<std::mutex> lock(_impl->mutex);
    try
    {
        _impl->ensureOperational();
        std::vector<std::string> actors;
        std::vector<Poco::Int64> expected;
        std::vector<std::string> inputs;
        std::vector<Poco::Int64> generations;
        std::vector<std::string> digests;
        std::vector<Poco::Int64> ruleCounts;
        (*_impl->session)
            << "SELECT actor,expected_generation,input_digest,result_generation,"
               "result_digest,result_rule_count FROM capability_policy_requests WHERE request_id=?",
            useRef(request.requestId), into(actors), into(expected), into(inputs),
            into(generations), into(digests), into(ruleCounts), now;
        if (!actors.empty())
        {
            if (actors.front() != request.actor ||
                positiveGeneration(expected.front()) != request.expectedGeneration ||
                inputs.front() != inputDigest)
                throw Poco::InvalidArgumentException(
                    "Capability requestId was already used with different input", request.requestId);
            return {{positiveGeneration(generations.front()), digests.front(),
                     static_cast<std::size_t>(ruleCounts.front()), Effect::deny}, true};
        }

        const auto current = _impl->currentUnlocked();
        if (request.expectedGeneration != current.snapshot.generation)
            throw Poco::InvalidArgumentException(
                "Capability generation conflict: expected " +
                std::to_string(request.expectedGeneration) + ", current " +
                std::to_string(current.snapshot.generation));
        const Poco::Int64 nextGeneration =
            static_cast<Poco::Int64>(current.snapshot.generation + 1);
        const Poco::Int64 expectedGeneration =
            static_cast<Poco::Int64>(request.expectedGeneration);
        const Poco::Int64 ruleCount = static_cast<Poco::Int64>(request.rules.size());
        const Poco::Int64 created = nowMicroseconds();
        Poco::Data::Transaction transaction(*_impl->session);
        (*_impl->session)
            << "UPDATE capability_policy_state SET generation=?,digest=?,"
               "policy_document=?,updated_us=? WHERE singleton=1",
            useRef(nextGeneration), useRef(inputDigest), useRef(document), useRef(created), now;
        (*_impl->session)
            << "INSERT INTO capability_policy_requests("
               "request_id,actor,expected_generation,input_digest,result_generation,"
               "result_digest,result_rule_count,created_us) VALUES(?,?,?,?,?,?,?,?)",
            useRef(request.requestId), useRef(request.actor), useRef(expectedGeneration),
            useRef(inputDigest), useRef(nextGeneration), useRef(inputDigest),
            useRef(ruleCount), useRef(created), now;
        transaction.commit();
        _impl->healthy = true;
        _impl->error.clear();
        return {{positiveGeneration(nextGeneration), inputDigest, request.rules.size(), Effect::deny},
                false};
    }
    catch (const Poco::InvalidArgumentException&)
    {
        throw;
    }
    catch (const Poco::Exception& exception)
    {
        _impl->markFailure(exception.displayText());
        throw;
    }
}

void SqlitePolicyStore::appendAudit(const AuditRecord& record)
{
    std::lock_guard<std::mutex> lock(_impl->mutex);
    try
    {
        _impl->ensureOperational();
        const std::string kind = resourceKindName(record.request.resourceKind);
        const std::string action = actionName(record.request.action);
        const int allowed = record.decision.allowed ? 1 : 0;
        const Poco::Int64 generation =
            static_cast<Poco::Int64>(record.decision.policyGeneration);
        (*_impl->session)
            << "INSERT INTO capability_audit("
               "timestamp_us,principal,resource_kind,resource,action,allowed,code,"
               "matched_rule_id,policy_generation,policy_digest,explanation) "
               "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            useRef(record.timestampMicroseconds), useRef(record.request.principal), useRef(kind),
            useRef(record.request.resource), useRef(action), useRef(allowed),
            useRef(record.decision.code), useRef(record.decision.matchedRuleId),
            useRef(generation), useRef(record.decision.policyDigest),
            useRef(record.decision.explanation), now;
        const Poco::Int64 maximum = static_cast<Poco::Int64>(_impl->maximumAuditRecords);
        (*_impl->session)
            << "DELETE FROM capability_audit WHERE id NOT IN ("
               "SELECT id FROM capability_audit ORDER BY id DESC LIMIT ?)",
            useRef(maximum), now;
        _impl->healthy = true;
        _impl->error.clear();
    }
    catch (const Poco::Exception& exception)
    {
        _impl->markFailure(exception.displayText());
        throw;
    }
}

std::vector<AuditRecord> SqlitePolicyStore::audit(std::size_t limit) const
{
    if (limit == 0 || limit > 1000)
        throw Poco::InvalidArgumentException("Capability audit limit must be 1..1000");
    std::lock_guard<std::mutex> lock(_impl->mutex);
    try
    {
        _impl->ensureOperational();
        std::vector<Poco::Int64> timestamps;
        std::vector<std::string> principals;
        std::vector<std::string> kinds;
        std::vector<std::string> resources;
        std::vector<std::string> actions;
        std::vector<int> allowed;
        std::vector<std::string> codes;
        std::vector<std::string> matched;
        std::vector<Poco::Int64> generations;
        std::vector<std::string> digests;
        std::vector<std::string> explanations;
        const Poco::Int64 bounded = static_cast<Poco::Int64>(limit);
        (*_impl->session)
            << "SELECT timestamp_us,principal,resource_kind,resource,action,allowed,code,"
               "matched_rule_id,policy_generation,policy_digest,explanation "
               "FROM capability_audit ORDER BY id DESC LIMIT ?",
            useRef(bounded), into(timestamps), into(principals), into(kinds), into(resources),
            into(actions), into(allowed), into(codes), into(matched), into(generations),
            into(digests), into(explanations), now;
        std::vector<AuditRecord> result;
        result.reserve(timestamps.size());
        for (std::size_t index = 0; index < timestamps.size(); ++index)
        {
            AuditRecord record;
            record.timestampMicroseconds = timestamps[index];
            record.request = {principals[index], parseResourceKind(kinds[index]), resources[index],
                              parseAction(actions[index])};
            record.decision.allowed = allowed[index] != 0;
            record.decision.code = codes[index];
            record.decision.matchedRuleId = matched[index];
            record.decision.policyGeneration = positiveGeneration(generations[index]);
            record.decision.policyDigest = digests[index];
            record.decision.explanation = explanations[index];
            result.push_back(std::move(record));
        }
        return result;
    }
    catch (const Poco::Exception& exception)
    {
        _impl->markFailure(exception.displayText());
        throw;
    }
}

PersistenceSnapshot SqlitePolicyStore::snapshot() const noexcept
{
    std::lock_guard<std::mutex> lock(_impl->mutex);
    PersistenceSnapshot result;
    result.databasePath = _impl->path;
    result.healthy = _impl->healthy;
    result.recoveryRequired = _impl->recoveryRequired;
    result.error = _impl->error;
    if (!_impl->session) return result;
    try
    {
        const auto policy = _impl->currentUnlocked();
        result.generation = policy.snapshot.generation;
        result.digest = policy.snapshot.digest;
        std::vector<Poco::Int64> auditCounts;
        std::vector<Poco::Int64> requestCounts;
        (*_impl->session) << "SELECT COUNT(*) FROM capability_audit", into(auditCounts), now;
        (*_impl->session) << "SELECT COUNT(*) FROM capability_policy_requests",
            into(requestCounts), now;
        if (auditCounts.size() == 1)
            result.auditRecords = static_cast<Poco::UInt64>(auditCounts.front());
        if (requestCounts.size() == 1)
            result.requestRecords = static_cast<Poco::UInt64>(requestCounts.front());
    }
    catch (const std::exception& exception)
    {
        result.healthy = false;
        result.recoveryRequired = true;
        result.error = exception.what();
    }
    return result;
}

bool SqlitePolicyStore::operational() const noexcept
{
    std::lock_guard<std::mutex> lock(_impl->mutex);
    return _impl->session && _impl->healthy && !_impl->recoveryRequired;
}

void SqlitePolicyStore::verifyIntegrity() const
{
    std::lock_guard<std::mutex> lock(_impl->mutex);
    try
    {
        std::vector<std::string> integrity;
        (*_impl->session) << "PRAGMA integrity_check", into(integrity), now;
        if (integrity.size() != 1 || integrity.front() != "ok")
            throw Poco::DataFormatException("Capability database integrity check failed");
        static_cast<void>(_impl->currentUnlocked());
        _impl->healthy = true;
        _impl->recoveryRequired = false;
        _impl->error.clear();
    }
    catch (const Poco::Exception& exception)
    {
        _impl->markFailure(exception.displayText());
        throw;
    }
}
} // namespace PocoDDS::Capabilities
