#include "PocoDDS/SchemaRegistry/Schema.h"

#include <Poco/DigestEngine.h>
#include <Poco/Exception.h>
#include <Poco/JSON/Array.h>
#include <Poco/JSON/Object.h>
#include <Poco/JSON/Parser.h>
#include <Poco/JSON/Stringifier.h>
#include <Poco/SHA2Engine.h>
#include <Poco/Timestamp.h>

#include <algorithm>
#include <map>
#include <regex>
#include <set>
#include <sstream>
#include <tuple>

namespace PocoDDS::SchemaRegistry
{
namespace
{
using Object = Poco::JSON::Object;
using Array = Poco::JSON::Array;

struct Node
{
    bool anyType{true};
    std::set<std::string> types;
    std::map<std::string, Node> properties;
    std::set<std::string> required;
    bool additionalProperties{true};
    std::optional<std::vector<std::string>> enumValues;
    std::optional<double> minimum;
    std::optional<double> maximum;
    std::optional<int> minLength;
    std::optional<int> maxLength;
    std::shared_ptr<Node> items;
};

std::string jsonValue(const Poco::Dynamic::Var& value)
{
    std::ostringstream stream;
    Poco::JSON::Stringifier::stringify(value, stream);
    return stream.str();
}

void rejectUnsupported(const Object::Ptr& object, const std::string& path)
{
    static const std::set<std::string> unsupported{
        "$ref", "allOf", "anyOf", "oneOf", "not", "if", "then", "else",
        "patternProperties", "dependentSchemas", "unevaluatedProperties",
        "contains", "prefixItems"};
    for (const auto& key : unsupported)
        if (object->has(key))
            throw Poco::DataFormatException(
                "Unsupported JSON Schema keyword at " + path + ": " + key);
}

Node parseNode(const Object::Ptr& object, const std::string& path)
{
    if (!object) throw Poco::DataFormatException("Schema node is not an object at " + path);
    rejectUnsupported(object, path);
    Node node;
    if (object->has("type"))
    {
        node.anyType = false;
        const auto value = object->get("type");
        if (value.isString())
            node.types.insert(value.convert<std::string>());
        else
        {
            const auto types = value.extract<Array::Ptr>();
            if (!types || types->empty())
                throw Poco::DataFormatException("Schema type array is empty at " + path);
            for (std::size_t index = 0; index < types->size(); ++index)
                node.types.insert(types->getElement<std::string>(
                    static_cast<unsigned int>(index)));
        }
    }
    static const std::set<std::string> supportedTypes{
        "null", "boolean", "object", "array", "number", "integer", "string"};
    for (const auto& type : node.types)
        if (!supportedTypes.count(type))
            throw Poco::DataFormatException("Unsupported JSON Schema type at " + path + ": " + type);

    if (object->has("properties"))
    {
        const auto properties = object->getObject("properties");
        if (!properties)
            throw Poco::DataFormatException("properties must be an object at " + path);
        for (const auto& name : properties->getNames())
            node.properties.emplace(name, parseNode(properties->getObject(name), path + "." + name));
    }
    if (object->has("required"))
    {
        const auto required = object->getArray("required");
        if (!required)
            throw Poco::DataFormatException("required must be an array at " + path);
        for (std::size_t index = 0; index < required->size(); ++index)
        {
            const auto name = required->getElement<std::string>(static_cast<unsigned int>(index));
            if (!node.required.insert(name).second)
                throw Poco::DataFormatException("Duplicate required property at " + path + ": " + name);
            if (!node.properties.count(name))
                throw Poco::DataFormatException("Required property is not defined at " + path + ": " + name);
        }
    }
    if (object->has("additionalProperties"))
    {
        const auto value = object->get("additionalProperties");
        if (!value.isBoolean())
            throw Poco::DataFormatException(
                "Only boolean additionalProperties is supported at " + path);
        node.additionalProperties = value.convert<bool>();
    }
    if (object->has("enum"))
    {
        const auto values = object->getArray("enum");
        if (!values || values->empty())
            throw Poco::DataFormatException("enum must be a non-empty array at " + path);
        std::vector<std::string> canonical;
        for (std::size_t index = 0; index < values->size(); ++index)
            canonical.push_back(jsonValue(values->get(static_cast<unsigned int>(index))));
        std::sort(canonical.begin(), canonical.end());
        canonical.erase(std::unique(canonical.begin(), canonical.end()), canonical.end());
        node.enumValues = std::move(canonical);
    }
    if (object->has("minimum")) node.minimum = object->getValue<double>("minimum");
    if (object->has("maximum")) node.maximum = object->getValue<double>("maximum");
    if (node.minimum && node.maximum && *node.minimum > *node.maximum)
        throw Poco::DataFormatException("minimum exceeds maximum at " + path);
    if (object->has("minLength")) node.minLength = object->getValue<int>("minLength");
    if (object->has("maxLength")) node.maxLength = object->getValue<int>("maxLength");
    if ((node.minLength && *node.minLength < 0) || (node.maxLength && *node.maxLength < 0) ||
        (node.minLength && node.maxLength && *node.minLength > *node.maxLength))
        throw Poco::DataFormatException("Invalid string length constraint at " + path);
    if (object->has("items"))
        node.items = std::make_shared<Node>(parseNode(object->getObject("items"), path + "[]"));
    return node;
}

void issue(std::vector<CompatibilityIssue>& issues, const std::string& direction,
           const std::string& path, const std::string& code, const std::string& message)
{
    issues.push_back({direction, path, code, message});
}

void accepts(const Node& reader, const Node& writer, const std::string& path,
             const std::string& direction, std::vector<CompatibilityIssue>& issues)
{
    if (!reader.anyType)
    {
        if (writer.anyType)
            issue(issues, direction, path, "TYPE_NARROWED",
                  "reader restricts a value that the writer may emit");
        else
            for (const auto& type : writer.types)
                if (!reader.types.count(type))
                    issue(issues, direction, path, "TYPE_REMOVED",
                          "reader does not accept writer type '" + type + "'");
    }

    if (reader.enumValues)
    {
        if (!writer.enumValues)
            issue(issues, direction, path, "ENUM_NARROWED",
                  "reader has an enum but writer may emit unrestricted values");
        else
            for (const auto& value : *writer.enumValues)
                if (!std::binary_search(reader.enumValues->begin(), reader.enumValues->end(), value))
                    issue(issues, direction, path, "ENUM_VALUE_REMOVED",
                          "reader does not accept enum value " + value);
    }
    if (reader.minimum && (!writer.minimum || *writer.minimum < *reader.minimum))
        issue(issues, direction, path, "MINIMUM_RAISED",
              "reader minimum rejects values the writer may emit");
    if (reader.maximum && (!writer.maximum || *writer.maximum > *reader.maximum))
        issue(issues, direction, path, "MAXIMUM_LOWERED",
              "reader maximum rejects values the writer may emit");
    if (reader.minLength && (!writer.minLength || *writer.minLength < *reader.minLength))
        issue(issues, direction, path, "MIN_LENGTH_RAISED",
              "reader minimum length rejects values the writer may emit");
    if (reader.maxLength && (!writer.maxLength || *writer.maxLength > *reader.maxLength))
        issue(issues, direction, path, "MAX_LENGTH_LOWERED",
              "reader maximum length rejects values the writer may emit");

    const bool readerObject = reader.anyType || reader.types.count("object");
    const bool writerObject = writer.anyType || writer.types.count("object");
    if (readerObject && writerObject)
    {
        for (const auto& name : reader.required)
            if (!writer.required.count(name) || !writer.properties.count(name))
                issue(issues, direction, path + "." + name, "REQUIRED_NOT_GUARANTEED",
                      "writer does not guarantee a property required by the reader");
        for (const auto& [name, writerProperty] : writer.properties)
        {
            const auto found = reader.properties.find(name);
            if (found != reader.properties.end())
                accepts(found->second, writerProperty, path + "." + name, direction, issues);
            else if (!reader.additionalProperties)
                issue(issues, direction, path + "." + name, "PROPERTY_NOT_ACCEPTED",
                      "reader forbids a property the writer may emit");
        }
        if (writer.additionalProperties && !reader.additionalProperties)
            issue(issues, direction, path, "ADDITIONAL_PROPERTIES_NARROWED",
                  "reader forbids additional properties that the writer permits");
    }

    const bool readerArray = reader.anyType || reader.types.count("array");
    const bool writerArray = writer.anyType || writer.types.count("array");
    if (readerArray && writerArray && reader.items)
    {
        if (!writer.items)
            issue(issues, direction, path + "[]", "ITEMS_NARROWED",
                  "reader restricts array items that the writer leaves unrestricted");
        else
            accepts(*reader.items, *writer.items, path + "[]", direction, issues);
    }
}

std::tuple<int, int, int> semanticVersion(const std::string& value)
{
    static const std::regex pattern(R"(^([0-9]+)\.([0-9]+)\.([0-9]+)$)");
    std::smatch match;
    if (!std::regex_match(value, match, pattern))
        throw Poco::InvalidArgumentException("Schema version must be semantic x.y.z: " + value);
    return {std::stoi(match[1].str()), std::stoi(match[2].str()), std::stoi(match[3].str())};
}
} // namespace

std::string kindName(SchemaKind value)
{
    switch (value)
    {
    case SchemaKind::message: return "message";
    case SchemaKind::event: return "event";
    case SchemaKind::command: return "command";
    case SchemaKind::configuration: return "configuration";
    case SchemaKind::service: return "service";
    }
    throw Poco::InvalidArgumentException("Unknown schema kind");
}

SchemaKind parseKind(const std::string& value)
{
    if (value == "message") return SchemaKind::message;
    if (value == "event") return SchemaKind::event;
    if (value == "command") return SchemaKind::command;
    if (value == "configuration") return SchemaKind::configuration;
    if (value == "service") return SchemaKind::service;
    throw Poco::InvalidArgumentException("Unknown schema kind: " + value);
}

std::string compatibilityName(CompatibilityMode value)
{
    switch (value)
    {
    case CompatibilityMode::none: return "none";
    case CompatibilityMode::backward: return "backward";
    case CompatibilityMode::forward: return "forward";
    case CompatibilityMode::full: return "full";
    }
    throw Poco::InvalidArgumentException("Unknown compatibility mode");
}

CompatibilityMode parseCompatibility(const std::string& value)
{
    if (value == "none") return CompatibilityMode::none;
    if (value == "backward") return CompatibilityMode::backward;
    if (value == "forward") return CompatibilityMode::forward;
    if (value == "full") return CompatibilityMode::full;
    throw Poco::InvalidArgumentException("Unknown compatibility mode: " + value);
}

int compareSemanticVersion(const std::string& left, const std::string& right)
{
    const auto a = semanticVersion(left);
    const auto b = semanticVersion(right);
    return a < b ? -1 : (a > b ? 1 : 0);
}

std::string canonicalDefinition(const std::string& definition)
{
    const auto root = Poco::JSON::Parser().parse(definition).extract<Object::Ptr>();
    if (!root) throw Poco::DataFormatException("Schema definition root must be an object");
    parseNode(root, "$");
    std::ostringstream stream;
    root->stringify(stream);
    return stream.str();
}

std::string schemaFingerprint(const SchemaDescriptor& schema)
{
    Poco::SHA2Engine engine(Poco::SHA2Engine::SHA_256);
    const std::string value = schema.subject + "\n" + schema.version + "\n" +
        kindName(schema.kind) + "\n" + schema.format + "\n" +
        compatibilityName(schema.compatibility) + "\n" + schema.owner + "\n" +
        schema.definition;
    engine.update(value);
    return Poco::DigestEngine::digestToHex(engine.digest());
}

SchemaDescriptor normalizeSchema(SchemaDescriptor schema)
{
    static const std::regex subjectPattern(R"(^[A-Za-z][A-Za-z0-9_.-]{2,127}$)");
    static const std::regex ownerPattern(R"(^[A-Za-z][A-Za-z0-9_.-]{2,127}$)");
    if (!std::regex_match(schema.subject, subjectPattern))
        throw Poco::InvalidArgumentException("Invalid schema subject: " + schema.subject);
    semanticVersion(schema.version);
    if (!std::regex_match(schema.owner, ownerPattern))
        throw Poco::InvalidArgumentException("Invalid schema owner: " + schema.owner);
    if (schema.format != "json-schema-draft-07")
        throw Poco::InvalidArgumentException("Unsupported schema format: " + schema.format);
    schema.definition = canonicalDefinition(schema.definition);
    const auto fingerprint = schemaFingerprint(schema);
    if (!schema.fingerprint.empty() && schema.fingerprint != fingerprint)
        throw Poco::DataFormatException("Schema fingerprint mismatch for " + schema.subject);
    schema.fingerprint = fingerprint;
    if (schema.registeredMicroseconds == 0)
        schema.registeredMicroseconds = Poco::Timestamp().epochMicroseconds();
    return schema;
}

CompatibilityReport checkCompatibility(const SchemaDescriptor& previous,
                                       const SchemaDescriptor& candidate,
                                       CompatibilityMode mode)
{
    CompatibilityReport report;
    report.mode = mode;
    if (previous.subject != candidate.subject)
        issue(report.issues, "metadata", "$", "SUBJECT_CHANGED", "schema subject changed");
    if (previous.kind != candidate.kind)
        issue(report.issues, "metadata", "$", "KIND_CHANGED", "schema kind changed");
    if (previous.format != candidate.format)
        issue(report.issues, "metadata", "$", "FORMAT_CHANGED", "schema format changed");
    const auto oldRoot = Poco::JSON::Parser().parse(previous.definition).extract<Object::Ptr>();
    const auto newRoot = Poco::JSON::Parser().parse(candidate.definition).extract<Object::Ptr>();
    const auto oldNode = parseNode(oldRoot, "$");
    const auto newNode = parseNode(newRoot, "$");
    if (mode == CompatibilityMode::backward || mode == CompatibilityMode::full)
        accepts(newNode, oldNode, "$", "backward", report.issues);
    if (mode == CompatibilityMode::forward || mode == CompatibilityMode::full)
        accepts(oldNode, newNode, "$", "forward", report.issues);
    report.compatible = report.issues.empty();
    return report;
}

SchemaDescriptor parseSchemaDocument(const std::string& document)
{
    const auto root = Poco::JSON::Parser().parse(document).extract<Object::Ptr>();
    if (!root || root->getValue<int>("schemaVersion") != 1)
        throw Poco::DataFormatException("Unsupported schema contract document");
    const auto definition = root->getObject("definition");
    if (!definition) throw Poco::DataFormatException("Schema contract definition is missing");
    std::ostringstream stream;
    definition->stringify(stream);
    SchemaDescriptor schema;
    schema.subject = root->getValue<std::string>("subject");
    schema.version = root->getValue<std::string>("version");
    schema.kind = parseKind(root->getValue<std::string>("kind"));
    schema.format = root->optValue<std::string>("format", "json-schema-draft-07");
    schema.compatibility = parseCompatibility(
        root->optValue<std::string>("compatibility", "backward"));
    schema.owner = root->getValue<std::string>("owner");
    schema.definition = stream.str();
    schema.fingerprint = root->optValue<std::string>("fingerprint", "");
    schema.deprecated = root->optValue<bool>("deprecated", false);
    return normalizeSchema(std::move(schema));
}

std::string schemaDocument(const SchemaDescriptor& input)
{
    const auto schema = normalizeSchema(input);
    Object root;
    root.set("schemaVersion", 1);
    root.set("subject", schema.subject);
    root.set("version", schema.version);
    root.set("kind", kindName(schema.kind));
    root.set("format", schema.format);
    root.set("compatibility", compatibilityName(schema.compatibility));
    root.set("owner", schema.owner);
    root.set("fingerprint", schema.fingerprint);
    root.set("deprecated", schema.deprecated);
    root.set("definition", Poco::JSON::Parser().parse(schema.definition));
    std::ostringstream stream;
    root.stringify(stream, 0, 2);
    stream << '\n';
    return stream.str();
}
} // namespace PocoDDS::SchemaRegistry
