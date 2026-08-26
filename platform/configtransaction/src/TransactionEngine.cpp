#include "PocoDDS/ConfigTransaction/TransactionEngine.h"
#include "PocoDDS/ConfigTransaction/ConfigurationPreflight.h"
#include "PocoDDS/ConfigTransaction/ConfigurationParticipantCatalog.h"

#include <Poco/Exception.h>
#include <Poco/Timestamp.h>
#include <Poco/UUIDGenerator.h>

#include <algorithm>
#include <atomic>
#include <cctype>
#include <condition_variable>
#include <map>
#include <mutex>
#include <set>
#include <stdexcept>
#include <unordered_map>
#include <utility>

namespace PocoDDS::ConfigTransaction
{
namespace
{
Poco::Int64 nowMicroseconds() { return Poco::Timestamp().epochMicroseconds(); }

bool validId(const std::string& id)
{
    if (id.empty() || !std::islower(static_cast<unsigned char>(id.front()))) return false;
    return std::all_of(id.begin(), id.end(), [](unsigned char value) {
        return std::islower(value) || std::isdigit(value) || value == '-' || value == '.';
    });
}

bool validPrefix(const std::string& prefix)
{
    return !prefix.empty() && prefix.front() != '.' && prefix.back() != '.' &&
           std::all_of(prefix.begin(), prefix.end(), [](unsigned char value) {
               return std::isalnum(value) || value == '-' || value == '_' || value == '.';
           });
}

bool owns(const std::string& prefix, const std::string& key)
{
    return key == prefix ||
           (key.size() > prefix.size() && key.compare(0, prefix.size(), prefix) == 0 &&
            key[prefix.size()] == '.');
}

bool overlaps(const std::string& left, const std::string& right)
{
    return owns(left, right) || owns(right, left);
}

ApplyResult resultFrom(const TransactionRecord& record, bool replay = false)
{
    ApplyResult result;
    result.transactionId = record.id;
    result.status = record.status;
    result.snapshot = record.status == Status::committed ? record.candidate : record.previous;
    result.changedKeys = record.changedKeys;
    result.participants = record.participants;
    result.errorCode = record.errorCode;
    result.errorMessage = record.errorMessage;
    result.idempotentReplay = replay;
    result.rolledBack = record.status == Status::rolledBack;
    return result;
}

struct ConfigurationEngineProvider
{
    std::mutex mutex;
    std::condition_variable changed;
    bool closing{false};
    std::size_t activeCalls{0};
    std::function<ConfigurationPreflightResult(
        const ConfigurationPreflightRequest&)> preflight;
    std::function<ConfigurationParticipantCatalogSnapshot()> participantCatalog;
};

std::mutex configurationProvidersMutex;
std::unordered_map<const TransactionEngine*, std::shared_ptr<ConfigurationEngineProvider>>
    configurationProviders;

void registerConfigurationProvider(
    TransactionEngine* engine,
    std::function<ConfigurationPreflightResult(
        const ConfigurationPreflightRequest&)> preflight,
    std::function<ConfigurationParticipantCatalogSnapshot()> participantCatalog)
{
    auto provider = std::make_shared<ConfigurationEngineProvider>();
    provider->preflight = std::move(preflight);
    provider->participantCatalog = std::move(participantCatalog);
    std::lock_guard<std::mutex> lock(configurationProvidersMutex);
    if (!configurationProviders.emplace(engine, std::move(provider)).second)
        throw Poco::ExistsException(
            "Configuration engine provider already registered");
}

void unregisterConfigurationProvider(TransactionEngine* engine) noexcept
{
    std::shared_ptr<ConfigurationEngineProvider> provider;
    {
        std::lock_guard<std::mutex> lock(configurationProvidersMutex);
        const auto found = configurationProviders.find(engine);
        if (found == configurationProviders.end()) return;
        provider = found->second;
        configurationProviders.erase(found);
    }
    std::unique_lock<std::mutex> lock(provider->mutex);
    provider->closing = true;
    provider->changed.wait(lock, [&] { return provider->activeCalls == 0; });
    provider->preflight = {};
    provider->participantCatalog = {};
}

std::shared_ptr<ConfigurationEngineProvider> acquireConfigurationProvider(
    const TransactionEngine* engine)
{
    std::shared_ptr<ConfigurationEngineProvider> provider;
    {
        std::lock_guard<std::mutex> lock(configurationProvidersMutex);
        const auto found = configurationProviders.find(engine);
        if (found == configurationProviders.end())
            throw Poco::IllegalStateException(
                "Configuration engine provider is unavailable");
        provider = found->second;
    }
    std::lock_guard<std::mutex> lock(provider->mutex);
    if (provider->closing || !provider->preflight || !provider->participantCatalog)
        throw Poco::IllegalStateException(
            "Configuration engine provider is closing");
    ++provider->activeCalls;
    return provider;
}

void releaseConfigurationProvider(
    const std::shared_ptr<ConfigurationEngineProvider>& provider) noexcept
{
    std::lock_guard<std::mutex> lock(provider->mutex);
    if (provider->activeCalls != 0) --provider->activeCalls;
    if (provider->activeCalls == 0) provider->changed.notify_all();
}
} // namespace

ParticipantRegistration::ParticipantRegistration(std::function<void()> cancel)
    : _cancel(std::move(cancel)) {}
ParticipantRegistration::~ParticipantRegistration() { reset(); }
ParticipantRegistration::ParticipantRegistration(ParticipantRegistration&& other) noexcept
    : _cancel(std::move(other._cancel)) { other._cancel = {}; }
ParticipantRegistration& ParticipantRegistration::operator=(ParticipantRegistration&& other) noexcept
{
    if (this != &other)
    {
        reset();
        _cancel = std::move(other._cancel);
        other._cancel = {};
    }
    return *this;
}
void ParticipantRegistration::reset() noexcept
{
    if (!_cancel) return;
    auto cancel = std::move(_cancel);
    _cancel = {};
    try { cancel(); } catch (...) {}
}
ParticipantRegistration::operator bool() const noexcept { return static_cast<bool>(_cancel); }

struct ParticipantCatalog
{
    struct InvocationGate
    {
        void acquire()
        {
            std::lock_guard<std::mutex> lock(mutex);
            ++active;
        }

        void release() noexcept
        {
            std::lock_guard<std::mutex> lock(mutex);
            if (active != 0) --active;
            if (active == 0) changed.notify_all();
        }

        void detachAndWait() noexcept
        {
            std::unique_lock<std::mutex> lock(mutex);
            changed.wait(lock, [&] { return active == 0; });
        }

        std::mutex mutex;
        std::condition_variable changed;
        std::size_t active{0};
    };

    struct InvocationLease
    {
        explicit InvocationLease(std::shared_ptr<InvocationGate> value)
            : gate(std::move(value))
        {
            gate->acquire();
        }
        ~InvocationLease() { gate->release(); }
        std::shared_ptr<InvocationGate> gate;
    };

    struct Entry
    {
        ParticipantDescriptor descriptor;
        Poco::AutoPtr<ConfigurationParticipantService> service;
        std::shared_ptr<InvocationGate> gate;
        Poco::UInt64 generation{0};
    };

    bool wouldCreateDependencyCycle(
        const ParticipantDescriptor& candidate) const
    {
        std::map<std::string, ParticipantDescriptor> descriptors;
        for (const auto& [id, entry] : entries)
            descriptors.emplace(id, entry.descriptor);
        descriptors.emplace(candidate.id, candidate);

        std::map<std::string, std::set<std::string>> remaining;
        for (const auto& [id, descriptor] : descriptors)
        {
            auto& dependencies = remaining[id];
            for (const auto& dependency : descriptor.after)
                if (descriptors.count(dependency) != 0)
                    dependencies.insert(dependency);
        }
        while (!remaining.empty())
        {
            std::vector<std::string> ready;
            for (const auto& [id, dependencies] : remaining)
                if (dependencies.empty()) ready.push_back(id);
            if (ready.empty()) return true;
            for (const auto& id : ready) remaining.erase(id);
            for (auto& [_, dependencies] : remaining)
                for (const auto& id : ready) dependencies.erase(id);
        }
        return false;
    }

    mutable std::mutex mutex;
    std::map<std::string, Entry> entries;
    std::atomic<Poco::UInt64> nextGeneration{1};
    Poco::UInt64 revision{0};
};

class TransactionEngine::Impl
{
public:
    Impl(std::unique_ptr<TransactionStore> value, Hooks callbacks)
        : store(std::move(value)), hooks(std::move(callbacks)), catalog(std::make_shared<ParticipantCatalog>())
    {
        if (!store) throw Poco::InvalidArgumentException("Configuration transaction store is required");
    }

    struct BoundParticipant
    {
        ParticipantDescriptor descriptor;
        Poco::AutoPtr<ConfigurationParticipantService> service;
        std::shared_ptr<ParticipantCatalog::InvocationLease> lease;
    };

    std::map<std::string, BoundParticipant> participantSnapshot() const
    {
        std::map<std::string, BoundParticipant> result;
        std::lock_guard<std::mutex> lock(catalog->mutex);
        for (const auto& [id, entry] : catalog->entries)
            result.emplace(id, BoundParticipant{
                entry.descriptor, entry.service,
                std::make_shared<ParticipantCatalog::InvocationLease>(entry.gate)});
        return result;
    }

    ConfigurationParticipantCatalogSnapshot participantCatalog() const
    {
        ConfigurationParticipantCatalogSnapshot result;
        Values digestValues;
        std::lock_guard<std::mutex> lock(catalog->mutex);
        result.generation = catalog->revision;
        digestValues["catalog.generation"] = std::to_string(result.generation);
        result.participants.reserve(catalog->entries.size());
        for (const auto& [id, entry] : catalog->entries)
        {
            ConfigurationParticipantCatalogEntry item;
            item.id = id;
            item.ownedPrefixes = entry.descriptor.ownedPrefixes;
            item.after = entry.descriptor.after;
            for (const auto& dependency : item.after)
                if (catalog->entries.count(dependency) == 0)
                    item.unresolvedAfter.push_back(dependency);
            item.registrationGeneration = entry.generation;
            result.participants.push_back(item);

            const auto root = "participant." + id + ".";
            digestValues[root + "registrationGeneration"] =
                std::to_string(entry.generation);
            for (std::size_t index = 0; index < item.ownedPrefixes.size(); ++index)
                digestValues[root + "ownedPrefix." + std::to_string(index)] =
                    item.ownedPrefixes[index];
            for (std::size_t index = 0; index < item.after.size(); ++index)
                digestValues[root + "after." + std::to_string(index)] = item.after[index];
            for (std::size_t index = 0; index < item.unresolvedAfter.size(); ++index)
                digestValues[root + "unresolvedAfter." + std::to_string(index)] =
                    item.unresolvedAfter[index];
        }
        result.digest = snapshotDigest(digestValues);
        return result;
    }

    static ParticipantResult invoke(
        BoundParticipant& participant, const char* phase, const Context& context)
    {
        try
        {
            if (std::string(phase) == "preflight") return participant.service->preflight(context);
            if (std::string(phase) == "commit") return participant.service->commit(context);
            return participant.service->rollback(context);
        }
        catch (const Poco::Exception& exception)
        {
            return ParticipantResult::rejected(
                "participant-exception", exception.displayText());
        }
        catch (const std::exception& exception)
        {
            return ParticipantResult::rejected("participant-exception", exception.what());
        }
        catch (...)
        {
            return ParticipantResult::rejected(
                "participant-exception", "unknown participant exception");
        }
    }

    std::vector<std::string> order(
        const std::set<std::string>& affected,
        const std::map<std::string, BoundParticipant>& participants) const
    {
        std::map<std::string, std::set<std::string>> remaining;
        for (const auto& id : affected)
        {
            const auto found = participants.find(id);
            if (found == participants.end())
                throw Poco::NotFoundException("Configuration participant disappeared", id);
            auto& dependencies = remaining[id];
            for (const auto& dependency : found->second.descriptor.after)
                if (affected.count(dependency) != 0) dependencies.insert(dependency);
        }
        std::vector<std::string> result;
        while (!remaining.empty())
        {
            std::vector<std::string> ready;
            for (const auto& [id, dependencies] : remaining)
                if (dependencies.empty()) ready.push_back(id);
            if (ready.empty())
                throw Poco::InvalidArgumentException("Configuration participant dependency cycle");
            for (const auto& id : ready)
            {
                result.push_back(id);
                remaining.erase(id);
            }
            for (auto& [_, dependencies] : remaining)
                for (const auto& id : ready) dependencies.erase(id);
        }
        return result;
    }

    struct PreparedOperation
    {
        Snapshot previous;
        Snapshot candidate;
        std::vector<std::string> changedKeys;
        std::map<std::string, BoundParticipant> participants;
        std::vector<std::string> orderedParticipants;
    };

    PreparedOperation prepare(Poco::UInt64 expectedGeneration,
                              const Values& candidateValues,
                              const std::string& principal)
    {
        const auto currentValue = store->current();
        if (!currentValue)
            throw Poco::IllegalStateException("Current configuration snapshot is missing");

        PreparedOperation prepared;
        prepared.previous = *currentValue;
        if (expectedGeneration != prepared.previous.generation)
            throw Poco::InvalidArgumentException(
                "Configuration generation conflict: expected " +
                std::to_string(expectedGeneration) + ", current " +
                std::to_string(prepared.previous.generation));

        prepared.candidate.generation = prepared.previous.generation + 1;
        prepared.candidate.values = candidateValues;
        prepared.candidate.digest = snapshotDigest(prepared.candidate.values);
        prepared.candidate.committedMicroseconds = nowMicroseconds();
        if (hooks.validate) hooks.validate(prepared.candidate);

        std::set<std::string> allKeys;
        for (const auto& [key, _] : prepared.previous.values) allKeys.insert(key);
        for (const auto& [key, _] : prepared.candidate.values) allKeys.insert(key);
        for (const auto& key : allKeys)
        {
            const auto oldValue = prepared.previous.values.find(key);
            const auto newValue = prepared.candidate.values.find(key);
            const bool differs = oldValue == prepared.previous.values.end() ||
                newValue == prepared.candidate.values.end() || oldValue->second != newValue->second;
            if (!differs) continue;
            if (newValue != prepared.candidate.values.end() && sensitiveKey(key) &&
                !sensitiveValueAllowed(key, newValue->second))
                throw Poco::InvalidArgumentException(
                    "Sensitive configuration changes require env://NAME reference", key);
            prepared.changedKeys.push_back(key);
        }
        if (hooks.authorize) hooks.authorize(principal, prepared.changedKeys);

        prepared.participants = participantSnapshot();
        std::set<std::string> affected;
        for (const auto& key : prepared.changedKeys)
        {
            std::string owner;
            for (const auto& [id, participant] : prepared.participants)
                for (const auto& prefix : participant.descriptor.ownedPrefixes)
                    if (owns(prefix, key)) owner = id;
            if (owner.empty())
                throw Poco::InvalidArgumentException("No configuration participant owns key", key);
            affected.insert(owner);
        }
        prepared.orderedParticipants = order(affected, prepared.participants);
        return prepared;
    }

    ConfigurationPreflightResult preflight(
        const ConfigurationPreflightRequest& request)
    {
        std::lock_guard<std::mutex> operation(operationMutex);
        if (!initialized)
            throw Poco::IllegalStateException("Configuration engine is not initialized");
        if (request.requestId.empty() || request.requestId.size() > 128)
            throw Poco::InvalidArgumentException(
                "Configuration preflight requestId must contain 1..128 characters");

        const auto currentValue = store->current();
        if (!currentValue)
            throw Poco::IllegalStateException("Current configuration snapshot is missing");

        ConfigurationPreflightResult result;
        result.preflightId =
            Poco::UUIDGenerator::defaultGenerator().createRandom().toString();
        result.expectedGeneration = request.expectedGeneration;
        result.observedGeneration = currentValue->generation;
        if (request.expectedGeneration != currentValue->generation)
        {
            result.candidateGeneration = currentValue->generation + 1;
            result.candidateDigest = snapshotDigest(request.candidate);
            result.errorCode = "generation-conflict";
            result.errorMessage =
                "Configuration generation conflict: expected " +
                std::to_string(request.expectedGeneration) + ", current " +
                std::to_string(currentValue->generation);
            return result;
        }

        auto prepared = prepare(
            request.expectedGeneration, request.candidate, request.principal);
        result.changed = !prepared.changedKeys.empty();
        result.candidateGeneration = result.changed
            ? prepared.candidate.generation : prepared.previous.generation;
        result.candidateDigest = result.changed
            ? prepared.candidate.digest : prepared.previous.digest;
        result.changedKeys = prepared.changedKeys;
        result.participants = prepared.orderedParticipants;
        if (!result.changed)
        {
            result.accepted = true;
            return result;
        }

        Context context{result.preflightId, request.requestId, prepared.previous,
                        prepared.candidate, prepared.changedKeys, request.principal};
        for (const auto& id : prepared.orderedParticipants)
        {
            const auto response = invoke(
                prepared.participants.at(id), "preflight", context);
            if (!response.success)
            {
                result.errorCode = response.code.empty()
                    ? "preflight-rejected" : response.code;
                result.errorMessage = id + ": " + response.message;
                return result;
            }
        }
        result.accepted = true;
        return result;
    }

    bool rollback(TransactionRecord& record,
                  std::map<std::string, BoundParticipant>& participants,
                  const Context& context,
                  bool restoreActivation)
    {
        record.status = Status::rollingBack;
        record.updatedMicroseconds = nowMicroseconds();
        store->save(record);
        bool succeeded = true;
        std::string errors;
        if (restoreActivation && hooks.activate)
        {
            try { hooks.activate(record.previous); }
            catch (const std::exception& exception)
            {
                succeeded = false;
                errors = std::string("configuration restore failed: ") + exception.what();
            }
        }
        for (auto iterator = record.commitAttempted.rbegin();
             iterator != record.commitAttempted.rend(); ++iterator)
        {
            const auto found = participants.find(*iterator);
            if (found == participants.end())
            {
                succeeded = false;
                if (!errors.empty()) errors += "; ";
                errors += "missing participant " + *iterator;
                continue;
            }
            const auto response = invoke(found->second, "rollback", context);
            if (!response.success)
            {
                succeeded = false;
                if (!errors.empty()) errors += "; ";
                errors += *iterator + ": " + response.code + " " + response.message;
            }
        }
        record.status = succeeded ? Status::rolledBack : Status::rollbackFailed;
        if (!succeeded)
        {
            record.errorCode = "rollback-failed";
            record.errorMessage = errors;
        }
        record.updatedMicroseconds = nowMicroseconds();
        store->save(record);
        return succeeded;
    }

    std::unique_ptr<TransactionStore> store;
    Hooks hooks;
    std::shared_ptr<ParticipantCatalog> catalog;
    mutable std::mutex operationMutex;
    bool initialized{false};
};

TransactionEngine::TransactionEngine(std::unique_ptr<TransactionStore> store, Hooks hooks)
    : _impl(std::make_unique<Impl>(std::move(store), std::move(hooks)))
{
    auto* implementation = _impl.get();
    registerConfigurationProvider(
        this,
        [implementation](const auto& request) {
            return implementation->preflight(request);
        },
        [implementation] {
            return implementation->participantCatalog();
        });
}
TransactionEngine::~TransactionEngine()
{
    unregisterConfigurationProvider(this);
}

ConfigurationPreflightResult preflightConfigurationTransaction(
    TransactionEngine& engine,
    const ConfigurationPreflightRequest& request)
{
    const auto provider = acquireConfigurationProvider(&engine);
    try
    {
        auto result = provider->preflight(request);
        releaseConfigurationProvider(provider);
        return result;
    }
    catch (...)
    {
        releaseConfigurationProvider(provider);
        throw;
    }
}

ConfigurationParticipantCatalogSnapshot configurationParticipantCatalog(
    const TransactionEngine& engine)
{
    const auto provider = acquireConfigurationProvider(&engine);
    try
    {
        auto result = provider->participantCatalog();
        releaseConfigurationProvider(provider);
        return result;
    }
    catch (...)
    {
        releaseConfigurationProvider(provider);
        throw;
    }
}

void TransactionEngine::initialize(const Values& initialValues)
{
    std::lock_guard<std::mutex> operation(_impl->operationMutex);
    _impl->store->initialize();
    Snapshot seed;
    seed.generation = 1;
    seed.values = initialValues;
    seed.digest = snapshotDigest(seed.values);
    seed.committedMicroseconds = nowMicroseconds();
    _impl->store->seed(seed);
    auto current = _impl->store->current();
    if (!current) throw Poco::IllegalStateException("Configuration snapshot seed failed");
    if (current->generation == 1 && current->digest != seed.digest)
    {
        _impl->store->replaceBootstrap(seed);
        current = seed;
    }
    if (_impl->hooks.validate) _impl->hooks.validate(*current);
    if (_impl->hooks.activate) _impl->hooks.activate(*current);
    _impl->initialized = true;
}

ParticipantRegistration TransactionEngine::attach(
    Poco::AutoPtr<ConfigurationParticipantService> participant)
{
    if (!participant) throw Poco::InvalidArgumentException("Configuration participant is null");
    ParticipantDescriptor descriptor;
    try { descriptor = participant->descriptor(); }
    catch (const std::exception& exception)
    {
        throw Poco::InvalidArgumentException("Configuration participant descriptor failed",
                                             exception.what());
    }
    if (!validId(descriptor.id))
        throw Poco::InvalidArgumentException("Invalid configuration participant id", descriptor.id);
    if (descriptor.ownedPrefixes.empty())
        throw Poco::InvalidArgumentException("Configuration participant owns no prefixes", descriptor.id);
    std::sort(descriptor.ownedPrefixes.begin(), descriptor.ownedPrefixes.end());
    if (std::adjacent_find(descriptor.ownedPrefixes.begin(), descriptor.ownedPrefixes.end()) !=
        descriptor.ownedPrefixes.end())
        throw Poco::InvalidArgumentException("Duplicate configuration ownership prefix", descriptor.id);
    for (std::size_t left = 0; left < descriptor.ownedPrefixes.size(); ++left)
        for (std::size_t right = left + 1; right < descriptor.ownedPrefixes.size(); ++right)
            if (overlaps(descriptor.ownedPrefixes[left], descriptor.ownedPrefixes[right]))
                throw Poco::InvalidArgumentException(
                    "Overlapping configuration ownership prefixes within participant",
                    descriptor.id);
    for (const auto& prefix : descriptor.ownedPrefixes)
        if (!validPrefix(prefix))
            throw Poco::InvalidArgumentException("Invalid configuration ownership prefix", prefix);
    std::sort(descriptor.after.begin(), descriptor.after.end());
    if (std::adjacent_find(descriptor.after.begin(), descriptor.after.end()) != descriptor.after.end())
        throw Poco::InvalidArgumentException("Duplicate participant dependency", descriptor.id);
    if (std::find(descriptor.after.begin(), descriptor.after.end(), descriptor.id) != descriptor.after.end())
        throw Poco::InvalidArgumentException("Configuration participant depends on itself", descriptor.id);
    for (const auto& dependency : descriptor.after)
        if (!validId(dependency))
            throw Poco::InvalidArgumentException("Invalid participant dependency", dependency);

    const auto generation = _impl->catalog->nextGeneration.fetch_add(1);
    {
        std::lock_guard<std::mutex> lock(_impl->catalog->mutex);
        if (_impl->catalog->entries.count(descriptor.id) != 0)
            throw Poco::ExistsException("Configuration participant already registered", descriptor.id);
        for (const auto& [otherId, other] : _impl->catalog->entries)
            for (const auto& prefix : descriptor.ownedPrefixes)
                for (const auto& otherPrefix : other.descriptor.ownedPrefixes)
                    if (overlaps(prefix, otherPrefix))
                        throw Poco::ExistsException(
                            "Configuration ownership overlaps " + otherId, prefix);
        if (_impl->catalog->wouldCreateDependencyCycle(descriptor))
            throw Poco::InvalidArgumentException(
                "Configuration participant dependency cycle", descriptor.id);
        _impl->catalog->entries.emplace(
            descriptor.id,
            ParticipantCatalog::Entry{descriptor, std::move(participant),
                                      std::make_shared<ParticipantCatalog::InvocationGate>(),
                                      generation});
        ++_impl->catalog->revision;
    }
    const auto id = descriptor.id;
    std::weak_ptr<ParticipantCatalog> weak = _impl->catalog;
    return ParticipantRegistration([weak, id, generation] {
        const auto catalog = weak.lock();
        if (!catalog) return;
        std::shared_ptr<ParticipantCatalog::InvocationGate> gate;
        {
            std::lock_guard<std::mutex> lock(catalog->mutex);
            const auto found = catalog->entries.find(id);
            if (found != catalog->entries.end() && found->second.generation == generation)
            {
                gate = found->second.gate;
                catalog->entries.erase(found);
                ++catalog->revision;
            }
        }
        // Removing the catalog entry prevents new transactions from acquiring
        // the participant. Waiting for existing leases forms the Bundle unload
        // barrier for preflight, commit, and rollback callbacks.
        if (gate) gate->detachAndWait();
    });
}

Snapshot TransactionEngine::current() const
{
    std::lock_guard<std::mutex> operation(_impl->operationMutex);
    if (!_impl->initialized) throw Poco::IllegalStateException("Configuration engine is not initialized");
    const auto result = _impl->store->current();
    if (!result) throw Poco::IllegalStateException("Current configuration snapshot is missing");
    return *result;
}

ApplyResult TransactionEngine::apply(const ApplyRequest& request)
{
    std::lock_guard<std::mutex> operation(_impl->operationMutex);
    if (!_impl->initialized) throw Poco::IllegalStateException("Configuration engine is not initialized");
    if (request.requestId.empty() || request.requestId.size() > 128)
        throw Poco::InvalidArgumentException("Configuration requestId must contain 1..128 characters");

    const auto currentValue = _impl->store->current();
    if (!currentValue) throw Poco::IllegalStateException("Current configuration snapshot is missing");
    Snapshot candidateIdentity;
    candidateIdentity.values = request.candidate;
    candidateIdentity.digest = snapshotDigest(candidateIdentity.values);
    const auto inputDigest = request.inputDigest.empty()
        ? candidateIdentity.digest : request.inputDigest;

    if (const auto replay = _impl->store->findByRequestId(request.requestId))
    {
        const auto replayInputDigest = replay->inputDigest.empty()
            ? replay->candidate.digest : replay->inputDigest;
        if (replayInputDigest != inputDigest ||
            replay->previous.generation != request.expectedGeneration)
            throw Poco::InvalidArgumentException(
                "Configuration requestId was already used with different input", request.requestId);
        if (_impl->hooks.authorize)
            _impl->hooks.authorize(request.principal, replay->changedKeys);
        return resultFrom(*replay, true);
    }
    auto prepared = _impl->prepare(
        request.expectedGeneration, request.candidate, request.principal);
    const auto& previous = prepared.previous;
    const auto& candidate = prepared.candidate;
    const auto& changed = prepared.changedKeys;
    auto& participants = prepared.participants;
    const auto& ordered = prepared.orderedParticipants;

    TransactionRecord record;
    record.id = Poco::UUIDGenerator::defaultGenerator().createRandom().toString();
    record.requestId = request.requestId;
    record.inputDigest = inputDigest;
    record.principal = request.principal;
    record.status = Status::preflighting;
    record.previous = previous;
    record.candidate = changed.empty() ? previous : candidate;
    record.changedKeys = changed;
    record.participants = ordered;
    record.createdMicroseconds = nowMicroseconds();
    record.updatedMicroseconds = record.createdMicroseconds;
    _impl->store->save(record);
    if (changed.empty())
    {
        record.status = Status::committed;
        record.updatedMicroseconds = nowMicroseconds();
        _impl->store->save(record);
        return resultFrom(record);
    }

    Context context{record.id, record.requestId, previous, candidate, changed, request.principal};
    for (const auto& id : ordered)
    {
        const auto response = Impl::invoke(participants.at(id), "preflight", context);
        if (!response.success)
        {
            record.status = Status::preflightFailed;
            record.errorCode = response.code.empty() ? "preflight-rejected" : response.code;
            record.errorMessage = id + ": " + response.message;
            record.updatedMicroseconds = nowMicroseconds();
            _impl->store->save(record);
            return resultFrom(record);
        }
    }

    record.status = Status::committing;
    record.updatedMicroseconds = nowMicroseconds();
    _impl->store->save(record);
    bool activated = false;
    for (const auto& id : ordered)
    {
        record.commitAttempted.push_back(id);
        record.updatedMicroseconds = nowMicroseconds();
        _impl->store->save(record);
        const auto response = Impl::invoke(participants.at(id), "commit", context);
        if (!response.success)
        {
            record.errorCode = response.code.empty() ? "commit-rejected" : response.code;
            record.errorMessage = id + ": " + response.message;
            const bool rolledBack = _impl->rollback(record, participants, context, activated);
            auto result = resultFrom(record);
            result.rolledBack = rolledBack;
            return result;
        }
        record.committedParticipants.push_back(id);
        record.updatedMicroseconds = nowMicroseconds();
        _impl->store->save(record);
    }

    try
    {
        if (_impl->hooks.activate) _impl->hooks.activate(candidate);
        activated = true;
        record.status = Status::committed;
        record.updatedMicroseconds = nowMicroseconds();
        _impl->store->commit(record, candidate);
        return resultFrom(record);
    }
    catch (const std::exception& exception)
    {
        record.errorCode = "activation-failed";
        record.errorMessage = exception.what();
        const bool rolledBack = _impl->rollback(record, participants, context, activated);
        auto result = resultFrom(record);
        result.rolledBack = rolledBack;
        return result;
    }
}

std::size_t TransactionEngine::recover()
{
    std::lock_guard<std::mutex> operation(_impl->operationMutex);
    if (!_impl->initialized) return 0;
    auto participants = _impl->participantSnapshot();
    std::size_t recovered = 0;
    for (auto record : _impl->store->incomplete())
    {
        Context context{record.id, record.requestId, record.previous,
                        record.candidate, record.changedKeys, "pdr.configuration-recovery"};
        bool missing = false;
        for (const auto& id : record.commitAttempted)
            if (participants.count(id) == 0) missing = true;
        if (missing)
        {
            record.status = Status::recoveryPending;
            record.errorCode = "participant-unavailable";
            record.errorMessage = "Recovery waits for all commit-attempted participants";
            record.updatedMicroseconds = nowMicroseconds();
            _impl->store->save(record);
            continue;
        }
        if (record.commitAttempted.empty())
        {
            record.status = Status::rolledBack;
            record.updatedMicroseconds = nowMicroseconds();
            _impl->store->save(record);
            ++recovered;
            continue;
        }
        if (_impl->rollback(record, participants, context, false)) ++recovered;
    }
    return recovered;
}

std::vector<TransactionSummary> TransactionEngine::history(std::size_t limit) const
{
    std::lock_guard<std::mutex> operation(_impl->operationMutex);
    if (limit == 0 || limit > 1000)
        throw Poco::InvalidArgumentException("Configuration history limit must be 1..1000");
    const auto records = _impl->store->history(limit);
    std::vector<TransactionSummary> result;
    result.reserve(records.size());
    for (const auto& record : records) result.push_back(summarize(record));
    return result;
}

std::vector<std::string> TransactionEngine::participantIds() const
{
    std::vector<std::string> result;
    std::lock_guard<std::mutex> lock(_impl->catalog->mutex);
    result.reserve(_impl->catalog->entries.size());
    for (const auto& [id, _] : _impl->catalog->entries) result.push_back(id);
    return result;
}
} // namespace PocoDDS::ConfigTransaction
