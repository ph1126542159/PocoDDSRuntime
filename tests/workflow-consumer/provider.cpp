#include "PocoDDS/Workflow/WorkflowDefinitionService.h"

class InstalledProvider final : public PocoDDS::Workflow::WorkflowDefinitionService
{
public:
    PocoDDS::Workflow::DefinitionDescriptor descriptor() const override
    {
        return {"installed-provider", "1.0.0", {"execute"}, 2};
    }

    PocoDDS::Workflow::StepResult execute(
        const std::string&, const PocoDDS::Workflow::StepContext&) override
    {
        return PocoDDS::Workflow::StepResult::completed();
    }

    void compensate(const std::string&,
                    const PocoDDS::Workflow::StepContext&) override
    {
    }
};

Poco::AutoPtr<PocoDDS::Workflow::WorkflowDefinitionService> makeInstalledProvider()
{
    return new InstalledProvider;
}
