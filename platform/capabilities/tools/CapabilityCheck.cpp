#include "PocoDDS/Capabilities/PolicyEngine.h"

#include <Poco/Exception.h>
#include <Poco/JSON/Object.h>
#include <Poco/JSON/Stringifier.h>

#include <iostream>
#include <map>
#include <sstream>
#include <string>

namespace
{
std::map<std::string, std::string> arguments(int argc, char** argv)
{
    std::map<std::string, std::string> result;
    for (int index = 1; index < argc; ++index)
    {
        const std::string name = argv[index];
        if (name == "--validate")
        {
            result[name] = "true";
            continue;
        }
        if (name.rfind("--", 0) != 0 || index + 1 >= argc)
            throw Poco::InvalidArgumentException("Invalid command line argument", name);
        result[name] = argv[++index];
    }
    return result;
}

std::string required(const std::map<std::string, std::string>& values, const std::string& name)
{
    const auto found = values.find(name);
    if (found == values.end() || found->second.empty())
        throw Poco::InvalidArgumentException("Missing command line argument", name);
    return found->second;
}

void print(const Poco::JSON::Object& object)
{
    Poco::JSON::Stringifier::stringify(object, std::cout);
    std::cout << '\n';
}
} // namespace

int main(int argc, char** argv)
{
    try
    {
        const auto values = arguments(argc, argv);
        const auto rules = PocoDDS::Capabilities::loadPolicyFile(required(values, "--policy"));
        PocoDDS::Capabilities::PolicyEngine engine(rules);
        if (values.count("--validate") != 0)
        {
            const auto snapshot = engine.snapshot();
            Poco::JSON::Object output;
            output.set("valid", true);
            output.set("defaultEffect", "deny");
            output.set("ruleCount", static_cast<Poco::UInt64>(snapshot.ruleCount));
            output.set("digest", snapshot.digest);
            print(output);
            return 0;
        }

        const PocoDDS::Capabilities::Request request{
            required(values, "--principal"),
            PocoDDS::Capabilities::parseResourceKind(required(values, "--resource-kind")),
            required(values, "--resource"),
            PocoDDS::Capabilities::parseAction(required(values, "--action"))};
        const auto decision = engine.decide(request);
        Poco::JSON::Object output;
        output.set("allowed", decision.allowed);
        output.set("code", decision.code);
        output.set("matchedRuleId", decision.matchedRuleId);
        output.set("explanation", decision.explanation);
        output.set("policyGeneration", decision.policyGeneration);
        output.set("policyDigest", decision.policyDigest);
        print(output);
        return decision.allowed ? 0 : 3;
    }
    catch (const Poco::Exception& exception)
    {
        Poco::JSON::Object output;
        output.set("valid", false);
        output.set("error", exception.displayText());
        print(output);
        return 2;
    }
    catch (const std::exception& exception)
    {
        Poco::JSON::Object output;
        output.set("valid", false);
        output.set("error", exception.what());
        print(output);
        return 2;
    }
}

