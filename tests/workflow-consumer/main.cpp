#include "PocoDDS/Workflow/Workflow.h"
#include "PocoDDS/Workflow/WorkflowDefinitionService.h"
#include "PocoDDS/StoreForward/StoreForward.h"

#include <Poco/AutoPtr.h>

#include <iostream>

Poco::AutoPtr<PocoDDS::Workflow::WorkflowDefinitionService> makeInstalledProvider();

int main()
{
    const auto provider = makeInstalledProvider();
    const auto descriptor = provider->descriptor();
    if (descriptor.type != "installed-provider" || descriptor.steps.size() != 1)
        return 1;
    if (std::string(PocoDDS::Workflow::stateName(
            PocoDDS::Workflow::State::retryScheduled)) != "retry-scheduled")
        return 2;
    if (std::string(PocoDDS::StoreForward::stateName(
            PocoDDS::StoreForward::State::deadLetter)) != "dead-letter")
        return 3;
    std::cout << "installed WorkflowAPI/WorkflowCore: PASS\n";
    return 0;
}
