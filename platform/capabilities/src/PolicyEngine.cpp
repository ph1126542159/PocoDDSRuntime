#include "PocoDDS/Capabilities/PolicyEngine.h"

#include <Poco/Exception.h>
#include <Poco/Timestamp.h>

#include <algorithm>
#include <atomic>
#include <deque>
#include <map>
#include <mutex>
#include <set>
#include <utility>

namespace PocoDDS::Capabilities
{
namespace
{
struct PolicyState
{
    Poco::UInt64 generation{1};
    std::string digest;
    std::vector<Rule> rules;
};

bool matches(const std::string& pattern, const std::string& value)
{
    if (pattern == "*") return true;
    if (!pattern.empty() && pattern.back() == '*')
        return value.compare(0, pattern.size() - 1, pattern, 0, pattern.size() - 1) == 0;
    return pattern == value;
}

void validateRequest(const Request& request)
{
    if (request.principal.empty())
        throw Poco::InvalidArgumentException("Capability principal cannot be empty");
    if (request.resource.empty())
        throw Poco::InvalidArgumentException("Capability resource cannot be empty");
    if (!actionAllowed(request.resourceKind, request.action))
        throw Poco::InvalidArgumentException(
            "Action is not valid for resource kind",
            std::string(actionName(request.action)) + "@" + resourceKindName(request.resourceKind));
}
} // namespace

class PolicyEngine::Impl
{
public:
    Impl(std::vector<Rule> rules, Poco::UInt64 generation, std::size_t capacity,
         AuditSink sink)
        : auditCapacity(capacity), auditSink(std::move(sink))
    {
        if (auditCapacity == 0) throw Poco::InvalidArgumentException("Audit capacity must be positive");
        auto initial = std::make_shared<PolicyState>();
        if (generation == 0)
            throw Poco::InvalidArgumentException("Policy generation must be positive");
        initial->generation = generation;
        initial->rules = std::move(rules);
        initial->digest = policyDigest(initial->rules);
        state = std::move(initial);
    }

    void record(const Request& request, const Decision& decision) const
    {
        const AuditRecord record{Poco::Timestamp().epochMicroseconds(), request, decision};
        if (auditSink) auditSink(record);
        std::lock_guard<std::mutex> lock(auditMutex);
        records.push_back(record);
        while (records.size() > auditCapacity) records.pop_front();
    }

    struct Replay
    {
        std::string actor;
        Poco::UInt64 expectedGeneration{0};
        std::string digest;
        ReplaceResult result;
    };

    std::shared_ptr<const PolicyState> state;
    const std::size_t auditCapacity;
    mutable std::mutex auditMutex;
    mutable std::deque<AuditRecord> records;
    AuditSink auditSink;
    std::mutex replaceMutex;
    std::map<std::string, Replay> replays;
    std::deque<std::string> replayOrder;
};

PolicyEngine::PolicyEngine(std::vector<Rule> initialRules, std::size_t auditCapacity,
                           AuditSink auditSink)
    : _impl(std::make_unique<Impl>(std::move(initialRules), 1, auditCapacity,
                                   std::move(auditSink))) {}
PolicyEngine::PolicyEngine(std::vector<Rule> recoveredRules,
                           Poco::UInt64 recoveredGeneration,
                           std::size_t auditCapacity, AuditSink auditSink)
    : _impl(std::make_unique<Impl>(std::move(recoveredRules), recoveredGeneration,
                                   auditCapacity, std::move(auditSink))) {}
PolicyEngine::~PolicyEngine() = default;

PolicySnapshot PolicyEngine::snapshot() const noexcept
{
    const auto state = std::atomic_load(&_impl->state);
    return {state->generation, state->digest, state->rules.size(), Effect::deny};
}

Decision PolicyEngine::decide(const Request& request) const
{
    validateRequest(request);
    const auto state = std::atomic_load(&_impl->state);
    const Rule* allow = nullptr;
    const Rule* deny = nullptr;
    for (const auto& rule : state->rules)
    {
        if (rule.resourceKind != request.resourceKind ||
            !matches(rule.principal, request.principal) ||
            !matches(rule.resource, request.resource) ||
            std::find(rule.actions.begin(), rule.actions.end(), request.action) == rule.actions.end())
            continue;
        if (rule.effect == Effect::deny)
        {
            if (!deny || rule.id < deny->id) deny = &rule;
        }
        else if (!allow || rule.id < allow->id) allow = &rule;
    }

    Decision decision;
    decision.policyGeneration = state->generation;
    decision.policyDigest = state->digest;
    if (deny)
    {
        decision.code = "CAPABILITY_EXPLICIT_DENY";
        decision.matchedRuleId = deny->id;
        decision.explanation = "explicit deny rule " + deny->id + " matched";
    }
    else if (allow)
    {
        decision.allowed = true;
        decision.code = "CAPABILITY_ALLOWED";
        decision.matchedRuleId = allow->id;
        decision.explanation = "allow rule " + allow->id + " matched";
    }
    else
    {
        decision.code = "CAPABILITY_DEFAULT_DENY";
        decision.explanation = "no matching allow rule; default deny applied";
    }
    _impl->record(request, decision);
    return decision;
}

void PolicyEngine::require(const Request& request) const
{
    const auto decision = decide(request);
    if (!decision.allowed)
        throw Poco::NoPermissionException(decision.code, decision.explanation);
}

ReplaceResult PolicyEngine::replace(const ReplaceRequest& request)
{
    if (request.requestId.empty() || request.requestId.size() > 128)
        throw Poco::InvalidArgumentException("Capability requestId must contain 1..128 characters");
    if (request.actor.empty())
        throw Poco::InvalidArgumentException("Capability policy actor cannot be empty");
    const auto replacementDigest = policyDigest(request.rules);
    std::lock_guard<std::mutex> lock(_impl->replaceMutex);
    const auto replay = _impl->replays.find(request.requestId);
    if (replay != _impl->replays.end())
    {
        if (replay->second.actor != request.actor ||
            replay->second.expectedGeneration != request.expectedGeneration ||
            replay->second.digest != replacementDigest)
            throw Poco::InvalidArgumentException(
                "Capability requestId was already used with different input", request.requestId);
        auto result = replay->second.result;
        result.idempotentReplay = true;
        return result;
    }

    const auto current = std::atomic_load(&_impl->state);
    if (request.expectedGeneration != current->generation)
        throw Poco::InvalidArgumentException(
            "Capability generation conflict: expected " +
            std::to_string(request.expectedGeneration) + ", current " +
            std::to_string(current->generation));
    auto next = std::make_shared<PolicyState>();
    next->generation = current->generation + 1;
    next->digest = replacementDigest;
    next->rules = request.rules;
    std::atomic_store(&_impl->state, std::shared_ptr<const PolicyState>(next));

    ReplaceResult result{{next->generation, next->digest, next->rules.size(), Effect::deny}, false};
    _impl->replays.emplace(request.requestId,
        Impl::Replay{request.actor, request.expectedGeneration, replacementDigest, result});
    _impl->replayOrder.push_back(request.requestId);
    while (_impl->replayOrder.size() > 1024)
    {
        _impl->replays.erase(_impl->replayOrder.front());
        _impl->replayOrder.pop_front();
    }
    return result;
}

PolicySnapshot PolicyEngine::restore(std::vector<Rule> rules, Poco::UInt64 generation)
{
    if (generation == 0)
        throw Poco::InvalidArgumentException("Policy generation must be positive");
    const auto replacementDigest = policyDigest(rules);
    auto next = std::make_shared<PolicyState>();
    next->generation = generation;
    next->digest = replacementDigest;
    next->rules = std::move(rules);
    std::lock_guard<std::mutex> lock(_impl->replaceMutex);
    std::atomic_store(&_impl->state, std::shared_ptr<const PolicyState>(next));
    _impl->replays.clear();
    _impl->replayOrder.clear();
    return {next->generation, next->digest, next->rules.size(), Effect::deny};
}

std::vector<AuditRecord> PolicyEngine::audit(std::size_t limit) const
{
    if (limit == 0 || limit > 1000)
        throw Poco::InvalidArgumentException("Capability audit limit must be 1..1000");
    std::lock_guard<std::mutex> lock(_impl->auditMutex);
    const auto count = std::min(limit, _impl->records.size());
    std::vector<AuditRecord> result;
    result.reserve(count);
    for (auto iterator = _impl->records.rbegin(); iterator != _impl->records.rend() && result.size() < count;
         ++iterator)
        result.push_back(*iterator);
    return result;
}
} // namespace PocoDDS::Capabilities
