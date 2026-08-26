#include "PocoDDS/SchemaRegistry/Registry.h"
#include "PocoDDS/SchemaRegistry/SqliteSchemaStore.h"

#include <Poco/File.h>
#include <Poco/TemporaryFile.h>

#include <future>
#include <iostream>
#include <memory>
#include <string>
#include <vector>

namespace
{
using namespace PocoDDS::SchemaRegistry;

std::string definition(bool optionalUnit, bool requireUnit, bool identifierInteger = false)
{
    std::string properties =
        std::string(R"("id":{"type":")") + (identifierInteger ? "integer" : "string") +
        R"("},"value":{"type":"number","minimum":0})";
    if (optionalUnit) properties += R"(,"unit":{"type":"string"})";
    std::string required = R"("id","value")";
    if (requireUnit) required += R"(,"unit")";
    return R"({"type":"object","additionalProperties":false,"required":[)" +
        required + R"(],"properties":{)" + properties + "}}";
}

SchemaDescriptor schema(std::string version, std::string value,
                        CompatibilityMode mode = CompatibilityMode::backward)
{
    return {"pdr.test.telemetry", std::move(version), SchemaKind::event,
            "json-schema-draft-07", mode, "pdr.test.provider", std::move(value)};
}

void removeDatabase(const std::string& path)
{
    for (const auto& suffix : {std::string(), std::string("-wal"), std::string("-shm")})
    {
        Poco::File file(path + suffix);
        if (file.exists()) file.remove();
    }
}
} // namespace

int main()
{
    using namespace PocoDDS::SchemaRegistry;
    const std::string path = Poco::TemporaryFile::tempName() + ".sqlite";
    try
    {
        {
            auto store = std::make_shared<SqliteSchemaStore>(path);
            Registry registry(store);
            registry.initialize();

            const auto first = registry.registerSchema(schema("1.0.0", definition(false, false)));
            if (!first.accepted || first.idempotent || first.schema.fingerprint.empty()) return 1;

            auto same = schema("1.0.0", "  " + definition(false, false) + "  ");
            const auto replay = registry.registerSchema(std::move(same));
            if (!replay.accepted || !replay.idempotent) return 2;

            const auto conflict = registry.registerSchema(
                schema("1.0.0", definition(true, false)));
            if (conflict.accepted || conflict.code != "SCHEMA_VERSION_CONFLICT") return 3;

            const auto compatible = registry.registerSchema(
                schema("1.1.0", definition(true, false)));
            if (!compatible.accepted || !compatible.compatibility.compatible) return 4;

            std::vector<std::future<RegistrationResult>> concurrent;
            for (int index = 0; index < 8; ++index)
                concurrent.push_back(std::async(std::launch::async, [&] {
                    return registry.registerSchema(schema("1.2.0", definition(true, false)));
                }));
            int inserted = 0;
            int idempotent = 0;
            for (auto& result : concurrent)
            {
                const auto value = result.get();
                if (!value.accepted) return 5;
                value.idempotent ? ++idempotent : ++inserted;
            }
            if (inserted != 1 || idempotent != 7) return 6;

            const auto rejectedBatch = registry.registerSchemas({
                schema("1.2.1", definition(true, false)),
                schema("1.2.1", definition(true, true))});
            if (rejectedBatch.accepted ||
                registry.find("pdr.test.telemetry", "1.2.1")) return 16;

            const auto breakingMinor = registry.registerSchema(
                schema("1.3.0", definition(true, true)));
            if (breakingMinor.accepted || breakingMinor.code != "SCHEMA_INCOMPATIBLE" ||
                breakingMinor.compatibility.issues.empty()) return 7;

            const auto breakingMajor = registry.registerSchema(
                schema("2.0.0", definition(true, true)));
            if (!breakingMajor.accepted || breakingMajor.compatibility.compatible ||
                breakingMajor.code != "SCHEMA_BREAKING_MAJOR_REGISTERED") return 8;

            auto wrongOwner = schema("2.1.0", definition(true, true));
            wrongOwner.owner = "pdr.other.provider";
            if (registry.registerSchema(std::move(wrongOwner)).code != "SCHEMA_IDENTITY_CHANGED")
                return 9;

            if (!registry.deprecate("pdr.test.telemetry", "1.0.0")) return 10;
            const auto old = registry.find("pdr.test.telemetry", "1.0.0");
            if (!old || !old->deprecated) return 11;
        }

        {
            auto store = std::make_shared<SqliteSchemaStore>(path);
            Registry recovered(store);
            recovered.initialize();
            const auto all = recovered.schemas();
            if (all.size() != 4) return 12;
            const auto latest = recovered.latest("pdr.test.telemetry");
            if (!latest || latest->version != "2.0.0") return 13;
            if (!recovered.registerSchema(schema("2.0.0", definition(true, true))).idempotent)
                return 14;
        }

        const auto oldSchema = normalizeSchema(schema("1.0.0", definition(false, false),
                                                       CompatibilityMode::full));
        const auto typeChange = normalizeSchema(schema("2.0.0", definition(false, false, true),
                                                        CompatibilityMode::full));
        const auto full = checkCompatibility(oldSchema, typeChange, CompatibilityMode::full);
        if (full.compatible || full.issues.empty()) return 15;

        removeDatabase(path);
        std::cout << "SCHEMA_REGISTRY_SMOKE_PASS\n";
        return 0;
    }
    catch (const std::exception& exception)
    {
        removeDatabase(path);
        std::cerr << exception.what() << '\n';
        return 100;
    }
}
