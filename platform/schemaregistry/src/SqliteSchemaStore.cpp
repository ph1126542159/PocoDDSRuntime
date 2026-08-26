#include "PocoDDS/SchemaRegistry/SqliteSchemaStore.h"

#include <Poco/Data/SQLite/Connector.h>
#include <Poco/Data/Session.h>
#include <Poco/Data/Statement.h>
#include <Poco/Data/Transaction.h>
#include <Poco/Exception.h>
#include <Poco/File.h>
#include <Poco/Path.h>

#include <utility>

namespace PocoDDS::SchemaRegistry
{
using namespace Poco::Data::Keywords;

class SqliteSchemaStore::Impl
{
public:
    explicit Impl(std::string value): path(std::move(value)) {}
    std::string path;
    mutable std::unique_ptr<Poco::Data::Session> session;
};

SqliteSchemaStore::SqliteSchemaStore(std::string path)
    : _impl(std::make_unique<Impl>(std::move(path)))
{
    if (_impl->path.empty())
        throw Poco::InvalidArgumentException("Schema registry database path is empty");
}

SqliteSchemaStore::~SqliteSchemaStore() = default;

void SqliteSchemaStore::initialize()
{
    Poco::Path path(_impl->path);
    if (path.depth() > 0) Poco::File(path.makeParent()).createDirectories();
    Poco::Data::SQLite::Connector::registerConnector();
    _impl->session = std::make_unique<Poco::Data::Session>("SQLite", _impl->path);
    (*_impl->session) << "PRAGMA journal_mode=WAL", now;
    (*_impl->session) << "PRAGMA synchronous=FULL", now;
    (*_impl->session)
        << "CREATE TABLE IF NOT EXISTS schema_registry_metadata ("
           "key TEXT PRIMARY KEY,value TEXT NOT NULL)", now;
    (*_impl->session)
        << "INSERT OR IGNORE INTO schema_registry_metadata(key,value) "
           "VALUES('schema_version','1')", now;
    std::vector<std::string> versions;
    (*_impl->session)
        << "SELECT value FROM schema_registry_metadata WHERE key='schema_version'",
        into(versions), now;
    if (versions.size() != 1 || versions.front() != "1")
        throw Poco::DataFormatException("Unsupported schema registry database version");
    (*_impl->session)
        << "CREATE TABLE IF NOT EXISTS registered_schemas ("
           "subject TEXT NOT NULL,version TEXT NOT NULL,fingerprint TEXT NOT NULL,"
           "registered_us INTEGER NOT NULL,deprecated INTEGER NOT NULL DEFAULT 0,"
           "payload TEXT NOT NULL,PRIMARY KEY(subject,version))", now;
    (*_impl->session)
        << "CREATE INDEX IF NOT EXISTS idx_registered_schemas_subject "
           "ON registered_schemas(subject,registered_us)", now;
}

std::vector<SchemaDescriptor> SqliteSchemaStore::all() const
{
    std::vector<std::string> payloads;
    std::vector<Poco::Int64> registered;
    std::vector<int> deprecated;
    (*_impl->session)
        << "SELECT payload,registered_us,deprecated FROM registered_schemas "
           "ORDER BY subject,registered_us,version",
        into(payloads), into(registered), into(deprecated), now;
    std::vector<SchemaDescriptor> result;
    result.reserve(payloads.size());
    for (std::size_t index = 0; index < payloads.size(); ++index)
    {
        auto schema = parseSchemaDocument(payloads[index]);
        schema.registeredMicroseconds = registered[index];
        schema.deprecated = deprecated[index] != 0;
        result.push_back(std::move(schema));
    }
    return result;
}

std::optional<SchemaDescriptor> SqliteSchemaStore::find(
    const std::string& subject, const std::string& version) const
{
    std::vector<std::string> payloads;
    std::vector<Poco::Int64> registered;
    std::vector<int> deprecated;
    (*_impl->session)
        << "SELECT payload,registered_us,deprecated FROM registered_schemas "
           "WHERE subject=? AND version=?",
        useRef(subject), useRef(version), into(payloads), into(registered), into(deprecated), now;
    if (payloads.empty()) return std::nullopt;
    auto schema = parseSchemaDocument(payloads.front());
    schema.registeredMicroseconds = registered.front();
    schema.deprecated = deprecated.front() != 0;
    return schema;
}

void SqliteSchemaStore::insert(const std::vector<SchemaDescriptor>& schemas)
{
    Poco::Data::Transaction transaction(*_impl->session);
    for (const auto& input : schemas)
    {
        const auto schema = normalizeSchema(input);
        const std::string payload = schemaDocument(schema);
        const int deprecated = schema.deprecated ? 1 : 0;
        (*_impl->session)
            << "INSERT INTO registered_schemas(subject,version,fingerprint,registered_us,"
               "deprecated,payload) VALUES(?,?,?,?,?,?)",
            useRef(schema.subject), useRef(schema.version), useRef(schema.fingerprint),
            useRef(schema.registeredMicroseconds), useRef(deprecated), useRef(payload), now;
    }
    transaction.commit();
}

bool SqliteSchemaStore::deprecate(const std::string& subject, const std::string& version)
{
    Poco::Data::Statement statement(*_impl->session);
    statement << "UPDATE registered_schemas SET deprecated=1 WHERE subject=? AND version=?",
        useRef(subject), useRef(version);
    return statement.execute() != 0;
}
} // namespace PocoDDS::SchemaRegistry
