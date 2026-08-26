#include "PocoDDS/Capabilities/PolicyEngine.h"
#include "PocoDDS/Capabilities/CapabilityRuntimeService.h"
#include "PocoDDS/Capabilities/SqlitePolicyStore.h"

#include <Poco/Exception.h>
#include <Poco/JSON/Object.h>
#include <Poco/JSON/Stringifier.h>

#include <iostream>
#include <map>
#include <memory>
#include <string>

namespace
{
std::map<std::string, std::string> arguments(int argc, char** argv)
{
    std::map<std::string, std::string> result;
    for (int index = 1; index < argc; ++index)
    {
        const std::string name = argv[index];
        if (name.rfind("--", 0) != 0 || index + 1 >= argc)
            throw Poco::InvalidArgumentException("Invalid command line argument", name);
        result[name] = argv[++index];
    }
    return result;
}

std::string required(const std::map<std::string, std::string>& values,
                     const std::string& name)
{
    const auto found = values.find(name);
    if (found == values.end() || found->second.empty())
        throw Poco::InvalidArgumentException("Missing command line argument", name);
    return found->second;
}

void output(const Poco::JSON::Object& value)
{
    Poco::JSON::Stringifier::stringify(value, std::cout);
    std::cout << '\n';
}
} // namespace

int main(int argc, char** argv)
{
    try
    {
        const auto values = arguments(argc, argv);
        const auto seed = PocoDDS::Capabilities::loadPolicyFile(
            required(values, "--seed-policy"));
        const auto candidate = PocoDDS::Capabilities::loadPolicyFile(
            required(values, "--candidate-policy"));
        auto store = std::make_shared<PocoDDS::Capabilities::SqlitePolicyStore>(
            required(values, "--database"));
        const auto current = store->initialize(seed);
        const auto actor = required(values, "--actor");
        PocoDDS::Capabilities::PolicyEngine engine(
            current.rules, current.snapshot.generation, 32,
            [store](const PocoDDS::Capabilities::AuditRecord& record) {
                store->appendAudit(record);
            });
        engine.require({actor, PocoDDS::Capabilities::ResourceKind::service,
                        PocoDDS::Capabilities::CapabilityRuntimeService::SERVICE_NAME,
                        PocoDDS::Capabilities::Action::use});
        const auto expected = static_cast<Poco::UInt64>(
            std::stoull(required(values, "--expected-generation")));
        const auto result = store->replace({required(values, "--request-id"), actor,
                                            expected, candidate});
        Poco::JSON::Object response;
        response.set("committed", true);
        response.set("idempotentReplay", result.idempotentReplay);
        response.set("generation", result.snapshot.generation);
        response.set("digest", result.snapshot.digest);
        response.set("ruleCount", static_cast<Poco::UInt64>(result.snapshot.ruleCount));
        response.set("database", store->snapshot().databasePath);
        output(response);
        return 0;
    }
    catch (const Poco::Exception& exception)
    {
        Poco::JSON::Object response;
        response.set("committed", false);
        response.set("error", exception.displayText());
        output(response);
        return 2;
    }
    catch (const std::exception& exception)
    {
        Poco::JSON::Object response;
        response.set("committed", false);
        response.set("error", exception.what());
        output(response);
        return 2;
    }
}
