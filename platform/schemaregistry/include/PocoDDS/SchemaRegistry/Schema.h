#pragma once

#include "PocoDDS/SchemaRegistry/Export.h"

#include <Poco/Types.h>

#include <optional>
#include <string>
#include <vector>

namespace PocoDDS::SchemaRegistry
{
enum class SchemaKind
{
    message,
    event,
    command,
    configuration,
    service
};

enum class CompatibilityMode
{
    none,
    backward,
    forward,
    full
};

struct SchemaDescriptor
{
    std::string subject;
    std::string version;
    SchemaKind kind{SchemaKind::message};
    std::string format{"json-schema-draft-07"};
    CompatibilityMode compatibility{CompatibilityMode::backward};
    std::string owner;
    std::string definition;
    std::string fingerprint;
    Poco::Int64 registeredMicroseconds{0};
    bool deprecated{false};
};

struct CompatibilityIssue
{
    std::string direction;
    std::string path;
    std::string code;
    std::string message;
};

struct CompatibilityReport
{
    CompatibilityMode mode{CompatibilityMode::backward};
    bool compatible{true};
    std::vector<CompatibilityIssue> issues;
};

struct RegistrationResult
{
    bool accepted{false};
    bool idempotent{false};
    std::string code;
    std::string message;
    SchemaDescriptor schema;
    CompatibilityReport compatibility;
};

struct BatchRegistrationResult
{
    bool accepted{false};
    std::vector<RegistrationResult> results;
};

PDR_SCHEMA_REGISTRY_API std::string kindName(SchemaKind value);
PDR_SCHEMA_REGISTRY_API SchemaKind parseKind(const std::string& value);
PDR_SCHEMA_REGISTRY_API std::string compatibilityName(CompatibilityMode value);
PDR_SCHEMA_REGISTRY_API CompatibilityMode parseCompatibility(const std::string& value);
PDR_SCHEMA_REGISTRY_API int compareSemanticVersion(const std::string& left,
                                                   const std::string& right);
PDR_SCHEMA_REGISTRY_API std::string canonicalDefinition(const std::string& definition);
PDR_SCHEMA_REGISTRY_API std::string schemaFingerprint(const SchemaDescriptor& schema);
PDR_SCHEMA_REGISTRY_API SchemaDescriptor normalizeSchema(SchemaDescriptor schema);
PDR_SCHEMA_REGISTRY_API CompatibilityReport checkCompatibility(
    const SchemaDescriptor& previous,
    const SchemaDescriptor& candidate,
    CompatibilityMode mode);
PDR_SCHEMA_REGISTRY_API SchemaDescriptor parseSchemaDocument(const std::string& document);
PDR_SCHEMA_REGISTRY_API std::string schemaDocument(const SchemaDescriptor& schema);
} // namespace PocoDDS::SchemaRegistry
