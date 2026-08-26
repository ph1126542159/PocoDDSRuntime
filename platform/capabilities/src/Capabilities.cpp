#include "PocoDDS/Capabilities/Capabilities.h"

#include <Poco/Exception.h>
#include <Poco/File.h>
#include <Poco/JSON/Array.h>
#include <Poco/JSON/Object.h>
#include <Poco/JSON/Parser.h>
#include <Poco/JSON/Stringifier.h>
#include <Poco/Path.h>
#include <Poco/StreamCopier.h>
#include <Poco/DigestEngine.h>
#include <Poco/SHA2Engine.h>

#include <algorithm>
#include <cctype>
#include <fstream>
#include <set>
#include <sstream>

namespace PocoDDS::Capabilities
{
namespace
{
bool validIdentifier(const std::string& value, bool pattern)
{
    if (value.empty()) return false;
    const auto star = value.find('*');
    if (star != std::string::npos &&
        (!pattern || star != value.size() - 1 || value.find('*', star + 1) != std::string::npos))
        return false;
    return std::all_of(value.begin(), value.end(), [](unsigned char character) {
        return std::isalnum(character) || character == '.' || character == '-' ||
               character == '_' || character == ':' || character == '/' || character == '*';
    });
}

template <typename T>
T parsedEnum(const std::string& value, const std::vector<std::pair<const char*, T>>& values,
             const char* label)
{
    const auto found = std::find_if(values.begin(), values.end(), [&](const auto& item) {
        return value == item.first;
    });
    if (found == values.end())
        throw Poco::InvalidArgumentException(std::string("Unknown ") + label, value);
    return found->second;
}

Poco::JSON::Object::Ptr parseObject(const std::string& document)
{
    try
    {
        auto value = Poco::JSON::Parser().parse(document);
        auto object = value.extract<Poco::JSON::Object::Ptr>();
        if (!object) throw Poco::InvalidArgumentException("Capability policy must be an object");
        return object;
    }
    catch (const Poco::Exception&)
    {
        throw;
    }
    catch (const std::exception& exception)
    {
        throw Poco::InvalidArgumentException("Invalid capability policy", exception.what());
    }
}
} // namespace

const char* resourceKindName(ResourceKind value) noexcept
{
    switch (value)
    {
    case ResourceKind::service: return "service";
    case ResourceKind::topic: return "topic";
    case ResourceKind::configuration: return "configuration";
    case ResourceKind::device: return "device";
    case ResourceKind::schema: return "schema";
    }
    return "unknown";
}

ResourceKind parseResourceKind(const std::string& value)
{
    return parsedEnum<ResourceKind>(value,
        {{"service", ResourceKind::service}, {"topic", ResourceKind::topic},
         {"configuration", ResourceKind::configuration}, {"device", ResourceKind::device},
         {"schema", ResourceKind::schema}}, "resource kind");
}

const char* actionName(Action value) noexcept
{
    switch (value)
    {
    case Action::discover: return "discover";
    case Action::use: return "use";
    case Action::publish: return "publish";
    case Action::subscribe: return "subscribe";
    case Action::read: return "read";
    case Action::write: return "write";
    case Action::observe: return "observe";
    case Action::operate: return "operate";
    case Action::registerSchema: return "register";
    case Action::deprecate: return "deprecate";
    }
    return "unknown";
}

Action parseAction(const std::string& value)
{
    return parsedEnum<Action>(value,
        {{"discover", Action::discover}, {"use", Action::use}, {"publish", Action::publish},
         {"subscribe", Action::subscribe}, {"read", Action::read}, {"write", Action::write},
         {"observe", Action::observe}, {"operate", Action::operate},
         {"register", Action::registerSchema}, {"deprecate", Action::deprecate}}, "action");
}

const char* effectName(Effect value) noexcept { return value == Effect::allow ? "allow" : "deny"; }

Effect parseEffect(const std::string& value)
{
    return parsedEnum<Effect>(value, {{"allow", Effect::allow}, {"deny", Effect::deny}}, "effect");
}

bool actionAllowed(ResourceKind kind, Action action) noexcept
{
    switch (kind)
    {
    case ResourceKind::service:
        return action == Action::discover || action == Action::use;
    case ResourceKind::topic:
        return action == Action::publish || action == Action::subscribe;
    case ResourceKind::configuration:
        return action == Action::read || action == Action::write;
    case ResourceKind::device:
        return action == Action::observe || action == Action::operate;
    case ResourceKind::schema:
        return action == Action::read || action == Action::registerSchema ||
               action == Action::deprecate;
    }
    return false;
}

void validateRule(const Rule& rule)
{
    if (!validIdentifier(rule.id, false))
        throw Poco::InvalidArgumentException("Invalid capability rule id", rule.id);
    if (!validIdentifier(rule.principal, true))
        throw Poco::InvalidArgumentException("Invalid capability principal pattern", rule.principal);
    if (!validIdentifier(rule.resource, true))
        throw Poco::InvalidArgumentException("Invalid capability resource pattern", rule.resource);
    if (rule.actions.empty())
        throw Poco::InvalidArgumentException("Capability rule has no actions", rule.id);
    std::set<Action> unique;
    for (const auto action : rule.actions)
    {
        if (!actionAllowed(rule.resourceKind, action))
            throw Poco::InvalidArgumentException(
                "Action is not valid for resource kind", std::string(actionName(action)) + "@" +
                                                          resourceKindName(rule.resourceKind));
        if (!unique.insert(action).second)
            throw Poco::InvalidArgumentException("Duplicate capability action", rule.id);
    }
}

std::vector<Rule> parsePolicyDocument(const std::string& document)
{
    const auto object = parseObject(document);
    const std::set<std::string> policyFields{"$schema", "version", "defaultEffect", "rules"};
    for (const auto& name : object->getNames())
        if (policyFields.count(name) == 0)
            throw Poco::InvalidArgumentException("Unknown capability policy field", name);
    if (object->getValue<int>("version") != 1)
        throw Poco::InvalidArgumentException("Unsupported capability policy version");
    if (!object->has("defaultEffect") ||
        object->getValue<std::string>("defaultEffect") != "deny")
        throw Poco::InvalidArgumentException("Capability policy defaultEffect must be deny");
    const auto rulesArray = object->getArray("rules");
    if (!rulesArray) throw Poco::InvalidArgumentException("Capability policy rules must be an array");

    std::vector<Rule> rules;
    std::set<std::string> ids;
    rules.reserve(rulesArray->size());
    for (std::size_t index = 0; index < rulesArray->size(); ++index)
    {
        const auto entry = rulesArray->getObject(static_cast<unsigned>(index));
        if (!entry) throw Poco::InvalidArgumentException("Capability rule must be an object");
        const std::set<std::string> ruleFields{
            "id", "effect", "principal", "resourceKind", "resource", "actions"};
        for (const auto& name : entry->getNames())
            if (ruleFields.count(name) == 0)
                throw Poco::InvalidArgumentException("Unknown capability rule field", name);
        Rule rule;
        rule.id = entry->getValue<std::string>("id");
        rule.effect = parseEffect(entry->getValue<std::string>("effect"));
        rule.principal = entry->getValue<std::string>("principal");
        rule.resourceKind = parseResourceKind(entry->getValue<std::string>("resourceKind"));
        rule.resource = entry->getValue<std::string>("resource");
        const auto actions = entry->getArray("actions");
        if (!actions) throw Poco::InvalidArgumentException("Capability rule actions must be an array");
        for (std::size_t actionIndex = 0; actionIndex < actions->size(); ++actionIndex)
            rule.actions.push_back(parseAction(actions->getElement<std::string>(
                static_cast<unsigned>(actionIndex))));
        validateRule(rule);
        if (!ids.insert(rule.id).second)
            throw Poco::InvalidArgumentException("Duplicate capability rule id", rule.id);
        rules.push_back(std::move(rule));
    }
    return rules;
}

std::vector<Rule> loadPolicyFile(const std::string& path)
{
    std::ifstream stream(path, std::ios::binary);
    if (!stream) throw Poco::OpenFileException("Cannot open capability policy", path);
    std::ostringstream document;
    document << stream.rdbuf();
    return parsePolicyDocument(document.str());
}

std::string policyDocument(const std::vector<Rule>& input)
{
    auto rules = input;
    for (const auto& rule : rules) validateRule(rule);
    std::sort(rules.begin(), rules.end(), [](const auto& left, const auto& right) {
        return left.id < right.id;
    });
    Poco::JSON::Object root;
    root.set("version", 1);
    root.set("defaultEffect", "deny");
    Poco::JSON::Array::Ptr outputRules = new Poco::JSON::Array;
    std::set<std::string> ids;
    for (auto rule : rules)
    {
        if (!ids.insert(rule.id).second)
            throw Poco::InvalidArgumentException("Duplicate capability rule id", rule.id);
        std::sort(rule.actions.begin(), rule.actions.end(), [](Action left, Action right) {
            return std::string(actionName(left)) < std::string(actionName(right));
        });
        Poco::JSON::Object::Ptr outputRule = new Poco::JSON::Object;
        outputRule->set("id", rule.id);
        outputRule->set("effect", effectName(rule.effect));
        outputRule->set("principal", rule.principal);
        outputRule->set("resourceKind", resourceKindName(rule.resourceKind));
        outputRule->set("resource", rule.resource);
        Poco::JSON::Array::Ptr actions = new Poco::JSON::Array;
        for (const auto action : rule.actions) actions->add(actionName(action));
        outputRule->set("actions", actions);
        outputRules->add(outputRule);
    }
    root.set("rules", outputRules);
    std::ostringstream stream;
    Poco::JSON::Stringifier::stringify(root, stream, 2);
    stream << '\n';
    return stream.str();
}

std::string policyDigest(const std::vector<Rule>& rules)
{
    Poco::SHA2Engine engine(Poco::SHA2Engine::SHA_256);
    engine.update(policyDocument(rules));
    return Poco::DigestEngine::digestToHex(engine.digest());
}
} // namespace PocoDDS::Capabilities
