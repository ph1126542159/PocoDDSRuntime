#include "PocoDDS/Workflow/SqliteWorkflowStore.h"

#include <Poco/Data/SQLite/Connector.h>
#include <Poco/Data/Session.h>
#include <Poco/Data/Statement.h>
#include <Poco/Exception.h>
#include <Poco/File.h>
#include <Poco/JSON/Array.h>
#include <Poco/JSON/Object.h>
#include <Poco/JSON/Parser.h>
#include <Poco/Path.h>

#include <sstream>
#include <utility>

namespace PocoDDS::Workflow
{
using namespace Poco::Data::Keywords;

namespace
{
std::string serialize(const Instance& instance)
{
    Poco::JSON::Object root;
    root.set("schemaVersion", 1);
    root.set("id", instance.id);
    root.set("type", instance.type);
    root.set("definitionVersion", instance.definitionVersion);
    root.set("businessKey", instance.businessKey);
    root.set("input", instance.input);
    root.set("state", stateName(instance.state));
    root.set("currentStep", static_cast<Poco::UInt64>(instance.currentStep));
    Poco::JSON::Array::Ptr completed = new Poco::JSON::Array;
    for (const auto& step : instance.completedSteps) completed->add(step);
    root.set("completedSteps", completed);
    Poco::JSON::Array::Ptr compensated = new Poco::JSON::Array;
    for (const auto& step : instance.compensatedSteps) compensated->add(step);
    root.set("compensatedSteps", compensated);
    root.set("attempt", instance.attempt);
    root.set("waitingEvent", instance.waitingEvent);
    root.set("signalPayload", instance.signalPayload);
    root.set("retryAtMicroseconds", instance.retryAtMicroseconds);
    root.set("failureCode", instance.failureCode);
    root.set("failureMessage", instance.failureMessage);
    root.set("lastErrorCode", instance.lastErrorCode);
    root.set("lastErrorMessage", instance.lastErrorMessage);
    root.set("compensationRequired", instance.compensationRequired);
    root.set("cancellationRequested", instance.cancellationRequested);
    root.set("compensated", instance.compensated);
    root.set("createdMicroseconds", instance.createdMicroseconds);
    root.set("updatedMicroseconds", instance.updatedMicroseconds);
    root.set("revision", instance.revision);
    std::ostringstream stream;
    root.stringify(stream);
    return stream.str();
}

Instance deserialize(const std::string& payload)
{
    const auto root = Poco::JSON::Parser().parse(payload).extract<Poco::JSON::Object::Ptr>();
    if (!root || root->getValue<int>("schemaVersion") != 1)
        throw Poco::DataFormatException("Unsupported workflow instance schema");
    Instance result;
    result.id = root->getValue<std::string>("id");
    result.type = root->getValue<std::string>("type");
    result.definitionVersion = root->getValue<std::string>("definitionVersion");
    result.businessKey = root->getValue<std::string>("businessKey");
    result.input = root->getValue<std::string>("input");
    result.state = parseState(root->getValue<std::string>("state"));
    result.currentStep = static_cast<std::size_t>(
        root->getValue<Poco::UInt64>("currentStep"));
    const auto completed = root->getArray("completedSteps");
    if (!completed) throw Poco::DataFormatException("Workflow completedSteps is missing");
    for (std::size_t index = 0; index < completed->size(); ++index)
        result.completedSteps.push_back(
            completed->getElement<std::string>(static_cast<unsigned>(index)));
    const auto compensated = root->getArray("compensatedSteps");
    if (!compensated) throw Poco::DataFormatException("Workflow compensatedSteps is missing");
    for (std::size_t index = 0; index < compensated->size(); ++index)
        result.compensatedSteps.push_back(
            compensated->getElement<std::string>(static_cast<unsigned>(index)));
    result.attempt = root->getValue<unsigned>("attempt");
    result.waitingEvent = root->getValue<std::string>("waitingEvent");
    result.signalPayload = root->getValue<std::string>("signalPayload");
    result.retryAtMicroseconds = root->getValue<Poco::Int64>("retryAtMicroseconds");
    result.failureCode = root->getValue<std::string>("failureCode");
    result.failureMessage = root->getValue<std::string>("failureMessage");
    result.lastErrorCode = root->getValue<std::string>("lastErrorCode");
    result.lastErrorMessage = root->getValue<std::string>("lastErrorMessage");
    result.compensationRequired = root->getValue<bool>("compensationRequired");
    result.cancellationRequested = root->getValue<bool>("cancellationRequested");
    result.compensated = root->getValue<bool>("compensated");
    result.createdMicroseconds = root->getValue<Poco::Int64>("createdMicroseconds");
    result.updatedMicroseconds = root->getValue<Poco::Int64>("updatedMicroseconds");
    result.revision = root->getValue<Poco::UInt64>("revision");
    return result;
}
}

class SqliteWorkflowStore::Impl
{
public:
    explicit Impl(std::string path): path(std::move(path)) {}

    std::string path;
    mutable std::unique_ptr<Poco::Data::Session> session;
};

SqliteWorkflowStore::SqliteWorkflowStore(std::string path)
    : _impl(std::make_unique<Impl>(std::move(path)))
{
    if (_impl->path.empty()) throw Poco::InvalidArgumentException("Workflow database path is empty");
}

SqliteWorkflowStore::~SqliteWorkflowStore() = default;

void SqliteWorkflowStore::initialize()
{
    Poco::Path path(_impl->path);
    if (path.depth() > 0) Poco::File(path.makeParent()).createDirectories();
    Poco::Data::SQLite::Connector::registerConnector();
    _impl->session = std::make_unique<Poco::Data::Session>("SQLite", _impl->path);
    (*_impl->session) << "PRAGMA journal_mode=WAL", now;
    (*_impl->session) << "PRAGMA synchronous=FULL", now;
    (*_impl->session)
        << "CREATE TABLE IF NOT EXISTS workflow_instances ("
           "id TEXT PRIMARY KEY,type TEXT NOT NULL,business_key TEXT NOT NULL,"
           "state TEXT NOT NULL,retry_at_us INTEGER NOT NULL,updated_us INTEGER NOT NULL,"
           "payload TEXT NOT NULL,UNIQUE(type,business_key))",
        now;
    (*_impl->session) << "CREATE INDEX IF NOT EXISTS idx_workflow_due "
                         "ON workflow_instances(state,retry_at_us)", now;
}

void SqliteWorkflowStore::save(const Instance& instance)
{
    if (!_impl->session) throw Poco::IllegalStateException("Workflow store is not initialized");
    const std::string state = stateName(instance.state);
    const std::string payload = serialize(instance);
    (*_impl->session)
        << "INSERT INTO workflow_instances(id,type,business_key,state,retry_at_us,updated_us,payload) "
           "VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
           "type=excluded.type,business_key=excluded.business_key,state=excluded.state,"
           "retry_at_us=excluded.retry_at_us,updated_us=excluded.updated_us,payload=excluded.payload",
        useRef(instance.id), useRef(instance.type), useRef(instance.businessKey), useRef(state),
        useRef(instance.retryAtMicroseconds), useRef(instance.updatedMicroseconds), useRef(payload),
        now;
}

std::optional<Instance> SqliteWorkflowStore::find(const std::string& id) const
{
    std::vector<std::string> payloads;
    (*_impl->session) << "SELECT payload FROM workflow_instances WHERE id=?",
        useRef(id), into(payloads), now;
    return payloads.empty() ? std::nullopt
                            : std::optional<Instance>(deserialize(payloads.front()));
}

std::optional<Instance> SqliteWorkflowStore::findByBusinessKey(
    const std::string& type, const std::string& businessKey) const
{
    std::vector<std::string> payloads;
    (*_impl->session)
        << "SELECT payload FROM workflow_instances WHERE type=? AND business_key=?",
        useRef(type), useRef(businessKey), into(payloads), now;
    return payloads.empty() ? std::nullopt
                            : std::optional<Instance>(deserialize(payloads.front()));
}

std::vector<Instance> SqliteWorkflowStore::list() const
{
    std::vector<std::string> payloads;
    (*_impl->session) << "SELECT payload FROM workflow_instances ORDER BY updated_us, id",
        into(payloads), now;
    std::vector<Instance> result;
    result.reserve(payloads.size());
    for (const auto& payload : payloads) result.push_back(deserialize(payload));
    return result;
}

std::vector<Instance> SqliteWorkflowStore::due(Poco::Int64 nowMicroseconds) const
{
    std::vector<std::string> payloads;
    const std::string state = stateName(State::retryScheduled);
    (*_impl->session)
        << "SELECT payload FROM workflow_instances WHERE state=? AND retry_at_us<=? "
           "ORDER BY retry_at_us,id",
        useRef(state), useRef(nowMicroseconds), into(payloads), now;
    std::vector<Instance> result;
    result.reserve(payloads.size());
    for (const auto& payload : payloads) result.push_back(deserialize(payload));
    return result;
}

std::size_t SqliteWorkflowStore::markActiveInterrupted(Poco::Int64 nowMicroseconds)
{
    std::vector<std::string> payloads;
    const std::string queued = stateName(State::queued);
    const std::string running = stateName(State::running);
    const std::string compensating = stateName(State::compensating);
    (*_impl->session)
        << "SELECT payload FROM workflow_instances WHERE state=? OR state=? OR state=?",
        useRef(queued), useRef(running), useRef(compensating), into(payloads), now;
    for (const auto& payload : payloads)
    {
        auto instance = deserialize(payload);
        instance.state = State::interrupted;
        instance.updatedMicroseconds = nowMicroseconds;
        ++instance.revision;
        save(instance);
    }
    return payloads.size();
}
} // namespace PocoDDS::Workflow
