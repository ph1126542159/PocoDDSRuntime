#include "PocoDDS/StoreForward/SqliteOutboxStore.h"

#include <Poco/Data/SQLite/Connector.h>
#include <Poco/Data/Session.h>
#include <Poco/Data/Statement.h>
#include <Poco/Exception.h>
#include <Poco/File.h>
#include <Poco/JSON/Object.h>
#include <Poco/JSON/Parser.h>
#include <Poco/Path.h>

#include <sstream>
#include <utility>

namespace PocoDDS::StoreForward
{
using namespace Poco::Data::Keywords;

namespace
{
std::string serialize(const Message& message)
{
    Poco::JSON::Object root;
    root.set("schemaVersion", 1);
    root.set("id", message.id);
    root.set("provider", message.provider);
    root.set("destination", message.destination);
    root.set("idempotencyKey", message.idempotencyKey);
    root.set("orderingKey", message.orderingKey);
    root.set("payload", message.payload);
    root.set("state", stateName(message.state));
    root.set("attempts", message.attempts);
    root.set("nextAttemptMicroseconds", message.nextAttemptMicroseconds);
    root.set("expiresAtMicroseconds", message.expiresAtMicroseconds);
    root.set("createdMicroseconds", message.createdMicroseconds);
    root.set("updatedMicroseconds", message.updatedMicroseconds);
    root.set("deliveredMicroseconds", message.deliveredMicroseconds);
    root.set("lastErrorCode", message.lastErrorCode);
    root.set("lastErrorMessage", message.lastErrorMessage);
    root.set("revision", message.revision);
    std::ostringstream stream;
    root.stringify(stream);
    return stream.str();
}

Message deserialize(const std::string& payload)
{
    const auto root = Poco::JSON::Parser().parse(payload).extract<Poco::JSON::Object::Ptr>();
    if (!root || root->getValue<int>("schemaVersion") != 1)
        throw Poco::DataFormatException("Unsupported outbox message schema");
    Message message;
    message.id = root->getValue<std::string>("id");
    message.provider = root->getValue<std::string>("provider");
    message.destination = root->getValue<std::string>("destination");
    message.idempotencyKey = root->getValue<std::string>("idempotencyKey");
    message.orderingKey = root->getValue<std::string>("orderingKey");
    message.payload = root->getValue<std::string>("payload");
    message.state = parseState(root->getValue<std::string>("state"));
    message.attempts = root->getValue<unsigned>("attempts");
    message.nextAttemptMicroseconds =
        root->getValue<Poco::Int64>("nextAttemptMicroseconds");
    message.expiresAtMicroseconds =
        root->getValue<Poco::Int64>("expiresAtMicroseconds");
    message.createdMicroseconds = root->getValue<Poco::Int64>("createdMicroseconds");
    message.updatedMicroseconds = root->getValue<Poco::Int64>("updatedMicroseconds");
    message.deliveredMicroseconds =
        root->getValue<Poco::Int64>("deliveredMicroseconds");
    message.lastErrorCode = root->getValue<std::string>("lastErrorCode");
    message.lastErrorMessage = root->getValue<std::string>("lastErrorMessage");
    message.revision = root->getValue<Poco::UInt64>("revision");
    return message;
}
} // namespace

class SqliteOutboxStore::Impl
{
public:
    explicit Impl(std::string databasePath): path(std::move(databasePath)) {}

    std::string path;
    mutable std::unique_ptr<Poco::Data::Session> session;
};

SqliteOutboxStore::SqliteOutboxStore(std::string path)
    : _impl(std::make_unique<Impl>(std::move(path)))
{
    if (_impl->path.empty()) throw Poco::InvalidArgumentException("Outbox database path is empty");
}

SqliteOutboxStore::~SqliteOutboxStore() = default;

void SqliteOutboxStore::initialize()
{
    Poco::Path path(_impl->path);
    if (path.depth() > 0) Poco::File(path.makeParent()).createDirectories();
    Poco::Data::SQLite::Connector::registerConnector();
    _impl->session = std::make_unique<Poco::Data::Session>("SQLite", _impl->path);
    (*_impl->session) << "PRAGMA journal_mode=WAL", now;
    (*_impl->session) << "PRAGMA synchronous=FULL", now;
    (*_impl->session)
        << "CREATE TABLE IF NOT EXISTS outbox_metadata ("
           "key TEXT PRIMARY KEY,value TEXT NOT NULL)", now;
    (*_impl->session)
        << "INSERT OR IGNORE INTO outbox_metadata(key,value) VALUES('schema_version','1')",
        now;
    std::vector<std::string> versions;
    (*_impl->session)
        << "SELECT value FROM outbox_metadata WHERE key='schema_version'",
        into(versions), now;
    if (versions.size() != 1 || versions.front() != "1")
        throw Poco::DataFormatException("Unsupported outbox database schema");
    (*_impl->session)
        << "CREATE TABLE IF NOT EXISTS outbox_messages ("
           "id TEXT PRIMARY KEY,provider TEXT NOT NULL,idempotency_key TEXT NOT NULL,"
           "ordering_key TEXT NOT NULL,state TEXT NOT NULL,created_us INTEGER NOT NULL,"
           "updated_us INTEGER NOT NULL,next_attempt_us INTEGER NOT NULL,payload TEXT NOT NULL,"
           "UNIQUE(provider,idempotency_key))",
        now;
    (*_impl->session)
        << "CREATE INDEX IF NOT EXISTS idx_outbox_due "
           "ON outbox_messages(state,next_attempt_us,created_us)", now;
    (*_impl->session)
        << "CREATE INDEX IF NOT EXISTS idx_outbox_ordering "
           "ON outbox_messages(provider,ordering_key,state,created_us)", now;
}

void SqliteOutboxStore::save(const Message& message)
{
    if (!_impl->session) throw Poco::IllegalStateException("Outbox store is not initialized");
    const std::string state = stateName(message.state);
    const std::string payload = serialize(message);
    (*_impl->session)
        << "INSERT INTO outbox_messages(id,provider,idempotency_key,ordering_key,state,"
           "created_us,updated_us,next_attempt_us,payload) VALUES(?,?,?,?,?,?,?,?,?) "
           "ON CONFLICT(id) DO UPDATE SET provider=excluded.provider,"
           "idempotency_key=excluded.idempotency_key,ordering_key=excluded.ordering_key,"
           "state=excluded.state,created_us=excluded.created_us,updated_us=excluded.updated_us,"
           "next_attempt_us=excluded.next_attempt_us,payload=excluded.payload",
        useRef(message.id), useRef(message.provider), useRef(message.idempotencyKey),
        useRef(message.orderingKey), useRef(state), useRef(message.createdMicroseconds),
        useRef(message.updatedMicroseconds), useRef(message.nextAttemptMicroseconds),
        useRef(payload), now;
}

std::optional<Message> SqliteOutboxStore::find(const std::string& id) const
{
    std::vector<std::string> payloads;
    (*_impl->session) << "SELECT payload FROM outbox_messages WHERE id=?",
        useRef(id), into(payloads), now;
    return payloads.empty() ? std::nullopt
                            : std::optional<Message>(deserialize(payloads.front()));
}

std::optional<Message> SqliteOutboxStore::findByIdempotencyKey(
    const std::string& provider, const std::string& idempotencyKey) const
{
    std::vector<std::string> payloads;
    (*_impl->session)
        << "SELECT payload FROM outbox_messages WHERE provider=? AND idempotency_key=?",
        useRef(provider), useRef(idempotencyKey), into(payloads), now;
    return payloads.empty() ? std::nullopt
                            : std::optional<Message>(deserialize(payloads.front()));
}

std::size_t SqliteOutboxStore::activeCount() const
{
    Poco::Int64 count = 0;
    const std::string pending = stateName(State::pending);
    const std::string delivering = stateName(State::delivering);
    (*_impl->session)
        << "SELECT COUNT(*) FROM outbox_messages WHERE state=? OR state=?",
        useRef(pending), useRef(delivering), into(count), now;
    return static_cast<std::size_t>(count);
}

std::vector<Message> SqliteOutboxStore::due(Poco::Int64 nowMicroseconds,
                                             std::size_t limit) const
{
    std::vector<std::string> payloads;
    const std::string pending = stateName(State::pending);
    const std::string delivering = stateName(State::delivering);
    const auto boundedLimit = static_cast<Poco::Int64>(limit);
    (*_impl->session)
        << "SELECT m.payload FROM outbox_messages m "
           "WHERE m.state=? AND m.next_attempt_us<=? AND "
           "(m.ordering_key='' OR NOT EXISTS ("
           "SELECT 1 FROM outbox_messages earlier WHERE earlier.provider=m.provider "
           "AND earlier.ordering_key=m.ordering_key AND "
           "(earlier.state=? OR earlier.state=?) AND "
           "(earlier.created_us<m.created_us OR "
           "(earlier.created_us=m.created_us AND earlier.id<m.id)))) "
           "ORDER BY m.created_us,m.id LIMIT ?",
        useRef(pending), useRef(nowMicroseconds), useRef(pending), useRef(delivering),
        useRef(boundedLimit), into(payloads), now;
    std::vector<Message> result;
    result.reserve(payloads.size());
    for (const auto& payload : payloads) result.push_back(deserialize(payload));
    return result;
}

std::vector<Message> SqliteOutboxStore::list() const
{
    std::vector<std::string> payloads;
    (*_impl->session) << "SELECT payload FROM outbox_messages ORDER BY created_us,id",
        into(payloads), now;
    std::vector<Message> result;
    result.reserve(payloads.size());
    for (const auto& payload : payloads) result.push_back(deserialize(payload));
    return result;
}

std::size_t SqliteOutboxStore::recoverDelivering(Poco::Int64 nowMicroseconds)
{
    std::vector<std::string> payloads;
    const std::string delivering = stateName(State::delivering);
    (*_impl->session) << "SELECT payload FROM outbox_messages WHERE state=?",
        useRef(delivering), into(payloads), now;
    for (const auto& payload : payloads)
    {
        auto message = deserialize(payload);
        message.state = State::pending;
        message.nextAttemptMicroseconds = nowMicroseconds;
        message.updatedMicroseconds = nowMicroseconds;
        message.lastErrorCode = "delivery-interrupted";
        message.lastErrorMessage = "Runtime stopped during provider delivery";
        ++message.revision;
        save(message);
    }
    return payloads.size();
}

std::size_t SqliteOutboxStore::purgeTerminalBefore(Poco::Int64 cutoffMicroseconds)
{
    Poco::Int64 count = 0;
    const std::string delivered = stateName(State::delivered);
    const std::string cancelled = stateName(State::cancelled);
    (*_impl->session)
        << "SELECT COUNT(*) FROM outbox_messages WHERE (state=? OR state=?) AND updated_us<?",
        useRef(delivered), useRef(cancelled), useRef(cutoffMicroseconds), into(count), now;
    (*_impl->session)
        << "DELETE FROM outbox_messages WHERE (state=? OR state=?) AND updated_us<?",
        useRef(delivered), useRef(cancelled), useRef(cutoffMicroseconds), now;
    return static_cast<std::size_t>(count);
}
} // namespace PocoDDS::StoreForward
