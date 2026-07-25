#pragma once

#include <chrono>
#include <functional>
#include <memory>
#include <optional>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

namespace PocoDDS::Application
{
struct Error
{
    std::string code;
    std::string message;
    bool retryable{false};
};

template <typename T>
class Result
{
public:
    static Result success(T value) { return Result(std::move(value)); }
    static Result failure(Error error) { return Result(std::move(error)); }

    [[nodiscard]] bool hasValue() const noexcept { return _value.has_value(); }
    [[nodiscard]] explicit operator bool() const noexcept { return hasValue(); }
    [[nodiscard]] const T& value() const { return _value.value(); }
    [[nodiscard]] const Error& error() const { return _error.value(); }

private:
    explicit Result(T value): _value(std::move(value)) {}
    explicit Result(Error error): _error(std::move(error)) {}
    std::optional<T> _value;
    std::optional<Error> _error;
};

struct CommandContext
{
    std::string requestId;
    std::string traceId;
    std::string deviceId;
    std::chrono::steady_clock::time_point deadline{};

    [[nodiscard]] bool expired() const noexcept
    {
        return deadline != std::chrono::steady_clock::time_point{} &&
               std::chrono::steady_clock::now() >= deadline;
    }
};

struct WorkflowEvent
{
    std::string type;
    std::string payload;
};

enum class WorkflowState
{
    idle,
    running,
    succeeded,
    failed,
    cancelled
};

struct WorkflowStep
{
    std::string id;
    std::function<Result<WorkflowState>(const CommandContext&)> execute;
    std::function<void(const CommandContext&)> compensate;
};

class IWorkflow
{
public:
    virtual ~IWorkflow() = default;
    virtual Result<WorkflowState> start(const CommandContext& context) = 0;
    virtual Result<WorkflowState> handle(const WorkflowEvent& event) = 0;
    virtual Result<WorkflowState> cancel(const CommandContext& context) = 0;
    [[nodiscard]] virtual WorkflowState state() const noexcept = 0;
};

class WorkflowRegistry
{
public:
    using Factory = std::function<std::unique_ptr<IWorkflow>()>;

    bool registerFactory(std::string id, Factory factory)
    {
        return _factories.emplace(std::move(id), std::move(factory)).second;
    }

    [[nodiscard]] std::unique_ptr<IWorkflow> create(const std::string& id) const
    {
        const auto found = _factories.find(id);
        return found == _factories.end() ? nullptr : found->second();
    }

private:
    std::unordered_map<std::string, Factory> _factories;
};

class SequentialWorkflow final : public IWorkflow
{
public:
    explicit SequentialWorkflow(std::vector<WorkflowStep> steps): _steps(std::move(steps)) {}

    Result<WorkflowState> start(const CommandContext& context) override
    {
        _state = WorkflowState::running;
        _completed = 0;
        for (const auto& step : _steps)
        {
            if (context.expired())
                return failAndCompensate(context,
                    {"deadline_exceeded", "workflow deadline expired", false});
            const auto result = step.execute(context);
            if (!result)
                return failAndCompensate(context, result.error());
            ++_completed;
        }
        _state = WorkflowState::succeeded;
        return Result<WorkflowState>::success(_state);
    }

    Result<WorkflowState> handle(const WorkflowEvent&) override
    {
        return Result<WorkflowState>::success(_state);
    }

    Result<WorkflowState> cancel(const CommandContext& context) override
    {
        compensate(context);
        _state = WorkflowState::cancelled;
        return Result<WorkflowState>::success(_state);
    }

    [[nodiscard]] WorkflowState state() const noexcept override { return _state; }
    [[nodiscard]] std::size_t completedSteps() const noexcept { return _completed; }

private:
    Result<WorkflowState> failAndCompensate(const CommandContext& context, Error error)
    {
        compensate(context);
        _state = WorkflowState::failed;
        return Result<WorkflowState>::failure(std::move(error));
    }

    void compensate(const CommandContext& context)
    {
        while (_completed > 0)
        {
            --_completed;
            if (_steps[_completed].compensate)
                _steps[_completed].compensate(context);
        }
    }

    std::vector<WorkflowStep> _steps;
    std::size_t _completed{0};
    WorkflowState _state{WorkflowState::idle};
};
}
