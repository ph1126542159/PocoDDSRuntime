#include "KeyLifecycleState.h"

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
struct Version
{
    unsigned major{0};
    unsigned minor{0};
    unsigned patch{0};

    auto tie() const { return std::tie(major, minor, patch); }
};

bool operator<(const Version& left, const Version& right)
{
    return left.tie() < right.tie();
}

bool operator<=(const Version& left, const Version& right)
{
    return left.tie() <= right.tie();
}

bool validIdentifier(const std::string& value)
{
    return !value.empty() && value.size() <= 128 &&
           std::islower(static_cast<unsigned char>(value.front())) &&
           std::all_of(value.begin(), value.end(), [](unsigned char character) {
               return std::islower(character) || std::isdigit(character) ||
                      character == '-' || character == '.';
           });
}

bool validEntryId(const std::string& value)
{
    constexpr const char* PREFIX = "PDR-CFG-";
    if (value.rfind(PREFIX, 0) != 0 || value.size() < 12) return false;
    return std::all_of(value.begin() + 8, value.end(), [](unsigned char value) {
        return std::isdigit(value);
    });
}

bool validKey(const std::string& value)
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

Version version(const std::string& text)
{
    Version result;
    std::size_t offset = 0;
    unsigned* fields[] = {&result.major, &result.minor, &result.patch};
    for (std::size_t index = 0; index < 3; ++index)
    {
        const auto separator = text.find('.', offset);
        const auto end = index == 2 ? text.size() : separator;
        if (end == std::string::npos || end == offset ||
            (index == 2 && separator != std::string::npos))
            throw Poco::InvalidArgumentException("invalid semantic version");
        const auto part = text.substr(offset, end - offset);
        if (!std::all_of(part.begin(), part.end(), [](unsigned char character) {
                return std::isdigit(character);
            }))
            throw Poco::InvalidArgumentException("invalid semantic version");
        try
        {
            *fields[index] = static_cast<unsigned>(std::stoul(part));
        }
        catch (const std::exception&)
        {
            throw Poco::InvalidArgumentException("invalid semantic version");
        }
        offset = end + 1;
    }
    return result;
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

std::vector<KeyLifecycleEntry> parse(
    const KeyLifecycleDocument& document, const Version& runtimeVersion)
{
    if (document.owner.empty() || document.owner.size() > 192)
        throw Poco::InvalidArgumentException("invalid lifecycle owner");
    if (document.json.size() > KeyLifecycleState::MAXIMUM_DOCUMENT_BYTES)
        throw Poco::RangeException("key lifecycle declaration exceeds 64 KiB");
    const auto root = Poco::JSON::Parser().parse(document.json)
                          .extract<Poco::JSON::Object::Ptr>();
    if (!root || root->optValue<int>("schemaVersion", 0) != 1)
        throw Poco::InvalidArgumentException("schemaVersion must equal 1");
    requireKnownFields(root, {"schemaVersion", "entries"},
                       "key lifecycle document");
    const auto entries = root->getArray("entries");
    if (!entries || entries->size() > 128)
        throw Poco::InvalidArgumentException(
            "entries must be an array with at most 128 items");

    std::vector<KeyLifecycleEntry> result;
    std::set<std::string> ids;
    std::set<std::string> sources;
    const std::set<std::string> fields = {
        "id", "participantId", "operation", "sourceKey", "replacementKey",
        "deprecatedSince", "removalAllowedFrom",
    };
    for (std::size_t index = 0; index < entries->size(); ++index)
    {
        const auto item = entries->getObject(static_cast<unsigned>(index));
        if (!item)
            throw Poco::InvalidArgumentException(
                "key lifecycle entry must be an object");
        requireKnownFields(item, fields, "key lifecycle entry");
        for (const auto& field : fields)
            if (!item->has(field))
                throw Poco::InvalidArgumentException(
                    "key lifecycle entry is missing field", field);
        KeyLifecycleEntry entry;
        entry.owner = document.owner;
        entry.ownerActive = document.ownerActive;
        entry.id = item->optValue<std::string>("id", "");
        entry.participantId = item->optValue<std::string>("participantId", "");
        entry.operation = item->optValue<std::string>("operation", "");
        entry.sourceKey = item->optValue<std::string>("sourceKey", "");
        entry.deprecatedSince = item->optValue<std::string>("deprecatedSince", "");
        entry.removalAllowedFrom =
            item->optValue<std::string>("removalAllowedFrom", "");
        if (!item->isNull("replacementKey"))
            entry.replacementKey =
                item->optValue<std::string>("replacementKey", "");
        if (!validEntryId(entry.id) || !validIdentifier(entry.participantId) ||
            !validKey(entry.sourceKey) ||
            (entry.operation != "rename" && entry.operation != "remove") ||
            (entry.operation == "rename" &&
             (!validKey(entry.replacementKey) ||
              entry.replacementKey == entry.sourceKey)) ||
            (entry.operation == "remove" && !entry.replacementKey.empty()))
            throw Poco::InvalidArgumentException("key lifecycle entry is invalid");
        const auto deprecated = version(entry.deprecatedSince);
        const auto removal = version(entry.removalAllowedFrom);
        if (runtimeVersion < deprecated)
            throw Poco::InvalidArgumentException(
                "deprecatedSince is newer than Runtime");
        if (removal <= deprecated || removal.major <= deprecated.major)
            throw Poco::InvalidArgumentException(
                "removalAllowedFrom must be in a later major version");
        if (!ids.insert(entry.id).second ||
            !sources.insert(entry.sourceKey).second)
            throw Poco::ExistsException(
                "key lifecycle repeats an id or sourceKey");
        result.push_back(std::move(entry));
    }
    return result;
}

bool replacementCycle(const std::vector<KeyLifecycleEntry>& entries,
                      std::set<std::string>& owners)
{
    std::map<std::string, std::pair<std::string, std::string>> graph;
    for (const auto& entry : entries)
        if (!entry.replacementKey.empty())
            graph[entry.sourceKey] = {entry.replacementKey, entry.owner};
    bool cyclic = false;
    for (const auto& [start, edge] : graph)
    {
        static_cast<void>(edge);
        std::set<std::string> seen;
        std::string node = start;
        while (graph.count(node) != 0)
        {
            if (!seen.insert(node).second)
            {
                cyclic = true;
                for (const auto& value : seen) owners.insert(graph[value].second);
                break;
            }
            node = graph[node].first;
        }
    }
    return cyclic;
}

std::string signature(const KeyLifecycleSnapshot& value)
{
    std::string result = (value.ready ? "1" : "0") +
                         std::to_string(value.declarationCount);
    for (const auto& entry : value.entries)
        result += "|" + entry.owner + "|" + (entry.ownerActive ? "1" : "0") +
                  "|" + entry.id + "|" + entry.participantId + "|" +
                  entry.operation + "|" + entry.sourceKey + "|" +
                  entry.replacementKey + "|" + entry.deprecatedSince + "|" +
                  entry.removalAllowedFrom + "|" + entry.status + "|" + entry.code;
    for (const auto& issue : value.issues)
        result += "|!" + issue.owner + "|" + issue.code + "|" +
                  (issue.blocking ? "1" : "0");
    return result;
}
} // namespace

void KeyLifecycleState::replace(
    const std::vector<KeyLifecycleDocument>& documents,
    const ConfigurationParticipantCatalogSnapshot& catalog,
    const std::vector<AdmittedParticipantObservation>& observations,
    const std::string& runtimeVersionText)
{
    const auto runtimeVersion = version(runtimeVersionText);
    KeyLifecycleSnapshot next;
    next.declarationCount = documents.size();
    std::vector<KeyLifecycleEntry> entries;
    std::set<std::string> ids;
    std::set<std::string> sources;
    for (const auto& document : documents)
    {
        try
        {
            auto parsed = parse(document, runtimeVersion);
            if (entries.size() + parsed.size() > MAXIMUM_ENTRIES)
                throw Poco::RangeException(
                    "key lifecycle entries exceed global capacity");
            auto nextIds = ids;
            auto nextSources = sources;
            for (const auto& entry : parsed)
                if (!nextIds.insert(entry.id).second ||
                    !nextSources.insert(entry.sourceKey).second)
                    throw Poco::ExistsException(
                        "key lifecycle conflicts across Bundles");
            ids = std::move(nextIds);
            sources = std::move(nextSources);
            entries.insert(entries.end(),
                           std::make_move_iterator(parsed.begin()),
                           std::make_move_iterator(parsed.end()));
        }
        catch (const std::exception&)
        {
            next.issues.push_back({
                document.owner, "configuration-key-lifecycle-invalid",
                document.ownerActive,
            });
            if (document.ownerActive) next.ready = false;
        }
    }

    std::set<std::string> cycleOwners;
    if (replacementCycle(entries, cycleOwners))
        for (const auto& owner : cycleOwners)
        {
            const auto blocking = std::any_of(
                entries.begin(), entries.end(), [&](const auto& entry) {
                    return entry.owner == owner && entry.ownerActive;
                });
            next.issues.push_back({
                owner, "configuration-key-lifecycle-cycle", blocking,
            });
            if (blocking) next.ready = false;
        }

    std::map<std::string, ConfigurationParticipantCatalogEntry> admitted;
    for (const auto& entry : catalog.participants) admitted.emplace(entry.id, entry);
    std::map<std::string, AdmittedParticipantObservation> observed;
    for (const auto& observation : observations)
        observed.emplace(observation.id, observation);
    for (auto& entry : entries)
    {
        if (!entry.ownerActive)
        {
            entry.status = "inactive";
            next.entries.push_back(std::move(entry));
            continue;
        }
        const auto participant = admitted.find(entry.participantId);
        const auto observation = observed.find(entry.participantId);
        const auto keyOwned = [&](const std::string& key) {
            return key.empty() ||
                   (participant != admitted.end() &&
                    std::any_of(participant->second.ownedPrefixes.begin(),
                                participant->second.ownedPrefixes.end(),
                                [&](const auto& prefix) { return owns(prefix, key); }));
        };
        if (participant == admitted.end() || observation == observed.end() ||
            observation->second.owner != entry.owner ||
            !keyOwned(entry.sourceKey) || !keyOwned(entry.replacementKey))
        {
            entry.status = "mismatched";
            entry.code = "configuration-key-lifecycle-owner-mismatch";
            next.ready = false;
        }
        else
            entry.status = "published";
        next.entries.push_back(std::move(entry));
    }
    std::sort(next.entries.begin(), next.entries.end(),
              [](const auto& left, const auto& right) {
                  return std::tie(left.owner, left.id) <
                         std::tie(right.owner, right.id);
              });
    std::sort(next.issues.begin(), next.issues.end(),
              [](const auto& left, const auto& right) {
                  return std::tie(left.owner, left.code, left.blocking) <
                         std::tie(right.owner, right.code, right.blocking);
              });
    next.issues.erase(
        std::unique(next.issues.begin(), next.issues.end(),
                    [](const auto& left, const auto& right) {
                        return left.owner == right.owner &&
                               left.code == right.code &&
                               left.blocking == right.blocking;
                    }),
        next.issues.end());

    std::lock_guard<std::mutex> lock(_mutex);
    if (signature(next) == signature(_snapshot)) return;
    next.generation = _snapshot.generation + 1;
    _snapshot = std::move(next);
}

void KeyLifecycleState::reset()
{
    std::lock_guard<std::mutex> lock(_mutex);
    _snapshot = {};
}

KeyLifecycleSnapshot KeyLifecycleState::snapshot() const
{
    std::lock_guard<std::mutex> lock(_mutex);
    return _snapshot;
}

Health::Report KeyLifecycleState::health() const
{
    const auto current = snapshot();
    if (current.ready)
        return {"configuration-key-lifecycle", Health::Status::up,
                "All active Bundle configuration key lifecycles are valid",
                "PDR-HEALTH-CONFIGURATION-KEY-LIFECYCLE-UP", "", {}};
    std::vector<std::string> affected;
    for (const auto& entry : current.entries)
        if (!entry.code.empty() && affected.size() < 16)
            affected.push_back(entry.owner + ":" + entry.id);
    for (const auto& issue : current.issues)
        if (issue.blocking && affected.size() < 16)
            affected.push_back(issue.owner);
    return {"configuration-key-lifecycle", Health::Status::degraded,
            "Active Bundle configuration key lifecycle is invalid",
            "PDR-HEALTH-CONFIGURATION-KEY-LIFECYCLE-INVALID",
            "Repair the Bundle-local configuration-key-lifecycle.json or its "
            "Participant ownership before applying project migrations.",
            std::move(affected)};
}
} // namespace PocoDDS::ConfigTransaction
