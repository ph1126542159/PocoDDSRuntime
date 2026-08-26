#include "PocoDDS/Lifecycle/SqliteMaintenanceStore.h"

#include <Poco/Data/SQLite/Connector.h>
#include <Poco/Data/Session.h>
#include <Poco/Data/Statement.h>
#include <Poco/Data/Transaction.h>
#include <Poco/Exception.h>
#include <Poco/File.h>
#include <Poco/JSON/Array.h>
#include <Poco/JSON/Object.h>
#include <Poco/JSON/Parser.h>
#include <Poco/Path.h>
#include <Poco/String.h>
#include <Poco/UnicodeConverter.h>

#include <algorithm>
#include <limits>
#include <set>
#include <sstream>
#include <utility>

#if defined(_WIN32)
#include <Windows.h>
#else
#include <fcntl.h>
#include <sys/file.h>
#include <unistd.h>
#endif

namespace PocoDDS::Lifecycle
{
using namespace Poco::Data::Keywords;

namespace
{
void validatePlan(const MaintenancePlan& plan)
{
    if (plan.id.empty() || plan.id.size() > 128 ||
        plan.target.empty() || plan.target.size() > 128 ||
        plan.code.size() > 128 || plan.detail.size() > 8192 ||
        plan.createdMicroseconds <= 0 ||
        plan.updatedMicroseconds < plan.createdMicroseconds ||
        plan.consumers.size() > 1024 || plan.steps.size() > 4096)
        throw Poco::DataFormatException(
            "Lifecycle maintenance plan is outside safe bounds");
    std::set<std::string> consumers;
    for (const auto& consumer : plan.consumers)
    {
        if (consumer.empty() || consumer.size() > 128 ||
            !consumers.insert(consumer).second)
            throw Poco::DataFormatException(
                "Lifecycle maintenance Consumer list is invalid");
    }
    for (const auto& step : plan.steps)
    {
        if (step.phase.empty() || step.phase.size() > 128 ||
            step.target.empty() || step.target.size() > 128 ||
            step.detail.size() > 8192)
            throw Poco::DataFormatException(
                "Lifecycle maintenance step is outside safe bounds");
    }
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
        _handle = CreateFileW(wide.c_str(), GENERIC_READ | GENERIC_WRITE, 0,
                              nullptr, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL,
                              nullptr);
        if (_handle == INVALID_HANDLE_VALUE)
            throw Poco::FileException(
                "Lifecycle maintenance database is already owned by another process",
                _path);
#else
        _descriptor = ::open(_path.c_str(), O_CREAT | O_RDWR, 0600);
        if (_descriptor < 0 || ::flock(_descriptor, LOCK_EX | LOCK_NB) != 0)
        {
            if (_descriptor >= 0) ::close(_descriptor);
            _descriptor = -1;
            throw Poco::FileException(
                "Lifecycle maintenance database is already owned by another process",
                _path);
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

Poco::JSON::Array::Ptr strings(const std::vector<std::string>& values)
{
    Poco::JSON::Array::Ptr result = new Poco::JSON::Array;
    for (const auto& value : values) result->add(value);
    return result;
}

std::vector<std::string> parseStrings(const Poco::JSON::Array::Ptr& values)
{
    if (!values || values->size() > 1024)
        throw Poco::DataFormatException("Invalid maintenance Consumer list");
    std::vector<std::string> result;
    result.reserve(values->size());
    for (std::size_t index = 0; index < values->size(); ++index)
        result.push_back(values->getElement<std::string>(
            static_cast<unsigned int>(index)));
    return result;
}

Poco::JSON::Object::Ptr planObject(const MaintenancePlan& plan)
{
    Poco::JSON::Object::Ptr result = new Poco::JSON::Object;
    result->set("id", plan.id);
    result->set("target", plan.target);
    result->set("status", toString(plan.status));
    result->set("consumers", strings(plan.consumers));
    Poco::JSON::Array::Ptr steps = new Poco::JSON::Array;
    for (const auto& step : plan.steps)
    {
        Poco::JSON::Object::Ptr item = new Poco::JSON::Object;
        item->set("phase", step.phase);
        item->set("target", step.target);
        item->set("succeeded", step.succeeded);
        item->set("detail", step.detail);
        steps->add(item);
    }
    result->set("steps", steps);
    result->set("rollbackComplete", plan.rollbackComplete);
    result->set("code", plan.code);
    result->set("detail", plan.detail);
    result->set("createdMicroseconds", plan.createdMicroseconds);
    result->set("updatedMicroseconds", plan.updatedMicroseconds);
    result->set("recoveryAttempts", plan.recoveryAttempts);
    return result;
}

MaintenancePlan parsePlan(const Poco::JSON::Object::Ptr& object)
{
    if (!object) throw Poco::DataFormatException("Maintenance plan is missing");
    MaintenancePlan result;
    result.id = object->getValue<std::string>("id");
    result.target = object->getValue<std::string>("target");
    result.status = maintenanceStatusFromString(
        object->getValue<std::string>("status"));
    result.consumers = parseStrings(object->getArray("consumers"));
    const auto steps = object->getArray("steps");
    if (!steps || steps->size() > 4096)
        throw Poco::DataFormatException("Invalid maintenance step list");
    result.steps.reserve(steps->size());
    for (std::size_t index = 0; index < steps->size(); ++index)
    {
        const auto item = steps->getObject(static_cast<unsigned int>(index));
        if (!item) throw Poco::DataFormatException("Invalid maintenance step");
        result.steps.push_back({
            item->getValue<std::string>("phase"),
            item->getValue<std::string>("target"),
            item->getValue<bool>("succeeded"),
            item->getValue<std::string>("detail")});
    }
    result.rollbackComplete = object->getValue<bool>("rollbackComplete");
    result.code = object->getValue<std::string>("code");
    result.detail = object->getValue<std::string>("detail");
    result.createdMicroseconds =
        object->getValue<Poco::Int64>("createdMicroseconds");
    result.updatedMicroseconds =
        object->getValue<Poco::Int64>("updatedMicroseconds");
    result.recoveryAttempts =
        object->getValue<unsigned int>("recoveryAttempts");
    if (result.id.empty() || result.target.empty() ||
        result.createdMicroseconds <= 0 ||
        result.updatedMicroseconds < result.createdMicroseconds)
        throw Poco::DataFormatException("Invalid maintenance plan identity or time");
    validatePlan(result);
    return result;
}

std::string serializePlan(const MaintenancePlan& plan)
{
    validatePlan(plan);
    Poco::JSON::Object root;
    root.set("schemaVersion", 1);
    root.set("plan", planObject(plan));
    std::ostringstream stream;
    root.stringify(stream);
    return stream.str();
}

MaintenancePlan deserializePlan(const std::string& payload)
{
    const auto root = Poco::JSON::Parser().parse(payload)
                          .extract<Poco::JSON::Object::Ptr>();
    if (!root || root->getValue<int>("schemaVersion") != 1)
        throw Poco::DataFormatException("Unsupported maintenance plan schema");
    return parsePlan(root->getObject("plan"));
}

std::string serializeOperation(const MaintenanceOperation& operation)
{
    validatePlan(operation.plan);
    Poco::JSON::Object root;
    root.set("schemaVersion", 1);
    root.set("succeeded", operation.succeeded);
    root.set("plan", planObject(operation.plan));
    std::ostringstream stream;
    root.stringify(stream);
    return stream.str();
}

MaintenanceOperation deserializeOperation(const std::string& payload)
{
    const auto root = Poco::JSON::Parser().parse(payload)
                          .extract<Poco::JSON::Object::Ptr>();
    if (!root || root->getValue<int>("schemaVersion") != 1)
        throw Poco::DataFormatException(
            "Unsupported maintenance operation schema");
    return {root->getValue<bool>("succeeded"), false,
            parsePlan(root->getObject("plan"))};
}

bool openStatus(MaintenanceStatus status) noexcept
{
    return status == MaintenanceStatus::draining ||
           status == MaintenanceStatus::restoring ||
           status == MaintenanceStatus::drained ||
           status == MaintenanceStatus::restoreRolledBack ||
           recoveryPending(status);
}

std::uint64_t parseSequence(const std::string& value)
{
    try
    {
        std::size_t consumed = 0;
        const auto result = std::stoull(value, &consumed);
        if (consumed != value.size())
            throw Poco::DataFormatException(
                "Lifecycle plan sequence contains trailing data");
        return result;
    }
    catch (const Poco::Exception&)
    {
        throw;
    }
    catch (const std::exception&)
    {
        throw Poco::DataFormatException("Lifecycle plan sequence is invalid");
    }
}

MaintenanceStoreSnapshot verifySession(Poco::Data::Session& session,
                                        const std::string& databasePath)
{
    std::vector<std::string> integrity;
    session << "PRAGMA integrity_check", into(integrity), now;
    if (integrity.size() != 1 || integrity.front() != "ok")
        throw Poco::DataFormatException(
            "Lifecycle maintenance database integrity check failed");

    std::vector<std::string> versions;
    std::vector<std::string> sequences;
    session << "SELECT value FROM lifecycle_metadata WHERE key='schema_version'",
        into(versions), now;
    session << "SELECT value FROM lifecycle_metadata WHERE key='next_plan_id'",
        into(sequences), now;
    if (versions.size() != 1 || versions.front() != "1")
        throw Poco::DataFormatException(
            "Unsupported lifecycle maintenance database schema");
    if (sequences.size() != 1)
        throw Poco::DataFormatException("Lifecycle plan sequence is missing");

    Poco::Int64 planCount = -1;
    Poco::Int64 requestCount = -1;
    session << "SELECT COUNT(*) FROM lifecycle_plans", into(planCount), now;
    session << "SELECT COUNT(*) FROM lifecycle_requests", into(requestCount), now;
    if (planCount < 0 || planCount > 100000 ||
        requestCount < 0 || requestCount > 200000)
        throw Poco::DataFormatException(
            "Lifecycle maintenance database exceeds safe verification bounds");

    std::vector<std::string> ids;
    std::vector<std::string> statuses;
    std::vector<Poco::Int64> created;
    std::vector<Poco::Int64> updated;
    std::vector<std::string> planPayloads;
    session << "SELECT id,status,created_us,updated_us,payload "
               "FROM lifecycle_plans ORDER BY id",
        into(ids), into(statuses), into(created), into(updated),
        into(planPayloads), now;
    const auto expectedPlans = static_cast<std::size_t>(planCount);
    const auto sequence = parseSequence(sequences.front());
    if (ids.size() != expectedPlans || statuses.size() != expectedPlans ||
        created.size() != expectedPlans || updated.size() != expectedPlans ||
        planPayloads.size() != expectedPlans)
        throw Poco::DataFormatException(
            "Lifecycle maintenance plan columns are inconsistent");

    std::size_t openPlans = 0;
    for (std::size_t index = 0; index < expectedPlans; ++index)
    {
        const auto plan = deserializePlan(planPayloads[index]);
        if (plan.id != ids[index] || toString(plan.status) != statuses[index] ||
            plan.createdMicroseconds != created[index] ||
            plan.updatedMicroseconds != updated[index])
            throw Poco::DataFormatException(
                "Lifecycle maintenance plan index does not match its payload");
        constexpr const char* prefix = "maintenance-";
        if (plan.id.rfind(prefix, 0) == 0 && plan.id.size() > 12 &&
            std::all_of(plan.id.begin() + 12, plan.id.end(),
                        [](unsigned char value) { return value >= '0' && value <= '9'; }) &&
            parseSequence(plan.id.substr(12)) > sequence)
            throw Poco::DataFormatException(
                "Lifecycle plan sequence trails a persisted numeric plan ID");
        if (openStatus(plan.status)) ++openPlans;
    }

    std::vector<std::string> requestIds;
    std::vector<std::string> fingerprints;
    std::vector<Poco::Int64> requestUpdated;
    std::vector<std::string> requestPayloads;
    session << "SELECT request_id,fingerprint,updated_us,payload "
               "FROM lifecycle_requests ORDER BY request_id",
        into(requestIds), into(fingerprints), into(requestUpdated),
        into(requestPayloads), now;
    const auto expectedRequests = static_cast<std::size_t>(requestCount);
    if (requestIds.size() != expectedRequests ||
        fingerprints.size() != expectedRequests ||
        requestUpdated.size() != expectedRequests ||
        requestPayloads.size() != expectedRequests)
        throw Poco::DataFormatException(
            "Lifecycle maintenance request columns are inconsistent");
    for (std::size_t index = 0; index < expectedRequests; ++index)
    {
        const auto operation = deserializeOperation(requestPayloads[index]);
        if (requestIds[index].empty() || fingerprints[index].empty() ||
            requestIds[index].size() > 128 || fingerprints[index].size() > 512 ||
            requestUpdated[index] <= 0 || operation.plan.id.empty() ||
            operation.plan.updatedMicroseconds != requestUpdated[index])
            throw Poco::DataFormatException(
                "Invalid lifecycle maintenance request record");
    }

    return {true, databasePath, 1, sequence,
            expectedPlans, expectedRequests, openPlans};
}

std::string absolutePath(const std::string& value)
{
    Poco::Path path(value);
    path.makeAbsolute();
    return path.toString();
}

bool samePath(const std::string& left, const std::string& right)
{
#if defined(_WIN32)
    return Poco::icompare(absolutePath(left), absolutePath(right)) == 0;
#else
    return absolutePath(left) == absolutePath(right);
#endif
}

std::string sqlString(const std::string& value)
{
    std::string result;
    result.reserve(value.size() + 2);
    result.push_back('\'');
    for (const auto character : value)
    {
        result.push_back(character);
        if (character == '\'') result.push_back('\'');
    }
    result.push_back('\'');
    return result;
}
} // namespace

class SqliteMaintenanceStore::Impl
{
public:
    Impl(std::string value, std::size_t plans, std::size_t requests)
        : path(std::move(value)), maximumPlans(plans), maximumRequests(requests)
    {
    }

    void savePlan(const MaintenancePlan& plan)
    {
        const std::string status = toString(plan.status);
        const std::string payload = serializePlan(plan);
        (*session)
            << "INSERT INTO lifecycle_plans(id,status,created_us,updated_us,payload) "
               "VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
               "status=excluded.status,updated_us=excluded.updated_us,"
               "payload=excluded.payload",
            useRef(plan.id), useRef(status), useRef(plan.createdMicroseconds),
            useRef(plan.updatedMicroseconds), useRef(payload), now;
    }

    void prune()
    {
        const auto plans = static_cast<Poco::Int64>(maximumPlans);
        const auto requests = static_cast<Poco::Int64>(maximumRequests);
        (*session)
            << "DELETE FROM lifecycle_plans WHERE id IN ("
               "SELECT id FROM lifecycle_plans WHERE status NOT IN "
               "('draining','restoring','drained','drainRecoveryPending',"
               "'restoreRecoveryPending','restoreRolledBack') "
               "ORDER BY updated_us DESC,id DESC "
               "LIMIT -1 OFFSET ?)",
            useRef(plans), now;
        (*session)
            << "DELETE FROM lifecycle_requests WHERE request_id IN ("
               "SELECT request_id FROM lifecycle_requests "
               "ORDER BY updated_us DESC,request_id DESC LIMIT -1 OFFSET ?)",
            useRef(requests), now;
    }

    std::string path;
    std::size_t maximumPlans;
    std::size_t maximumRequests;
    std::unique_ptr<ExclusiveStoreLease> lease;
    mutable std::unique_ptr<Poco::Data::Session> session;
    bool readOnly{false};
};

SqliteMaintenanceStore::SqliteMaintenanceStore(
    std::string path, std::size_t maximumPlans, std::size_t maximumRequests)
    : _impl(std::make_unique<Impl>(
          std::move(path), maximumPlans, maximumRequests))
{
    if (_impl->path.empty())
        throw Poco::InvalidArgumentException(
            "Lifecycle maintenance database path is empty");
    if (maximumPlans == 0 || maximumPlans > 100000 ||
        maximumRequests == 0 || maximumRequests > 200000)
        throw Poco::InvalidArgumentException(
            "Lifecycle maintenance retention is outside safe bounds");
}

SqliteMaintenanceStore::~SqliteMaintenanceStore() = default;

void SqliteMaintenanceStore::initialize()
{
    if (_impl->session || _impl->lease)
        throw Poco::IllegalStateException(
            "Lifecycle maintenance store is already initialized");
    _impl->lease = std::make_unique<ExclusiveStoreLease>(_impl->path);
    Poco::Path path(_impl->path);
    if (path.depth() > 0) Poco::File(path.makeParent()).createDirectories();
    Poco::Data::SQLite::Connector::registerConnector();
    _impl->session = std::make_unique<Poco::Data::Session>("SQLite", _impl->path);
    (*_impl->session) << "PRAGMA journal_mode=WAL", now;
    (*_impl->session) << "PRAGMA synchronous=FULL", now;
    std::vector<std::string> integrity;
    (*_impl->session) << "PRAGMA quick_check", into(integrity), now;
    if (integrity.size() != 1 || integrity.front() != "ok")
        throw Poco::DataFormatException(
            "Lifecycle maintenance database integrity check failed");
    (*_impl->session)
        << "CREATE TABLE IF NOT EXISTS lifecycle_metadata ("
           "key TEXT PRIMARY KEY,value TEXT NOT NULL)", now;
    (*_impl->session)
        << "INSERT OR IGNORE INTO lifecycle_metadata(key,value) "
           "VALUES('schema_version','1')", now;
    (*_impl->session)
        << "INSERT OR IGNORE INTO lifecycle_metadata(key,value) "
           "VALUES('next_plan_id','0')", now;
    std::vector<std::string> versions;
    (*_impl->session)
        << "SELECT value FROM lifecycle_metadata WHERE key='schema_version'",
        into(versions), now;
    if (versions.size() != 1 || versions.front() != "1")
        throw Poco::DataFormatException(
            "Unsupported lifecycle maintenance database schema");
    (*_impl->session)
        << "CREATE TABLE IF NOT EXISTS lifecycle_plans ("
           "id TEXT PRIMARY KEY,status TEXT NOT NULL,created_us INTEGER NOT NULL,"
           "updated_us INTEGER NOT NULL,payload TEXT NOT NULL)", now;
    (*_impl->session)
        << "CREATE INDEX IF NOT EXISTS idx_lifecycle_plans_status "
           "ON lifecycle_plans(status,updated_us)", now;
    (*_impl->session)
        << "CREATE TABLE IF NOT EXISTS lifecycle_requests ("
           "request_id TEXT PRIMARY KEY,fingerprint TEXT NOT NULL,"
           "updated_us INTEGER NOT NULL,payload TEXT NOT NULL)", now;
    (*_impl->session)
        << "CREATE INDEX IF NOT EXISTS idx_lifecycle_requests_updated "
           "ON lifecycle_requests(updated_us)", now;
    verifyIntegrity();
}

void SqliteMaintenanceStore::openExisting(MaintenanceStoreOpenMode mode)
{
    if (_impl->session || _impl->lease)
        throw Poco::IllegalStateException(
            "Lifecycle maintenance store is already initialized");
    const Poco::File database(_impl->path);
    if (!database.exists() || !database.isFile())
        throw Poco::FileNotFoundException(
            "Lifecycle maintenance database does not exist", _impl->path);
    _impl->lease = std::make_unique<ExclusiveStoreLease>(_impl->path);
    Poco::Data::SQLite::Connector::registerConnector();
    _impl->session = std::make_unique<Poco::Data::Session>("SQLite", _impl->path);
    _impl->readOnly = mode == MaintenanceStoreOpenMode::readOnly;
    if (_impl->readOnly) (*_impl->session) << "PRAGMA query_only=ON", now;
    verifyIntegrity();
}

std::string SqliteMaintenanceStore::allocatePlanId()
{
    Poco::Data::Transaction transaction(*_impl->session);
    std::vector<std::string> values;
    (*_impl->session)
        << "SELECT value FROM lifecycle_metadata WHERE key='next_plan_id'",
        into(values), now;
    if (values.size() != 1)
        throw Poco::DataFormatException("Lifecycle plan sequence is missing");
    const auto current = parseSequence(values.front());
    if (current == std::numeric_limits<std::uint64_t>::max())
        throw Poco::RangeException("Lifecycle plan sequence is exhausted");
    const auto next = current + 1;
    const auto encoded = std::to_string(next);
    (*_impl->session)
        << "UPDATE lifecycle_metadata SET value=? WHERE key='next_plan_id'",
        useRef(encoded), now;
    transaction.commit();
    return "maintenance-" + encoded;
}

void SqliteMaintenanceStore::save(const MaintenancePlan& plan)
{
    _impl->savePlan(plan);
    _impl->prune();
}

void SqliteMaintenanceStore::complete(
    const MaintenancePlan& plan, const StoredMaintenanceRequest& request)
{
    if (request.requestId.empty() || request.requestId.size() > 128 ||
        request.fingerprint.empty() || request.fingerprint.size() > 512 ||
        request.operation.plan.id != plan.id ||
        serializePlan(request.operation.plan) != serializePlan(plan))
        throw Poco::InvalidArgumentException(
            "Invalid lifecycle maintenance completion record");
    Poco::Data::Transaction transaction(*_impl->session);
    std::vector<std::string> existing;
    std::vector<std::string> existingPayloads;
    (*_impl->session)
        << "SELECT fingerprint,payload FROM lifecycle_requests WHERE request_id=?",
        useRef(request.requestId), into(existing), into(existingPayloads), now;
    if (!existing.empty())
    {
        const auto requestedPayload = serializeOperation(request.operation);
        if (existing.size() != 1 || existingPayloads.size() != 1 ||
            existing.front() != request.fingerprint ||
            existingPayloads.front() != requestedPayload)
            throw Poco::InvalidArgumentException(
                "Lifecycle request ID is already bound to a different result");
        transaction.commit();
        return;
    }
    _impl->savePlan(plan);
    {
        const std::string payload = serializeOperation(request.operation);
        (*_impl->session)
            << "INSERT INTO lifecycle_requests(request_id,fingerprint,updated_us,payload) "
               "VALUES(?,?,?,?)",
            useRef(request.requestId), useRef(request.fingerprint),
            useRef(plan.updatedMicroseconds), useRef(payload), now;
    }
    _impl->prune();
    transaction.commit();
}

std::optional<StoredMaintenanceRequest>
SqliteMaintenanceStore::findByRequestId(const std::string& requestId) const
{
    if (requestId.empty() || requestId.size() > 128)
        throw Poco::InvalidArgumentException(
            "Invalid lifecycle maintenance request ID");
    std::vector<std::string> fingerprints;
    std::vector<std::string> payloads;
    (*_impl->session)
        << "SELECT fingerprint,payload FROM lifecycle_requests WHERE request_id=?",
        useRef(requestId), into(fingerprints), into(payloads), now;
    if (payloads.empty()) return std::nullopt;
    if (payloads.size() != 1 || fingerprints.size() != 1)
        throw Poco::DataFormatException("Duplicate lifecycle request record");
    return StoredMaintenanceRequest{
        requestId, fingerprints.front(), deserializeOperation(payloads.front())};
}

std::vector<MaintenancePlan> SqliteMaintenanceStore::incomplete() const
{
    std::vector<std::string> payloads;
    (*_impl->session)
        << "SELECT payload FROM lifecycle_plans WHERE status IN "
           "('draining','restoring','drainRecoveryPending',"
           "'restoreRecoveryPending','drained','restoreRolledBack') "
           "ORDER BY created_us,id",
        into(payloads), now;
    std::vector<MaintenancePlan> result;
    result.reserve(payloads.size());
    for (const auto& payload : payloads) result.push_back(deserializePlan(payload));
    return result;
}

std::vector<MaintenancePlan> SqliteMaintenanceStore::history(
    std::size_t limit) const
{
    if (limit > 100000)
        throw Poco::InvalidArgumentException(
            "Lifecycle maintenance history limit exceeds safe bounds");
    std::vector<std::string> payloads;
    const auto bounded = static_cast<Poco::Int64>(limit);
    (*_impl->session)
        << "SELECT payload FROM lifecycle_plans ORDER BY created_us DESC,id DESC "
           "LIMIT ?",
        useRef(bounded), into(payloads), now;
    std::vector<MaintenancePlan> result;
    result.reserve(payloads.size());
    for (const auto& payload : payloads) result.push_back(deserializePlan(payload));
    std::reverse(result.begin(), result.end());
    return result;
}

void SqliteMaintenanceStore::verifyIntegrity() const
{
    if (!_impl->session)
        throw Poco::IllegalStateException(
            "Lifecycle maintenance store is not initialized");
    static_cast<void>(verifySession(*_impl->session, _impl->path));
}

MaintenanceStoreSnapshot SqliteMaintenanceStore::snapshot() const
{
    if (!_impl->session)
        throw Poco::IllegalStateException(
            "Lifecycle maintenance store is not initialized");
    return verifySession(*_impl->session, _impl->path);
}

MaintenanceStoreSnapshot SqliteMaintenanceStore::backupTo(
    const std::string& destination) const
{
    if (!_impl->session)
        throw Poco::IllegalStateException(
            "Lifecycle maintenance store is not initialized");
    if (destination.empty())
        throw Poco::InvalidArgumentException(
            "Lifecycle maintenance backup destination is empty");
    if (samePath(_impl->path, destination))
        throw Poco::InvalidArgumentException(
            "Lifecycle maintenance backup destination matches the source");
    if (_impl->readOnly)
        throw Poco::IllegalStateException(
            "Lifecycle maintenance store was opened read-only");

    static_cast<void>(verifySession(*_impl->session, _impl->path));
    const auto target = absolutePath(destination);
    ExclusiveStoreLease destinationLease(target);
    Poco::File targetFile(target);
    if (targetFile.exists())
        throw Poco::FileExistsException(
            "Lifecycle maintenance backup destination already exists", target);
    Poco::Path parent(target);
    parent.makeParent();
    if (!parent.toString().empty()) Poco::File(parent).createDirectories();

    (*_impl->session) << "VACUUM INTO " + sqlString(target), now;
    Poco::Data::Session backup("SQLite", target);
    backup << "PRAGMA query_only=ON", now;
    return verifySession(backup, target);
}
} // namespace PocoDDS::Lifecycle
