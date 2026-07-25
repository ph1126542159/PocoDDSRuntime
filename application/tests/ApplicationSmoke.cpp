#include "PocoDDS/Application/Application.h"

#include <iostream>
#include <memory>

namespace
{
class ProbeWorkflow final : public PocoDDS::Application::IWorkflow
{
public:
    PocoDDS::Application::Result<PocoDDS::Application::WorkflowState> start(
        const PocoDDS::Application::CommandContext& context) override
    {
        if (context.expired())
            return PocoDDS::Application::Result<PocoDDS::Application::WorkflowState>::failure(
                {"deadline_exceeded", "command deadline expired", false});
        _state = PocoDDS::Application::WorkflowState::running;
        return PocoDDS::Application::Result<PocoDDS::Application::WorkflowState>::success(_state);
    }

    PocoDDS::Application::Result<PocoDDS::Application::WorkflowState> handle(
        const PocoDDS::Application::WorkflowEvent& event) override
    {
        _state = event.type == "complete" ? PocoDDS::Application::WorkflowState::succeeded
                                           : PocoDDS::Application::WorkflowState::failed;
        return PocoDDS::Application::Result<PocoDDS::Application::WorkflowState>::success(_state);
    }

    PocoDDS::Application::Result<PocoDDS::Application::WorkflowState> cancel(
        const PocoDDS::Application::CommandContext&) override
    {
        _state = PocoDDS::Application::WorkflowState::cancelled;
        return PocoDDS::Application::Result<PocoDDS::Application::WorkflowState>::success(_state);
    }

    PocoDDS::Application::WorkflowState state() const noexcept override { return _state; }

private:
    PocoDDS::Application::WorkflowState _state{PocoDDS::Application::WorkflowState::idle};
};
}

int main()
{
    PocoDDS::Application::WorkflowRegistry registry;
    if (!registry.registerFactory("probe", [] { return std::make_unique<ProbeWorkflow>(); }))
        return 1;
    auto workflow = registry.create("probe");
    PocoDDS::Application::CommandContext context;
    if (!workflow || !workflow->start(context) ||
        !workflow->handle({"complete", "{}"}) ||
        workflow->state() != PocoDDS::Application::WorkflowState::succeeded)
        return 2;
    int compensationCount = 0;
    PocoDDS::Application::SequentialWorkflow sequence({
        {"prepare",
         [](const auto&) {
             return PocoDDS::Application::Result<PocoDDS::Application::WorkflowState>::success(
                 PocoDDS::Application::WorkflowState::running);
         },
         [&](const auto&) { ++compensationCount; }},
        {"execute",
         [](const auto&) {
             return PocoDDS::Application::Result<PocoDDS::Application::WorkflowState>::failure(
                 {"probe_failure", "expected", false});
         },
         {}}
    });
    if (sequence.start(context) || sequence.state() != PocoDDS::Application::WorkflowState::failed ||
        compensationCount != 1)
        return 3;
    std::cout << "APPLICATION_SMOKE_PASS\n";
}
