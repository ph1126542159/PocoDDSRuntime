#include "PocoDDS/ConfigTransaction/SqliteTransactionStore.h"

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

#include <sstream>
#include <utility>

namespace PocoDDS::ConfigTransaction
{
using namespace Poco::Data::Keywords;

namespace
{
Poco::JSON::Object::Ptr valuesObject(const Values& values)
{
    Poco::JSON::Object::Ptr result = new Poco::JSON::Object;
    for (const auto& [key, value] : values) result->set(key, value);
    return result;
}

Values parseValues(const Poco::JSON::Object::Ptr& object)
{
    Values result;
    if (!object) return result;
    for (const auto& key : object->getNames())
        result.emplace(key, object->getValue<std::string>(key));
    return result;
}

Poco::JSON::Array::Ptr stringArray(const std::vector<std::string>& values)
{
    Poco::JSON::Array::Ptr result = new Poco::JSON::Array;
    for (const auto& value : values) result->add(value);
    return result;
}

std::vector<std::string> parseStrings(const Poco::JSON::Array::Ptr& array)
{
    std::vector<std::string> result;
    if (!array) return result;
    result.reserve(array->size());
    for (std::size_t index = 0; index < array->size(); ++index)
        result.push_back(array->getElement<std::string>(static_cast<unsigned int>(index)));
    return result;
}

Poco::JSON::Object::Ptr snapshotObject(const Snapshot& snapshot)
{
    Poco::JSON::Object::Ptr result = new Poco::JSON::Object;
    result->set("generation", snapshot.generation);
    result->set("digest", snapshot.digest);
    result->set("values", valuesObject(snapshot.values));
    result->set("committedMicroseconds", snapshot.committedMicroseconds);
    return result;
}

Snapshot parseSnapshot(const Poco::JSON::Object::Ptr& object)
{
    if (!object) throw Poco::DataFormatException("Configuration snapshot is missing");
    Snapshot result;
    result.generation = object->getValue<Poco::UInt64>("generation");
    result.digest = object->getValue<std::string>("digest");
    result.values = parseValues(object->getObject("values"));
    result.committedMicroseconds = object->getValue<Poco::Int64>("committedMicroseconds");
    if (result.digest != snapshotDigest(result.values))
        throw Poco::DataFormatException("Configuration snapshot digest mismatch");
    return result;
}

std::string serialize(const Snapshot& snapshot)
{
    Poco::JSON::Object root;
    root.set("schemaVersion", 1);
    root.set("snapshot", snapshotObject(snapshot));
    std::ostringstream stream;
    root.stringify(stream);
    return stream.str();
}

Snapshot deserializeSnapshot(const std::string& payload)
{
    const auto root = Poco::JSON::Parser().parse(payload).extract<Poco::JSON::Object::Ptr>();
    if (!root || root->getValue<int>("schemaVersion") != 1)
        throw Poco::DataFormatException("Unsupported configuration snapshot schema");
    return parseSnapshot(root->getObject("snapshot"));
}

std::string serialize(const TransactionRecord& record)
{
    Poco::JSON::Object root;
    root.set("schemaVersion", 1);
    root.set("id", record.id);
    root.set("requestId", record.requestId);
    root.set("inputDigest", record.inputDigest);
    root.set("principal", record.principal);
    root.set("status", statusName(record.status));
    root.set("previous", snapshotObject(record.previous));
    root.set("candidate", snapshotObject(record.candidate));
    root.set("changedKeys", stringArray(record.changedKeys));
    root.set("participants", stringArray(record.participants));
    root.set("commitAttempted", stringArray(record.commitAttempted));
    root.set("committedParticipants", stringArray(record.committedParticipants));
    root.set("errorCode", record.errorCode);
    root.set("errorMessage", record.errorMessage);
    root.set("createdMicroseconds", record.createdMicroseconds);
    root.set("updatedMicroseconds", record.updatedMicroseconds);
    std::ostringstream stream;
    root.stringify(stream);
    return stream.str();
}

TransactionRecord deserializeRecord(const std::string& payload)
{
    const auto root = Poco::JSON::Parser().parse(payload).extract<Poco::JSON::Object::Ptr>();
    if (!root || root->getValue<int>("schemaVersion") != 1)
        throw Poco::DataFormatException("Unsupported configuration transaction schema");
    TransactionRecord result;
    result.id = root->getValue<std::string>("id");
    result.requestId = root->getValue<std::string>("requestId");
    if (root->has("inputDigest"))
        result.inputDigest = root->getValue<std::string>("inputDigest");
    if (root->has("principal"))
        result.principal = root->getValue<std::string>("principal");
    result.status = parseStatus(root->getValue<std::string>("status"));
    result.previous = parseSnapshot(root->getObject("previous"));
    result.candidate = parseSnapshot(root->getObject("candidate"));
    result.changedKeys = parseStrings(root->getArray("changedKeys"));
    result.participants = parseStrings(root->getArray("participants"));
    result.commitAttempted = parseStrings(root->getArray("commitAttempted"));
    result.committedParticipants = parseStrings(root->getArray("committedParticipants"));
    result.errorCode = root->getValue<std::string>("errorCode");
    result.errorMessage = root->getValue<std::string>("errorMessage");
    result.createdMicroseconds = root->getValue<Poco::Int64>("createdMicroseconds");
    result.updatedMicroseconds = root->getValue<Poco::Int64>("updatedMicroseconds");
    return result;
}
} // namespace

class SqliteTransactionStore::Impl
{
public:
    explicit Impl(std::string value): path(std::move(value)) {}
    std::string path;
    mutable std::unique_ptr<Poco::Data::Session> session;
};

SqliteTransactionStore::SqliteTransactionStore(std::string path)
    : _impl(std::make_unique<Impl>(std::move(path)))
{
    if (_impl->path.empty())
        throw Poco::InvalidArgumentException("Configuration transaction database path is empty");
}

SqliteTransactionStore::~SqliteTransactionStore() = default;

void SqliteTransactionStore::initialize()
{
    Poco::Path path(_impl->path);
    if (path.depth() > 0) Poco::File(path.makeParent()).createDirectories();
    Poco::Data::SQLite::Connector::registerConnector();
    _impl->session = std::make_unique<Poco::Data::Session>("SQLite", _impl->path);
    (*_impl->session) << "PRAGMA journal_mode=WAL", now;
    (*_impl->session) << "PRAGMA synchronous=FULL", now;
    (*_impl->session)
        << "CREATE TABLE IF NOT EXISTS config_metadata ("
           "key TEXT PRIMARY KEY,value TEXT NOT NULL)", now;
    (*_impl->session)
        << "INSERT OR IGNORE INTO config_metadata(key,value) VALUES('schema_version','1')", now;
    std::vector<std::string> versions;
    (*_impl->session) << "SELECT value FROM config_metadata WHERE key='schema_version'",
        into(versions), now;
    if (versions.size() != 1 || versions.front() != "1")
        throw Poco::DataFormatException("Unsupported configuration transaction database schema");
    (*_impl->session)
        << "CREATE TABLE IF NOT EXISTS config_current ("
           "singleton INTEGER PRIMARY KEY CHECK(singleton=1),payload TEXT NOT NULL)", now;
    (*_impl->session)
        << "CREATE TABLE IF NOT EXISTS config_transactions ("
           "id TEXT PRIMARY KEY,request_id TEXT NOT NULL UNIQUE,status TEXT NOT NULL,"
           "updated_us INTEGER NOT NULL,payload TEXT NOT NULL)", now;
    (*_impl->session)
        << "CREATE INDEX IF NOT EXISTS idx_config_transactions_status "
           "ON config_transactions(status,updated_us)", now;
}

std::optional<Snapshot> SqliteTransactionStore::current() const
{
    std::vector<std::string> payloads;
    (*_impl->session) << "SELECT payload FROM config_current WHERE singleton=1",
        into(payloads), now;
    if (payloads.empty()) return std::nullopt;
    return deserializeSnapshot(payloads.front());
}

void SqliteTransactionStore::seed(const Snapshot& snapshot)
{
    const std::string payload = serialize(snapshot);
    (*_impl->session)
        << "INSERT OR IGNORE INTO config_current(singleton,payload) VALUES(1,?)",
        useRef(payload), now;
}

void SqliteTransactionStore::replaceBootstrap(const Snapshot& snapshot)
{
    const std::string payload = serialize(snapshot);
    (*_impl->session) << "UPDATE config_current SET payload=? WHERE singleton=1",
        useRef(payload), now;
}

std::optional<TransactionRecord> SqliteTransactionStore::findByRequestId(
    const std::string& requestId) const
{
    std::vector<std::string> payloads;
    (*_impl->session) << "SELECT payload FROM config_transactions WHERE request_id=?",
        useRef(requestId), into(payloads), now;
    if (payloads.empty()) return std::nullopt;
    return deserializeRecord(payloads.front());
}

void SqliteTransactionStore::save(const TransactionRecord& record)
{
    const std::string status = statusName(record.status);
    const std::string payload = serialize(record);
    (*_impl->session)
        << "INSERT INTO config_transactions(id,request_id,status,updated_us,payload) "
           "VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET status=excluded.status,"
           "updated_us=excluded.updated_us,payload=excluded.payload",
        useRef(record.id), useRef(record.requestId), useRef(status),
        useRef(record.updatedMicroseconds), useRef(payload), now;
}

void SqliteTransactionStore::commit(const TransactionRecord& record,
                                    const Snapshot& snapshot)
{
    Poco::Data::Transaction transaction(*_impl->session);
    save(record);
    const std::string payload = serialize(snapshot);
    (*_impl->session)
        << "INSERT INTO config_current(singleton,payload) VALUES(1,?) "
           "ON CONFLICT(singleton) DO UPDATE SET payload=excluded.payload",
        useRef(payload), now;
    transaction.commit();
}

std::vector<TransactionRecord> SqliteTransactionStore::incomplete() const
{
    std::vector<std::string> payloads;
    (*_impl->session)
        << "SELECT payload FROM config_transactions WHERE status IN "
           "('preflighting','committing','rolling-back','rollback-failed','recovery-pending') "
           "ORDER BY updated_us,id",
        into(payloads), now;
    std::vector<TransactionRecord> result;
    result.reserve(payloads.size());
    for (const auto& payload : payloads) result.push_back(deserializeRecord(payload));
    return result;
}

std::vector<TransactionRecord> SqliteTransactionStore::history(std::size_t limit) const
{
    std::vector<std::string> payloads;
    const auto bounded = static_cast<Poco::Int64>(limit);
    (*_impl->session)
        << "SELECT payload FROM config_transactions ORDER BY updated_us DESC,id DESC LIMIT ?",
        useRef(bounded), into(payloads), now;
    std::vector<TransactionRecord> result;
    result.reserve(payloads.size());
    for (const auto& payload : payloads) result.push_back(deserializeRecord(payload));
    return result;
}
} // namespace PocoDDS::ConfigTransaction
