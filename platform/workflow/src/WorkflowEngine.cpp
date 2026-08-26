#include "PocoDDS/Workflow/WorkflowEngine.h"

#include <Poco/Exception.h>
#include <Poco/Timestamp.h>
#include <Poco/UUIDGenerator.h>

#include <algorithm>
#include <regex>
#include <unordered_set>
#include <utility>

namespace PocoDDS::Workflow
{
namespace
{
Poco::Int64 nowMicroseconds()
{
    return Poco::Timestamp().epochMicroseconds();
}

void validateDescriptor(const DefinitionDescriptor& descriptor)
{
    static const std::regex typePattern("^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$");
    if (!std::regex_match(descriptor.type, typePattern))
        throw Poco::InvalidArgumentException(
            "Workflow type must be a lower-case kebab-case identifier", descriptor.type);
    if (descriptor.version.empty())
        throw Poco::InvalidArgumentException("Workflow definition version is empty");
    if (descriptor.steps.empty())
        throw Poco::InvalidArgumentException("Workflow definition has no steps", descriptor.type);
    if (descriptor.maximumAttempts == 0)
        throw Poco::InvalidArgumentException("Workflow maximumAttempts must be greater than zero");

    std::unordered_set<std::string> seen;
    for (const auto& step : descriptor.steps)
    {
        if (step.empty())
            throw Poco::InvalidArgumentException("Workflow definition contains an empty step");
        if (!seen.insert(step).second)
            throw Poco::InvalidArgumentException("Workflow definition contains a duplicate step", step);
    }
}

StepContext contextFor(const Instance& instance)
{
    return {instance.id,
            instance.businessKey,
            instance.input,
            instance.signalPayload,
            instance.attempt};
}
} // namespace

const char* stateName(State state) noexcept
{
    switch (state)
    {
    case State::queued: return "queued";
    case State::running: return "running";
    case State::waiting: return "waiting";
    case State::retryScheduled: return "retry-scheduled";
    case State::compensating: return "compensating";
    case State::interrupted: return "interrupted";
    case State::succeeded: return "succeeded";
    case State::failed: return "failed";
    case State::cancelled: return "cancelled";
    }
    return "unknown";
}

State parseState(const std::string& value)
{
    if (value == "queued") return State::queued;
    if (value == "running") return State::running;
    if (value == "waiting") return State::waiting;
    if (value == "retry-scheduled") return State::retryScheduled;
    if (value == "compensating") return State::compensating;
    if (value == "interrupted") return State::interrupted;
    if (value == "succeeded") return State::succeeded;
    if (value == "failed") return State::failed;
    if (value == "cancelled") return State::cancelled;
    throw Poco::DataFormatException("Unknown workflow state", value);
}

bool terminal(State state) noexcept
{
    return state == State::succeeded || state == State::failed || state == State::cancelled;
}

WorkflowEngine::WorkflowEngine(std::unique_ptr<WorkflowStore> store)
    : _store(std::move(store))
{
    if (!_store) throw Poco::NullPointerException("Workflow store is null");
}

void WorkflowEngine::initialize()
{
    std::lock_guard<std::mutex> lock(_mutex);
    _store->initialize();
    _store->markActiveInterrupted(nowMicroseconds());
}

void WorkflowEngine::attach(Poco::AutoPtr<WorkflowDefinitionService> definition)
{
    if (!definition) throw Poco::NullPointerException("Workflow definition service is null");
    auto descriptor = definition->descriptor();
    validateDescriptor(descriptor);
    std::lock_guard<std::mutex> lock(_mutex);
    if (_definitions.find(descriptor.type) != _definitions.end())
        throw Poco::ExistsException("Workflow definition is already attached", descriptor.type);
    const std::string type = descriptor.type;
    _definitions.emplace(type,
                         AttachedDefinition{std::move(descriptor), std::move(definition)});
}

void WorkflowEngine::detach(const std::string& type)
{
    std::lock_guard<std::mutex> lock(_mutex);
    const auto existing = _definitions.find(type);
    if (existing == _definitions.end()) return;
    const auto instances = _store->list();
    const auto active = std::find_if(instances.begin(), instances.end(), [&](const Instance& item) {
        return item.type == type && !terminal(item.state);
    });
    if (active != instances.end())
        throw Poco::IllegalStateException(
            "Cannot detach workflow definition while an instance is active", type);
    _definitions.erase(existing);
}

Instance WorkflowEngine::start(const std::string& type,
                               const std::string& businessKey,
                               const std::string& input)
{
    if (type.empty()) throw Poco::InvalidArgumentException("Workflow type is empty");
    if (businessKey.empty()) throw Poco::InvalidArgumentException("Workflow business key is empty");
    std::lock_guard<std::mutex> lock(_mutex);
    if (const auto existing = _store->findByBusinessKey(type, businessKey)) return *existing;

    auto& definition = requireDefinition(type);
    const auto now = nowMicroseconds();
    Instance instance;
    instance.id = Poco::UUIDGenerator::defaultGenerator().createRandom().toString();
    instance.type = type;
    instance.definitionVersion = definition.descriptor.version;
    instance.businessKey = businessKey;
    instance.input = input;
    instance.createdMicroseconds = now;
    instance.updatedMicroseconds = now;
    persist(instance);
    return run(std::move(instance), definition);
}

Instance WorkflowEngine::signal(const std::string& id,
                                const std::string& event,
                                const std::string& payload)
{
    std::lock_guard<std::mutex> lock(_mutex);
    auto instance = requireInstance(id);
    if (instance.state != State::waiting)
        throw Poco::IllegalStateException("Workflow instance is not waiting", id);
    if (event.empty() || instance.waitingEvent != event)
        throw Poco::InvalidArgumentException("Unexpected workflow event", event);
    auto& definition = requireDefinition(instance.type);
    if (definition.descriptor.version != instance.definitionVersion)
        throw Poco::IllegalStateException("Workflow definition version mismatch", instance.type);
    instance.state = State::queued;
    instance.waitingEvent.clear();
    instance.signalPayload = payload;
    persist(instance);
    return run(std::move(instance), definition);
}

Instance WorkflowEngine::resume(const std::string& id)
{
    std::lock_guard<std::mutex> lock(_mutex);
    auto instance = requireInstance(id);
    if (instance.state != State::interrupted && instance.state != State::retryScheduled)
        throw Poco::IllegalStateException("Workflow instance cannot be resumed", id);
    auto& definition = requireDefinition(instance.type);
    if (definition.descriptor.version != instance.definitionVersion)
        throw Poco::IllegalStateException("Workflow definition version mismatch", instance.type);
    if (instance.compensationRequired)
    {
        auto code = instance.lastErrorCode;
        auto message = instance.lastErrorMessage;
        return failAndCompensate(std::move(instance), definition,
                                 std::move(code), std::move(message));
    }
    return run(std::move(instance), definition);
}

Instance WorkflowEngine::cancel(const std::string& id)
{
    std::lock_guard<std::mutex> lock(_mutex);
    auto instance = requireInstance(id);
    if (terminal(instance.state)) return instance;
    auto& definition = requireDefinition(instance.type);
    if (definition.descriptor.version != instance.definitionVersion)
        throw Poco::IllegalStateException("Workflow definition version mismatch", instance.type);
    instance.cancellationRequested = true;
    if (instance.completedSteps.empty())
    {
        instance.state = State::cancelled;
        instance.lastErrorCode = "cancelled";
        instance.lastErrorMessage = "Workflow cancelled";
        instance.waitingEvent.clear();
        instance.retryAtMicroseconds = 0;
        persist(instance);
        return instance;
    }
    return failAndCompensate(std::move(instance), definition,
                             "cancelled", "Workflow cancelled");
}

std::size_t WorkflowEngine::runDue()
{
    std::lock_guard<std::mutex> lock(_mutex);
    auto due = _store->due(nowMicroseconds());
    std::size_t executed = 0;
    for (auto& instance : due)
    {
        const auto found = _definitions.find(instance.type);
        if (found == _definitions.end() ||
            found->second.descriptor.version != instance.definitionVersion)
            continue;
        run(std::move(instance), found->second);
        ++executed;
    }
    return executed;
}

Instance WorkflowEngine::get(const std::string& id) const
{
    std::lock_guard<std::mutex> lock(_mutex);
    return requireInstance(id);
}

std::vector<Instance> WorkflowEngine::list() const
{
    std::lock_guard<std::mutex> lock(_mutex);
    return _store->list();
}

std::vector<std::string> WorkflowEngine::definitionTypes() const
{
    std::lock_guard<std::mutex> lock(_mutex);
    std::vector<std::string> result;
    result.reserve(_definitions.size());
    for (const auto& [type, definition] : _definitions) result.push_back(type);
    std::sort(result.begin(), result.end());
    return result;
}

Instance WorkflowEngine::run(Instance instance, AttachedDefinition& definition)
{
    while (instance.currentStep < definition.descriptor.steps.size())
    {
        if (instance.cancellationRequested)
            return failAndCompensate(std::move(instance), definition,
                                     "cancelled", "Workflow cancelled");

        instance.state = State::running;
        instance.retryAtMicroseconds = 0;
        instance.waitingEvent.clear();
        ++instance.attempt;
        persist(instance); // Durable checkpoint before invoking user code.

        StepResult result;
        try
        {
            result = definition.service->execute(
                definition.descriptor.steps[instance.currentStep], contextFor(instance));
        }
        catch (const Poco::Exception& exception)
        {
            result = StepResult::failed("provider-exception", exception.displayText());
        }
        catch (const std::exception& exception)
        {
            result = StepResult::failed("provider-exception", exception.what());
        }
        catch (...)
        {
            result = StepResult::failed("provider-exception", "Unknown provider exception");
        }

        switch (result.action)
        {
        case StepAction::complete:
            instance.completedSteps.push_back(
                definition.descriptor.steps[instance.currentStep]);
            ++instance.currentStep;
            instance.attempt = 0;
            instance.signalPayload.clear();
            instance.lastErrorCode.clear();
            instance.lastErrorMessage.clear();
            persist(instance);
            break;

        case StepAction::waitForEvent:
            if (result.event.empty())
                return failAndCompensate(std::move(instance), definition,
                                         "invalid-wait-event", "Wait event is empty");
            instance.state = State::waiting;
            instance.waitingEvent = std::move(result.event);
            instance.signalPayload.clear();
            instance.retryAtMicroseconds = 0;
            persist(instance);
            return instance;

        case StepAction::retry:
            if (result.retryDelay.count() < 0)
                return failAndCompensate(std::move(instance), definition,
                                         "invalid-retry-delay", "Retry delay is negative");
            if (instance.attempt >= definition.descriptor.maximumAttempts)
                return failAndCompensate(
                    std::move(instance), definition,
                    result.errorCode.empty() ? "attempts-exhausted" : result.errorCode,
                    result.errorMessage.empty() ? "Workflow step attempts exhausted"
                                                : result.errorMessage);
            instance.state = State::retryScheduled;
            instance.retryAtMicroseconds = nowMicroseconds() +
                static_cast<Poco::Int64>(result.retryDelay.count()) * 1000;
            instance.lastErrorCode = std::move(result.errorCode);
            instance.lastErrorMessage = std::move(result.errorMessage);
            persist(instance);
            return instance;

        case StepAction::fail:
            return failAndCompensate(std::move(instance), definition,
                                     std::move(result.errorCode),
                                     std::move(result.errorMessage));
        }
    }

    instance.state = State::succeeded;
    instance.attempt = 0;
    instance.retryAtMicroseconds = 0;
    instance.waitingEvent.clear();
    instance.signalPayload.clear();
    instance.compensationRequired = false;
    persist(instance);
    return instance;
}

Instance WorkflowEngine::failAndCompensate(Instance instance,
                                           AttachedDefinition& definition,
                                           std::string code,
                                           std::string message)
{
    instance.lastErrorCode = std::move(code);
    instance.lastErrorMessage = std::move(message);
    if (instance.failureCode.empty())
    {
        instance.failureCode = instance.lastErrorCode;
        instance.failureMessage = instance.lastErrorMessage;
    }
    instance.waitingEvent.clear();
    instance.retryAtMicroseconds = 0;
    instance.compensationRequired = !instance.completedSteps.empty();
    instance.state = State::compensating;
    persist(instance); // Durable checkpoint before compensation callbacks.

    try
    {
        for (auto iterator = instance.completedSteps.rbegin();
             iterator != instance.completedSteps.rend(); ++iterator)
        {
            if (std::find(instance.compensatedSteps.begin(),
                          instance.compensatedSteps.end(), *iterator) !=
                instance.compensatedSteps.end())
                continue;
            definition.service->compensate(*iterator, contextFor(instance));
            instance.compensatedSteps.push_back(*iterator);
            persist(instance);
        }
    }
    catch (const Poco::Exception& exception)
    {
        instance.state = State::interrupted;
        instance.lastErrorCode = "compensation-failed";
        instance.lastErrorMessage = exception.displayText();
        persist(instance);
        return instance;
    }
    catch (const std::exception& exception)
    {
        instance.state = State::interrupted;
        instance.lastErrorCode = "compensation-failed";
        instance.lastErrorMessage = exception.what();
        persist(instance);
        return instance;
    }
    catch (...)
    {
        instance.state = State::interrupted;
        instance.lastErrorCode = "compensation-failed";
        instance.lastErrorMessage = "Unknown compensation exception";
        persist(instance);
        return instance;
    }

    instance.compensationRequired = false;
    instance.compensated = true;
    instance.state = instance.cancellationRequested ? State::cancelled : State::failed;
    instance.lastErrorCode = instance.failureCode;
    instance.lastErrorMessage = instance.failureMessage;
    persist(instance);
    return instance;
}

void WorkflowEngine::persist(Instance& instance)
{
    instance.updatedMicroseconds = nowMicroseconds();
    ++instance.revision;
    _store->save(instance);
}

WorkflowEngine::AttachedDefinition& WorkflowEngine::requireDefinition(const std::string& type)
{
    const auto found = _definitions.find(type);
    if (found == _definitions.end())
        throw Poco::NotFoundException("Workflow definition is not attached", type);
    return found->second;
}

Instance WorkflowEngine::requireInstance(const std::string& id) const
{
    const auto instance = _store->find(id);
    if (!instance) throw Poco::NotFoundException("Workflow instance was not found", id);
    return *instance;
}
} // namespace PocoDDS::Workflow
