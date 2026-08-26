#include "PocoDDS/SchemaRegistry/Schema.h"

#include <Poco/Exception.h>
#include <Poco/JSON/Array.h>
#include <Poco/JSON/Object.h>
#include <Poco/JSON/Parser.h>
#include <Poco/Path.h>

#include <fstream>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

namespace Schema = PocoDDS::SchemaRegistry;

namespace
{
std::string readFile(const std::string& path)
{
    std::ifstream stream(path, std::ios::binary);
    if (!stream) throw Poco::OpenFileException(path);
    std::ostringstream value;
    value << stream.rdbuf();
    return value.str();
}

int major(const std::string& version)
{
    return std::stoi(version.substr(0, version.find('.')));
}

bool checkPair(const std::string& baselinePath, const std::string& candidatePath,
               const std::string& modeOverride)
{
    const auto baseline = Schema::parseSchemaDocument(readFile(baselinePath));
    const auto candidate = Schema::parseSchemaDocument(readFile(candidatePath));
    if (baseline.subject != candidate.subject || baseline.owner != candidate.owner ||
        baseline.kind != candidate.kind || baseline.format != candidate.format)
    {
        std::cerr << "SCHEMA_COMPATIBILITY_ERROR: immutable identity changed for "
                  << baseline.subject << '\n';
        return false;
    }
    if (baseline.compatibility != candidate.compatibility)
    {
        std::cerr << "SCHEMA_COMPATIBILITY_ERROR: compatibility policy changed for "
                  << baseline.subject << '\n';
        return false;
    }
    const int ordering = Schema::compareSemanticVersion(candidate.version, baseline.version);
    if (ordering < 0)
    {
        std::cerr << "SCHEMA_COMPATIBILITY_ERROR: candidate version is older for "
                  << baseline.subject << '\n';
        return false;
    }
    if (ordering == 0 && candidate.fingerprint != baseline.fingerprint)
    {
        std::cerr << "SCHEMA_COMPATIBILITY_ERROR: definition changed without a version bump for "
                  << baseline.subject << '\n';
        return false;
    }
    const auto mode = modeOverride.empty() ? candidate.compatibility :
                                             Schema::parseCompatibility(modeOverride);
    const auto report = Schema::checkCompatibility(baseline, candidate, mode);
    if (!report.compatible && major(candidate.version) <= major(baseline.version))
    {
        for (const auto& issue : report.issues)
            std::cerr << "SCHEMA_COMPATIBILITY_ERROR: " << baseline.subject << ' '
                      << issue.direction << ' ' << issue.path << ' ' << issue.code
                      << ": " << issue.message << '\n';
        std::cerr << "SCHEMA_COMPATIBILITY_ERROR: breaking changes require a higher major version\n";
        return false;
    }
    std::cout << "SCHEMA_COMPATIBILITY_PASS subject=" << candidate.subject
              << " baseline=" << baseline.version << " candidate=" << candidate.version;
    if (!report.compatible) std::cout << " breaking-major=true";
    std::cout << '\n';
    return true;
}

bool checkCatalog(const std::string& catalogPath)
{
    const auto root = Poco::JSON::Parser().parse(readFile(catalogPath))
                          .extract<Poco::JSON::Object::Ptr>();
    if (!root || root->getValue<int>("schemaVersion") != 1)
        throw Poco::DataFormatException("Unsupported schema compatibility catalog");
    const auto entries = root->getArray("entries");
    if (!entries || entries->empty())
        throw Poco::DataFormatException("Schema compatibility catalog is empty");
    Poco::Path base(catalogPath);
    base.makeParent();
    bool passed = true;
    for (std::size_t index = 0; index < entries->size(); ++index)
    {
        const auto entry = entries->getObject(static_cast<unsigned int>(index));
        if (!entry) throw Poco::DataFormatException("Schema catalog entry is not an object");
        Poco::Path baseline(base, entry->getValue<std::string>("baseline"));
        Poco::Path candidate(base, entry->getValue<std::string>("candidate"));
        passed = checkPair(baseline.toString(), candidate.toString(),
                           entry->optValue<std::string>("mode", "")) && passed;
    }
    return passed;
}
} // namespace

int main(int argc, char** argv)
{
    try
    {
        std::string baseline;
        std::string candidate;
        std::string catalog;
        std::string mode;
        for (int index = 1; index < argc; ++index)
        {
            const std::string argument = argv[index];
            auto value = [&](const std::string& name) {
                if (++index >= argc) throw Poco::InvalidArgumentException(name + " requires a value");
                return std::string(argv[index]);
            };
            if (argument == "--baseline") baseline = value(argument);
            else if (argument == "--candidate") candidate = value(argument);
            else if (argument == "--catalog") catalog = value(argument);
            else if (argument == "--mode") mode = value(argument);
            else throw Poco::InvalidArgumentException("Unknown argument: " + argument);
        }
        bool passed = false;
        if (!catalog.empty())
        {
            if (!baseline.empty() || !candidate.empty())
                throw Poco::InvalidArgumentException("--catalog cannot be combined with pair arguments");
            passed = checkCatalog(catalog);
        }
        else
        {
            if (baseline.empty() || candidate.empty())
                throw Poco::InvalidArgumentException("--baseline and --candidate are required");
            passed = checkPair(baseline, candidate, mode);
        }
        return passed ? 0 : 1;
    }
    catch (const Poco::Exception& exception)
    {
        std::cerr << "SCHEMA_CHECK_ERROR: " << exception.displayText() << '\n';
    }
    catch (const std::exception& exception)
    {
        std::cerr << "SCHEMA_CHECK_ERROR: " << exception.what() << '\n';
    }
    return 2;
}
