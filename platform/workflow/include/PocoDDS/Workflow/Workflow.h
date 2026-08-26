#pragma once

#include <Poco/Types.h>

#include <chrono>
#include <cstddef>
#include <string>
#include <utility>
#include <vector>

namespace PocoDDS::Workflow
{
enum class State
{
    queued,
    running,
    waiting,
    retryScheduled,
    compensating,
    interrupted,
    succeeded,
    failed,
    cancelled
};

enum class StepAction
{
    complete,
    waitForEvent,
    retry,
    fail
};

struct DefinitionDescriptor
{
    std::string type;
    std::string version;
    std::vector<std::string> steps;
    unsigned maximumAttempts{3};
};

struct StepContext
{
    std::string instanceId;
    std::string businessKey;
    std::string workflowInput;
    std::string signalPayload;
    unsigned attempt{1};
};

struct StepResult
{
    StepAction action{StepAction::complete};
    std::string output;
    std::string event;
    std::chrono::milliseconds retryDelay{0};
    std::string errorCode;
    std::string errorMessage;

    static StepResult completed(std::string output = {})
    {
        StepResult result;
        result.action = StepAction::complete;
        result.output = std::move(output);
        return result;
    }

    static StepResult waiting(std::string event)
    {
        StepResult result;
        result.action = StepAction::waitForEvent;
        result.event = std::move(event);
        return result;
    }

    static StepResult retryAfter(std::chrono::milliseconds delay,
                                 std::string code,
                                 std::string message)
    {
        StepResult result;
        result.action = StepAction::retry;
        result.retryDelay = delay;
        result.errorCode = std::move(code);
        result.errorMessage = std::move(message);
        return result;
    }

    static StepResult failed(std::string code, std::string message)
    {
        StepResult result;
        result.action = StepAction::fail;
        result.errorCode = std::move(code);
        result.errorMessage = std::move(message);
        return result;
    }
};

struct Instance
{
    std::string id;
    std::string type;
    std::string definitionVersion;
    std::string businessKey;
    std::string input;
    State state{State::queued};
    std::size_t currentStep{0};
    std::vector<std::string> completedSteps;
    std::vector<std::string> compensatedSteps;
    unsigned attempt{0};
    std::string waitingEvent;
    std::string signalPayload;
    Poco::Int64 retryAtMicroseconds{0};
    std::string failureCode;
    std::string failureMessage;
    std::string lastErrorCode;
    std::string lastErrorMessage;
    bool compensationRequired{false};
    bool cancellationRequested{false};
    bool compensated{false};
    Poco::Int64 createdMicroseconds{0};
    Poco::Int64 updatedMicroseconds{0};
    Poco::UInt64 revision{0};
};

const char* stateName(State state) noexcept;
State parseState(const std::string& value);
bool terminal(State state) noexcept;
} // namespace PocoDDS::Workflow
