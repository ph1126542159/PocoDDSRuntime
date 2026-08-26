#pragma once

#include "PocoDDS/Capabilities/Export.h"

#include <Poco/Types.h>

#include <cstddef>
#include <string>
#include <vector>

namespace PocoDDS::Capabilities
{
enum class ResourceKind
{
    service,
    topic,
    configuration,
    device,
    schema
};

enum class Action
{
    discover,
    use,
    publish,
    subscribe,
    read,
    write,
    observe,
    operate,
    registerSchema,
    deprecate
};

enum class Effect
{
    allow,
    deny
};

PDR_CAPABILITIES_API const char* resourceKindName(ResourceKind value) noexcept;
PDR_CAPABILITIES_API ResourceKind parseResourceKind(const std::string& value);
PDR_CAPABILITIES_API const char* actionName(Action value) noexcept;
PDR_CAPABILITIES_API Action parseAction(const std::string& value);
PDR_CAPABILITIES_API const char* effectName(Effect value) noexcept;
PDR_CAPABILITIES_API Effect parseEffect(const std::string& value);
PDR_CAPABILITIES_API bool actionAllowed(ResourceKind kind, Action action) noexcept;

struct Rule
{
    std::string id;
    Effect effect{Effect::deny};
    std::string principal;
    ResourceKind resourceKind{ResourceKind::service};
    std::string resource;
    std::vector<Action> actions;
};

struct Request
{
    std::string principal;
    ResourceKind resourceKind{ResourceKind::service};
    std::string resource;
    Action action{Action::discover};
};

struct Decision
{
    bool allowed{false};
    std::string code;
    std::string matchedRuleId;
    std::string explanation;
    Poco::UInt64 policyGeneration{0};
    std::string policyDigest;
};

struct PolicySnapshot
{
    Poco::UInt64 generation{0};
    std::string digest;
    std::size_t ruleCount{0};
    Effect defaultEffect{Effect::deny};
};

struct AuditRecord
{
    Poco::Int64 timestampMicroseconds{0};
    Request request;
    Decision decision;
};

struct ReplaceRequest
{
    std::string requestId;
    std::string actor;
    Poco::UInt64 expectedGeneration{0};
    std::vector<Rule> rules;
};

struct ReplaceResult
{
    PolicySnapshot snapshot;
    bool idempotentReplay{false};
};

struct PersistedPolicy
{
    PolicySnapshot snapshot;
    std::vector<Rule> rules;
    Poco::Int64 updatedMicroseconds{0};
};

struct PersistenceSnapshot
{
    bool healthy{false};
    bool recoveryRequired{false};
    std::string databasePath;
    Poco::UInt64 generation{0};
    std::string digest;
    Poco::UInt64 auditRecords{0};
    Poco::UInt64 requestRecords{0};
    std::string error;
};

PDR_CAPABILITIES_API void validateRule(const Rule& rule);
PDR_CAPABILITIES_API std::vector<Rule> parsePolicyDocument(const std::string& document);
PDR_CAPABILITIES_API std::vector<Rule> loadPolicyFile(const std::string& path);
PDR_CAPABILITIES_API std::string policyDocument(const std::vector<Rule>& rules);
PDR_CAPABILITIES_API std::string policyDigest(const std::vector<Rule>& rules);
} // namespace PocoDDS::Capabilities
