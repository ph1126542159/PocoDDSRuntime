#include "PocoDDS/SchemaRegistry/Registry.h"

#include <Poco/Exception.h>

#include <algorithm>
#include <utility>

namespace PocoDDS::SchemaRegistry
{
namespace
{
int majorVersion(const std::string& version)
{
    return std::stoi(version.substr(0, version.find('.')));
}

void sortSchemas(std::vector<SchemaDescriptor>& schemas)
{
    std::sort(schemas.begin(), schemas.end(), [](const auto& left, const auto& right) {
        if (left.subject != right.subject) return left.subject < right.subject;
        return compareSemanticVersion(left.version, right.version) < 0;
    });
}

std::optional<SchemaDescriptor> latestFrom(const std::vector<SchemaDescriptor>& schemas,
                                           const std::string& subject)
{
    std::optional<SchemaDescriptor> result;
    for (const auto& schema : schemas)
        if (schema.subject == subject &&
            (!result || compareSemanticVersion(schema.version, result->version) > 0))
            result = schema;
    return result;
}

RegistrationResult evaluateRegistration(const SchemaDescriptor& schema,
                                        const std::vector<SchemaDescriptor>& catalog)
{
    RegistrationResult result;
    result.schema = schema;
    const auto exact = std::find_if(catalog.begin(), catalog.end(), [&](const auto& item) {
        return item.subject == schema.subject && item.version == schema.version;
    });
    if (exact != catalog.end())
    {
        result.schema = *exact;
        if (exact->fingerprint == schema.fingerprint)
        {
            result.accepted = true;
            result.idempotent = true;
            result.code = "SCHEMA_ALREADY_REGISTERED";
            result.message = "identical immutable schema already exists";
        }
        else
        {
            result.code = "SCHEMA_VERSION_CONFLICT";
            result.message = "subject and version already exist with a different fingerprint";
        }
        return result;
    }

    const auto previous = latestFrom(catalog, schema.subject);
    if (previous)
    {
        if (compareSemanticVersion(schema.version, previous->version) <= 0)
        {
            result.code = "SCHEMA_VERSION_NOT_MONOTONIC";
            result.message = "schema version must be greater than the latest registered version";
            return result;
        }
        if (schema.owner != previous->owner || schema.kind != previous->kind ||
            schema.format != previous->format)
        {
            result.code = "SCHEMA_IDENTITY_CHANGED";
            result.message = "schema owner, kind and format are immutable within a subject";
            return result;
        }
        if (schema.compatibility != previous->compatibility)
        {
            result.code = "SCHEMA_POLICY_CHANGED";
            result.message = "compatibility policy is immutable within a subject";
            return result;
        }
        result.compatibility = checkCompatibility(*previous, schema, schema.compatibility);
        if (!result.compatibility.compatible &&
            majorVersion(schema.version) <= majorVersion(previous->version))
        {
            result.code = "SCHEMA_INCOMPATIBLE";
            result.message = "breaking schema changes require a higher major version";
            return result;
        }
    }
    else
    {
        result.compatibility.mode = schema.compatibility;
        result.compatibility.compatible = true;
    }

    result.accepted = true;
    if (!result.compatibility.compatible)
    {
        result.code = "SCHEMA_BREAKING_MAJOR_REGISTERED";
        result.message = "breaking schema registered under an explicit major version";
    }
    else
    {
        result.code = "SCHEMA_REGISTERED";
        result.message = "schema registered";
    }
    return result;
}
} // namespace

Registry::Registry(std::shared_ptr<SchemaStore> store): _store(std::move(store))
{
    if (!_store) throw Poco::InvalidArgumentException("Schema store is required");
}

void Registry::initialize()
{
    std::lock_guard<std::mutex> lock(_mutex);
    if (_initialized) return;
    _store->initialize();
    _schemas = _store->all();
    for (auto& schema : _schemas) schema = normalizeSchema(std::move(schema));
    sortSchemas(_schemas);
    for (std::size_t index = 1; index < _schemas.size(); ++index)
        if (_schemas[index - 1].subject == _schemas[index].subject &&
            _schemas[index - 1].version == _schemas[index].version)
            throw Poco::DataFormatException("Duplicate schema in persistent registry: " +
                                            _schemas[index].subject + "@" +
                                            _schemas[index].version);
    _initialized = true;
}

RegistrationResult Registry::registerSchema(SchemaDescriptor input)
{
    auto batch = registerSchemas({std::move(input)});
    if (!batch.results.empty()) return batch.results.front();
    return {false, false, "SCHEMA_INVALID", "schema registration produced no result", {}, {}};
}

BatchRegistrationResult Registry::registerSchemas(std::vector<SchemaDescriptor> inputs)
{
    BatchRegistrationResult batch;
    if (inputs.empty())
    {
        batch.accepted = true;
        return batch;
    }
    try
    {
        for (auto& schema : inputs) schema = normalizeSchema(std::move(schema));
        std::lock_guard<std::mutex> lock(_mutex);
        if (!_initialized) throw Poco::IllegalStateException("Schema registry is not initialized");
        auto simulated = _schemas;
        std::vector<SchemaDescriptor> pending;
        for (const auto& schema : inputs)
        {
            auto result = evaluateRegistration(schema, simulated);
            batch.results.push_back(result);
            if (!result.accepted) return batch;
            if (!result.idempotent)
            {
                simulated.push_back(schema);
                pending.push_back(schema);
                sortSchemas(simulated);
            }
        }
        _store->insert(pending);
        _schemas = std::move(simulated);
        batch.accepted = true;
    }
    catch (const Poco::Exception& exception)
    {
        batch.results.clear();
        batch.results.push_back({false, false, "SCHEMA_INVALID", exception.displayText(), {}, {}});
    }
    catch (const std::exception& exception)
    {
        batch.results.clear();
        batch.results.push_back({false, false, "SCHEMA_INVALID", exception.what(), {}, {}});
    }
    return batch;
}

std::optional<SchemaDescriptor> Registry::find(const std::string& subject,
                                               const std::string& version) const
{
    std::lock_guard<std::mutex> lock(_mutex);
    const auto found = std::find_if(_schemas.begin(), _schemas.end(), [&](const auto& item) {
        return item.subject == subject && item.version == version;
    });
    return found == _schemas.end() ? std::nullopt : std::optional<SchemaDescriptor>(*found);
}

std::optional<SchemaDescriptor> Registry::latest(const std::string& subject) const
{
    std::lock_guard<std::mutex> lock(_mutex);
    return latestLocked(subject);
}

std::optional<SchemaDescriptor> Registry::latestLocked(const std::string& subject) const
{
    std::optional<SchemaDescriptor> result;
    for (const auto& schema : _schemas)
        if (schema.subject == subject &&
            (!result || compareSemanticVersion(schema.version, result->version) > 0))
            result = schema;
    return result;
}

std::vector<SchemaDescriptor> Registry::versions(const std::string& subject) const
{
    std::lock_guard<std::mutex> lock(_mutex);
    std::vector<SchemaDescriptor> result;
    for (const auto& schema : _schemas)
        if (schema.subject == subject) result.push_back(schema);
    return result;
}

std::vector<SchemaDescriptor> Registry::schemas() const
{
    std::lock_guard<std::mutex> lock(_mutex);
    return _schemas;
}

bool Registry::deprecate(const std::string& subject, const std::string& version)
{
    std::lock_guard<std::mutex> lock(_mutex);
    const auto found = std::find_if(_schemas.begin(), _schemas.end(), [&](const auto& item) {
        return item.subject == subject && item.version == version;
    });
    if (found == _schemas.end()) return false;
    if (found->deprecated) return true;
    if (!_store->deprecate(subject, version)) return false;
    found->deprecated = true;
    return true;
}
} // namespace PocoDDS::SchemaRegistry
