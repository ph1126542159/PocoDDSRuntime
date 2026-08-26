#include "PocoDDS/Capabilities/SqlitePolicyStore.h"

#include <Poco/Exception.h>
#include <Poco/JSON/Object.h>
#include <Poco/JSON/Stringifier.h>

#include <iostream>
#include <map>
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
        PocoDDS::Capabilities::SqlitePolicyStore store(
            required(values, "--database"));
        const auto state = store.initialize(seed);
        store.verifyIntegrity();
        const auto persistence = store.snapshot();
        Poco::JSON::Object result;
        result.set("healthy", persistence.healthy);
        result.set("recoveryRequired", persistence.recoveryRequired);
        result.set("database", persistence.databasePath);
        result.set("generation", persistence.generation);
        result.set("digest", persistence.digest);
        result.set("ruleCount", static_cast<Poco::UInt64>(state.snapshot.ruleCount));
        result.set("auditRecords", persistence.auditRecords);
        result.set("requestRecords", persistence.requestRecords);
        result.set("sourceDrift", state.snapshot.digest !=
                                      PocoDDS::Capabilities::policyDigest(seed));
        output(result);
        return persistence.healthy && !persistence.recoveryRequired ? 0 : 3;
    }
    catch (const Poco::Exception& exception)
    {
        Poco::JSON::Object result;
        result.set("healthy", false);
        result.set("recoveryRequired", true);
        result.set("error", exception.displayText());
        output(result);
        return 2;
    }
    catch (const std::exception& exception)
    {
        Poco::JSON::Object result;
        result.set("healthy", false);
        result.set("recoveryRequired", true);
        result.set("error", exception.what());
        output(result);
        return 2;
    }
}
