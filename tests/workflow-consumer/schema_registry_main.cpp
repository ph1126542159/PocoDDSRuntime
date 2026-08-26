#include <PocoDDS/SchemaRegistry/Registry.h>
#include <PocoDDS/SchemaRegistry/SchemaProviderService.h>
#include <PocoDDS/SchemaRegistry/SqliteSchemaStore.h>

#include <Poco/File.h>
#include <Poco/TemporaryFile.h>

#include <iostream>
#include <memory>

int main()
{
    using namespace PocoDDS::SchemaRegistry;
    const std::string database = Poco::TemporaryFile::tempName() + ".sqlite";
    {
        Registry registry(std::make_shared<SqliteSchemaStore>(database));
        registry.initialize();
        SchemaDescriptor schema{
            "external.consumer.event", "1.0.0", SchemaKind::event,
            "json-schema-draft-07", CompatibilityMode::backward,
            "external.consumer",
            R"({"type":"object","required":["id"],"properties":{"id":{"type":"string"}}})"};
        const auto result = registry.registerSchema(std::move(schema));
        if (!result.accepted || result.schema.fingerprint.empty()) return 1;
        const auto found = registry.latest("external.consumer.event");
        if (!found || found->version != "1.0.0") return 2;
        static_cast<void>(SchemaProviderService::PROPERTY_KIND);
    }
    for (const auto& suffix : {std::string(), std::string("-wal"), std::string("-shm")})
        try { Poco::File(database + suffix).remove(); } catch (...) {}
    std::cout << "PDR_SCHEMA_REGISTRY_EXTERNAL_PASS\n";
    return 0;
}
