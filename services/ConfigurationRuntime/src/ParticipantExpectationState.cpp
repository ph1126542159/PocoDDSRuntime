#include "ParticipantExpectationState.h"

#include <Poco/Exception.h>
#include <Poco/JSON/Array.h>
#include <Poco/JSON/Object.h>
#include <Poco/JSON/Parser.h>

#include <algorithm>
#include <cctype>
#include <map>
#include <set>
#include <tuple>
#include <utility>

namespace PocoDDS::ConfigTransaction
{
namespace
{
struct Declaration
{
    std::string owner;
    bool ownerActive{false};
    std::string id;
    std::string serviceName;
    std::vector<std::string> ownedPrefixes;
    std::vector<std::string> after;
};

bool validId(const std::string& value)
{
    return !value.empty() && value.size() <= 128 &&
           std::islower(static_cast<unsigned char>(value.front())) &&
           std::all_of(value.begin(), value.end(), [](unsigned char character) {
               return std::islower(character) || std::isdigit(character) ||
                      character == '-' || character == '.';
           });
}

bool validServiceName(const std::string& value)
{
    return !value.empty() && value.size() <= 192 &&
           std::all_of(value.begin(), value.end(), [](unsigned char character) {
               return std::isalnum(character) || character == '-' ||
                      character == '_' || character == '.' || character == ':';
           });
}

bool validPrefix(const std::string& value)
{
    return !value.empty() && value.size() <= 192 && value.front() != '.' &&
           value.back() != '.' &&
           std::all_of(value.begin(), value.end(), [](unsigned char character) {
               return std::isalnum(character) || character == '-' ||
                      character == '_' || character == '.';
           });
}

bool owns(const std::string& prefix, const std::string& key)
{
    return key == prefix ||
           (key.size() > prefix.size() &&
            key.compare(0, prefix.size(), prefix) == 0 &&
            key[prefix.size()] == '.');
}

bool overlaps(const std::string& left, const std::string& right)
{
    return owns(left, right) || owns(right, left);
}

void requireKnownFields(const Poco::JSON::Object::Ptr& object,
                        const std::set<std::string>& allowed,
                        const std::string& location)
{
    for (const auto& name : object->getNames())
        if (allowed.count(name) == 0)
            throw Poco::InvalidArgumentException(
                location + " contains unknown field", name);
}

std::vector<std::string> stringArray(const Poco::JSON::Object::Ptr& object,
                                     const std::string& name,
                                     bool requireNonEmpty)
{
    const auto array = object->getArray(name);
    if (!array || array->size() > 64 || (requireNonEmpty && array->size() == 0))
        throw Poco::InvalidArgumentException(
            name + " must be an array with a valid item count");
    std::vector<std::string> result;
    result.reserve(array->size());
    for (std::size_t index = 0; index < array->size(); ++index)
    {
        const auto value = array->get(static_cast<unsigned>(index));
        if (!value.isString())
            throw Poco::InvalidArgumentException(name + " entries must be strings");
        result.push_back(value.convert<std::string>());
    }
    std::sort(result.begin(), result.end());
    if (std::adjacent_find(result.begin(), result.end()) != result.end())
        throw Poco::InvalidArgumentException(name + " contains duplicate entries");
    return result;
}

std::vector<Declaration> parse(const ParticipantDeclarationDocument& document)
{
    if (document.owner.empty() || document.owner.size() > 192)
        throw Poco::InvalidArgumentException("invalid declaration owner");
    if (document.json.size() > ParticipantExpectationState::MAXIMUM_DOCUMENT_BYTES)
        throw Poco::RangeException("participant declaration exceeds 64 KiB");
    const auto root = Poco::JSON::Parser().parse(document.json)
                          .extract<Poco::JSON::Object::Ptr>();
    if (!root || root->optValue<int>("schemaVersion", 0) != 1)
        throw Poco::InvalidArgumentException("schemaVersion must equal 1");
    requireKnownFields(root, {"schemaVersion", "participants"},
                       "participant declaration document");
    const auto participants = root->getArray("participants");
    if (!participants || participants->size() > 128)
        throw Poco::InvalidArgumentException(
            "participants must be an array with at most 128 entries");

    std::vector<Declaration> result;
    std::set<std::string> ids;
    std::set<std::string> services;
    for (std::size_t index = 0; index < participants->size(); ++index)
    {
        const auto item = participants->getObject(static_cast<unsigned>(index));
        if (!item)
            throw Poco::InvalidArgumentException(
                "participant declaration entry must be an object");
        requireKnownFields(item, {"id", "serviceName", "ownedPrefixes", "after"},
                           "participant declaration entry");
        Declaration declaration;
        declaration.owner = document.owner;
        declaration.ownerActive = document.ownerActive;
        declaration.id = item->optValue<std::string>("id", "");
        declaration.serviceName = item->optValue<std::string>("serviceName", "");
        declaration.ownedPrefixes = stringArray(item, "ownedPrefixes", true);
        declaration.after = stringArray(item, "after", false);
        if (!validId(declaration.id) || !validServiceName(declaration.serviceName))
            throw Poco::InvalidArgumentException(
                "participant id or serviceName is invalid");
        if (!std::all_of(declaration.ownedPrefixes.begin(),
                         declaration.ownedPrefixes.end(), validPrefix) ||
            !std::all_of(declaration.after.begin(), declaration.after.end(), validId))
            throw Poco::InvalidArgumentException(
                "participant ownedPrefixes or after is invalid");
        if (std::find(declaration.after.begin(), declaration.after.end(),
                      declaration.id) != declaration.after.end())
            throw Poco::InvalidArgumentException(
                "participant declaration depends on itself");
        for (std::size_t left = 0;
             left < declaration.ownedPrefixes.size(); ++left)
            for (std::size_t right = left + 1;
                 right < declaration.ownedPrefixes.size(); ++right)
                if (overlaps(declaration.ownedPrefixes[left],
                             declaration.ownedPrefixes[right]))
                    throw Poco::InvalidArgumentException(
                        "participant declaration prefixes overlap");
        if (!ids.insert(declaration.id).second ||
            !services.insert(declaration.serviceName).second)
            throw Poco::InvalidArgumentException(
                "participant id or serviceName is duplicated within Bundle");
        result.push_back(std::move(declaration));
    }
    return result;
}

std::string signature(const ConfigurationParticipantExpectationSnapshot& value)
{
    std::string result = value.ready ? "1" : "0";
    for (const auto& expectation : value.expectations)
        result += "|" + expectation.owner + "|" + expectation.id + "|" +
                  expectation.serviceName + "|" +
                  (expectation.ownerActive ? "1" : "0") + "|" +
                  expectation.status + "|" + expectation.code;
    for (const auto& issue : value.issues)
        result += "|!" + issue.owner + "|" + issue.code;
    return result;
}
} // namespace

void ParticipantExpectationState::replace(
    const std::vector<ParticipantDeclarationDocument>& documents,
    const ConfigurationParticipantCatalogSnapshot& catalog,
    const std::vector<AdmittedParticipantObservation>& observations)
{
    ConfigurationParticipantExpectationSnapshot next;
    std::vector<Declaration> declarations;
    std::set<std::string> globalIds;
    std::set<std::string> globalServices;
    std::vector<std::pair<std::string, std::string>> globalPrefixes;
    for (const auto& document : documents)
    {
        try
        {
            auto parsed = parse(document);
            if (declarations.size() + parsed.size() > MAXIMUM_DECLARATIONS)
                throw Poco::RangeException(
                    "participant declarations exceed global capacity");
            auto nextIds = globalIds;
            auto nextServices = globalServices;
            auto nextPrefixes = globalPrefixes;
            for (const auto& declaration : parsed)
            {
                if (!nextIds.insert(declaration.id).second ||
                    !nextServices.insert(declaration.serviceName).second)
                    throw Poco::ExistsException(
                        "participant declaration conflicts across Bundles");
                for (const auto& prefix : declaration.ownedPrefixes)
                {
                    if (std::any_of(
                            nextPrefixes.begin(), nextPrefixes.end(),
                            [&](const auto& registered) {
                                return overlaps(prefix, registered.first);
                            }))
                        throw Poco::ExistsException(
                            "participant ownership declaration conflicts across Bundles");
                    nextPrefixes.emplace_back(prefix, declaration.owner);
                }
            }
            globalIds = std::move(nextIds);
            globalServices = std::move(nextServices);
            globalPrefixes = std::move(nextPrefixes);
            declarations.insert(declarations.end(),
                                std::make_move_iterator(parsed.begin()),
                                std::make_move_iterator(parsed.end()));
        }
        catch (const std::exception&)
        {
            next.issues.push_back(
                {document.owner, "participant-declaration-invalid"});
        }
    }

    std::map<std::string, std::vector<std::string>> dependencyGraph;
    std::map<std::string, std::string> owners;
    for (const auto& declaration : declarations)
    {
        dependencyGraph[declaration.id] = declaration.after;
        owners[declaration.id] = declaration.owner;
    }
    std::map<std::string, int> colors;
    std::set<std::string> cycleOwners;
    std::vector<std::string> dependencyStack;
    const auto visit = [&](const auto& self, const std::string& id) -> void {
        if (colors[id] == 2) return;
        colors[id] = 1;
        dependencyStack.push_back(id);
        for (const auto& dependency : dependencyGraph[id])
        {
            if (dependencyGraph.count(dependency) == 0) continue;
            if (colors[dependency] == 1)
            {
                const auto cycleBegin = std::find(
                    dependencyStack.begin(), dependencyStack.end(), dependency);
                for (auto it = cycleBegin; it != dependencyStack.end(); ++it)
                    cycleOwners.insert(owners[*it]);
            }
            else if (colors[dependency] == 0)
                self(self, dependency);
        }
        dependencyStack.pop_back();
        colors[id] = 2;
    };
    for (const auto& [id, dependencies] : dependencyGraph)
    {
        static_cast<void>(dependencies);
        if (colors[id] == 0) visit(visit, id);
    }
    for (const auto& owner : cycleOwners)
        next.issues.push_back({owner, "participant-declaration-invalid"});

    std::map<std::string, ConfigurationParticipantCatalogEntry> admitted;
    for (const auto& entry : catalog.participants) admitted.emplace(entry.id, entry);
    std::map<std::string, AdmittedParticipantObservation> observed;
    for (const auto& observation : observations)
        observed.emplace(observation.id, observation);

    for (const auto& declaration : declarations)
    {
        ConfigurationParticipantExpectation expectation;
        expectation.owner = declaration.owner;
        expectation.id = declaration.id;
        expectation.serviceName = declaration.serviceName;
        expectation.ownerActive = declaration.ownerActive;
        if (!declaration.ownerActive)
        {
            expectation.status = "inactive";
            expectation.code = "";
        }
        else
        {
            const auto catalogEntry = admitted.find(declaration.id);
            const auto observation = observed.find(declaration.id);
            if (catalogEntry == admitted.end() || observation == observed.end())
            {
                expectation.status = "missing";
                expectation.code = "participant-required-missing";
                next.ready = false;
            }
            else if (observation->second.owner != declaration.owner ||
                     observation->second.serviceName != declaration.serviceName ||
                     catalogEntry->second.ownedPrefixes != declaration.ownedPrefixes ||
                     catalogEntry->second.after != declaration.after)
            {
                expectation.status = "mismatched";
                expectation.code = "participant-declaration-mismatch";
                next.ready = false;
            }
            else
            {
                expectation.status = "satisfied";
                expectation.code = "";
            }
        }
        next.expectations.push_back(std::move(expectation));
    }
    if (!next.issues.empty()) next.ready = false;
    std::sort(next.expectations.begin(), next.expectations.end(),
              [](const auto& left, const auto& right) {
                  return std::tie(left.owner, left.id) <
                         std::tie(right.owner, right.id);
              });
    std::sort(next.issues.begin(), next.issues.end(),
              [](const auto& left, const auto& right) {
                  return std::tie(left.owner, left.code) <
                         std::tie(right.owner, right.code);
              });
    next.issues.erase(
        std::unique(next.issues.begin(), next.issues.end(),
                    [](const auto& left, const auto& right) {
                        return left.owner == right.owner && left.code == right.code;
                    }),
        next.issues.end());

    std::lock_guard<std::mutex> lock(_mutex);
    if (signature(next) == signature(_snapshot)) return;
    next.generation = _snapshot.generation + 1;
    _snapshot = std::move(next);
}

void ParticipantExpectationState::reset()
{
    std::lock_guard<std::mutex> lock(_mutex);
    _snapshot = {};
}

ConfigurationParticipantExpectationSnapshot
ParticipantExpectationState::snapshot() const
{
    std::lock_guard<std::mutex> lock(_mutex);
    return _snapshot;
}

Health::Report ParticipantExpectationState::health() const
{
    const auto current = snapshot();
    if (current.ready)
        return {"configuration-participants", Health::Status::up,
                "All active Bundle configuration participant declarations are satisfied",
                "PDR-HEALTH-CONFIGURATION-PARTICIPANTS-UP", "", {}};

    std::vector<std::string> affected;
    std::size_t problemCount = current.issues.size();
    bool mismatched = false;
    for (const auto& expectation : current.expectations)
        if (!expectation.code.empty())
        {
            ++problemCount;
            if (expectation.status == "mismatched") mismatched = true;
            if (affected.size() < 16)
                affected.push_back(expectation.owner + ":" + expectation.id);
        }
    for (const auto& issue : current.issues)
        if (affected.size() < 16) affected.push_back(issue.owner);
    const auto invalid = !current.issues.empty();
    return {"configuration-participants", Health::Status::degraded,
            std::to_string(problemCount) +
                " configuration participant declaration issue(s)",
            invalid
                ? "PDR-HEALTH-CONFIGURATION-PARTICIPANT-DECLARATION-INVALID"
                : (mismatched
                       ? "PDR-HEALTH-CONFIGURATION-PARTICIPANT-CONTRACT-MISMATCH"
                       : "PDR-HEALTH-CONFIGURATION-PARTICIPANT-REQUIRED-MISSING"),
            "Repair the Bundle-local configuration-participants.json contract or "
            "register an exactly matching transactional participant service.",
            std::move(affected)};
}
} // namespace PocoDDS::ConfigTransaction
