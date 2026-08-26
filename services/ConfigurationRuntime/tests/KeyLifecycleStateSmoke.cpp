#include "KeyLifecycleState.h"

#include <iostream>

int main()
{
    using namespace PocoDDS::ConfigTransaction;
    KeyLifecycleState state;
    ConfigurationParticipantCatalogSnapshot catalog;
    catalog.participants.push_back(
        {"workflow-scheduler", {"pdr.workflow"}, {}, {}, 1});
    const std::vector<AdmittedParticipantObservation> observations = {{
        "workflow-scheduler", "pdr.service.workflowRuntime",
        "pdr.configuration.participant.workflowScheduler",
    }};
    const std::string valid = R"({
      "schemaVersion":1,
      "entries":[{
        "id":"PDR-CFG-0001",
        "participantId":"workflow-scheduler",
        "operation":"rename",
        "sourceKey":"pdr.workflow.oldInterval",
        "replacementKey":"pdr.workflow.schedulerIntervalMilliseconds",
        "deprecatedSince":"0.1.0",
        "removalAllowedFrom":"1.0.0"
      }]
    })";
    state.replace(
        {{"pdr.service.workflowRuntime", true, valid}}, catalog, observations,
        "0.1.0");
    const auto published = state.snapshot();
    if (!published.ready || published.generation != 1 ||
        published.declarationCount != 1 ||
        published.entries.size() != 1 ||
        published.entries[0].status != "published" ||
        state.health().status != PocoDDS::Health::Status::up) return 1;

    state.replace(
        {{"pdr.service.workflowRuntime", true, valid}}, {}, {}, "0.1.0");
    if (state.snapshot().ready ||
        state.snapshot().entries[0].status != "mismatched" ||
        state.health().status != PocoDDS::Health::Status::degraded) return 2;

    state.replace(
        {{"pdr.service.workflowRuntime", false, "{"}}, {}, {}, "0.1.0");
    const auto inactiveInvalid = state.snapshot();
    if (!inactiveInvalid.ready || inactiveInvalid.issues.size() != 1 ||
        inactiveInvalid.issues[0].blocking) return 3;

    const std::string cycle = R"({
      "schemaVersion":1,
      "entries":[
        {"id":"PDR-CFG-0001","participantId":"workflow-scheduler",
         "operation":"rename","sourceKey":"pdr.workflow.a",
         "replacementKey":"pdr.workflow.b","deprecatedSince":"0.1.0",
         "removalAllowedFrom":"1.0.0"},
        {"id":"PDR-CFG-0002","participantId":"workflow-scheduler",
         "operation":"rename","sourceKey":"pdr.workflow.b",
         "replacementKey":"pdr.workflow.a","deprecatedSince":"0.1.0",
         "removalAllowedFrom":"1.0.0"}
      ]
    })";
    state.replace(
        {{"pdr.service.workflowRuntime", true, cycle}}, catalog, observations,
        "0.1.0");
    if (state.snapshot().ready || state.snapshot().issues.size() != 1 ||
        state.snapshot().issues[0].code !=
            "configuration-key-lifecycle-cycle") return 4;

    state.reset();
    if (!state.snapshot().ready || state.snapshot().generation != 0) return 5;
    std::cout << "PDR_CONFIGURATION_KEY_LIFECYCLE_STATE_PASS "
                 "published=1 mismatch=1 inactive-diagnostic=1 cycle=1\n";
    return 0;
}
