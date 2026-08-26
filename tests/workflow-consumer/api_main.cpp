#include "PocoDDS/Workflow/WorkflowDefinitionService.h"

#include <Poco/AutoPtr.h>

Poco::AutoPtr<PocoDDS::Workflow::WorkflowDefinitionService> makeInstalledProvider();

int main()
{
    auto provider = makeInstalledProvider();
    PocoDDS::Workflow::StepContext context;
    return provider->execute("execute", context).action ==
                   PocoDDS::Workflow::StepAction::complete
               ? 0
               : 1;
}
