#include "ParticipantExpectationState.h"

#include <iostream>
#include <string>
#include <vector>

int main()
{
    using namespace PocoDDS::ConfigTransaction;
    ParticipantExpectationState state;
    ConfigurationParticipantCatalogSnapshot catalog;
    catalog.participants.push_back(
        {"workflow-scheduler", {"pdr.workflow.schedulerEnabled"}, {}, {}, 1});
    const std::string valid = R"({
      "schemaVersion":1,
      "participants":[{
        "id":"workflow-scheduler",
        "serviceName":"pdr.configuration.participant.workflowScheduler",
        "ownedPrefixes":["pdr.workflow.schedulerEnabled"],
        "after":[]
      }]
    })";

    state.replace({{"pdr.service.workflowRuntime", true, valid}}, catalog, {});
    const auto missing = state.snapshot();
    if (missing.ready || missing.generation != 1 ||
        missing.expectations.size() != 1 ||
        missing.expectations[0].status != "missing" ||
        state.health().status != PocoDDS::Health::Status::degraded) return 1;

    state.replace(
        {{"pdr.service.workflowRuntime", true, valid}}, catalog,
        {{"workflow-scheduler", "pdr.service.workflowRuntime",
          "pdr.configuration.participant.workflowScheduler"}});
    const auto satisfied = state.snapshot();
    if (!satisfied.ready || satisfied.generation != 2 ||
        satisfied.expectations[0].status != "satisfied" ||
        state.health().code != "PDR-HEALTH-CONFIGURATION-PARTICIPANTS-UP") return 2;
    state.replace(
        {{"pdr.service.workflowRuntime", true, valid}}, catalog,
        {{"workflow-scheduler", "pdr.service.workflowRuntime",
          "pdr.configuration.participant.workflowScheduler"}});
    if (state.snapshot().generation != 2) return 3;

    state.replace(
        {{"pdr.service.workflowRuntime", true, valid}}, catalog,
        {{"workflow-scheduler", "pdr.service.other",
          "pdr.configuration.participant.workflowScheduler"}});
    if (state.snapshot().ready ||
        state.snapshot().expectations[0].status != "mismatched") return 4;

    state.replace({{"pdr.service.workflowRuntime", false, valid}}, catalog, {});
    if (!state.snapshot().ready ||
        state.snapshot().expectations[0].status != "inactive") return 5;

    state.replace({{"unsafe-owner", true,
                    "{\"schemaVersion\":1,\"participants\":[{\"id\":\"secret\","
                    "\"serviceName\":\"secret\",\"ownedPrefixes\":[\"SECRET VALUE\"],"
                    "\"after\":[],\"rawException\":\"must-not-leak\"}]}"}},
                  catalog, {});
    const auto invalid = state.snapshot();
    if (invalid.ready || invalid.issues.size() != 1 ||
        invalid.issues[0].code != "participant-declaration-invalid" ||
        state.health().code !=
            "PDR-HEALTH-CONFIGURATION-PARTICIPANT-DECLARATION-INVALID") return 6;

    const std::string cycle = R"({
      "schemaVersion":1,
      "participants":[
        {"id":"cycle-a","serviceName":"pdr.configuration.participant.cycleA",
         "ownedPrefixes":["cycle.a"],"after":["cycle-b"]},
        {"id":"cycle-b","serviceName":"pdr.configuration.participant.cycleB",
         "ownedPrefixes":["cycle.b"],"after":["cycle-a"]}
      ]
    })";
    const std::string cycleDependent = R"({
      "schemaVersion":1,
      "participants":[
        {"id":"cycle-dependent","serviceName":"pdr.configuration.participant.cycleDependent",
         "ownedPrefixes":["cycle.dependent"],"after":["cycle-a"]}
      ]
    })";
    state.replace({{"cycle-owner", true, cycle},
                   {"cycle-dependent-owner", true, cycleDependent}}, {}, {});
    const auto cyclic = state.snapshot();
    if (cyclic.ready || cyclic.issues.size() != 1 ||
        cyclic.issues[0].owner != "cycle-owner") return 7;

    state.reset();
    if (!state.snapshot().ready || state.snapshot().generation != 0) return 8;
    std::cout << "PDR_CONFIGURATION_PARTICIPANT_EXPECTATION_PASS "
                 "missing=1 satisfied=1 mismatch=1 inactive=1 invalid=1 sanitized=1 "
                 "cycle=1 cycle-scope=1\n";
    return 0;
}
