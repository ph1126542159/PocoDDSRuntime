#include "ParticipantAdmissionState.h"

#include <iostream>
#include <string>

int main()
{
    using namespace PocoDDS::ConfigTransaction;
    ParticipantAdmissionState state;

    const auto empty = state.snapshot();
    if (empty.generation != 0 || empty.overflow ||
        !empty.rejectedParticipants.empty() ||
        state.health().status != PocoDDS::Health::Status::up) return 1;

    state.recordFailure("service-1", "workflow-scheduler",
                        "participant-ownership-conflict");
    const auto rejected = state.snapshot();
    if (rejected.generation != 1 || rejected.overflow ||
        rejected.rejectedParticipants.size() != 1 ||
        rejected.rejectedParticipants[0].participantId != "workflow-scheduler" ||
        rejected.rejectedParticipants[0].code !=
            "participant-ownership-conflict" ||
        rejected.rejectedParticipants[0].observationGeneration != 1 ||
        state.health().status != PocoDDS::Health::Status::degraded ||
        state.health().code !=
            "PDR-HEALTH-CONFIGURATION-PARTICIPANT-ADMISSION-REJECTED") return 2;

    state.recordFailure("service-1", "workflow-scheduler",
                        "participant-ownership-conflict");
    if (state.snapshot().generation != 1) return 3;

    state.recordFailure("service-1", "SECRET VALUE THAT MUST NOT LEAK",
                        "raw exception text must not leak");
    const auto sanitized = state.snapshot();
    if (sanitized.generation != 2 ||
        sanitized.rejectedParticipants[0].participantId != "unknown" ||
        sanitized.rejectedParticipants[0].code !=
            "participant-registration-failed") return 4;

    state.recordFailure(std::string(1024, 'x'), "0-invalid-id",
                        "participant-contract-invalid");
    const auto boundedStrings = state.snapshot();
    if (boundedStrings.rejectedParticipants.size() != 2 ||
        boundedStrings.rejectedParticipants[0].participantId != "unknown") return 5;
    state.clear(std::string(1024, 'x'));

    state.clear("unknown-service");
    if (state.snapshot().generation != 4) return 6;
    state.clear("service-1");
    if (state.snapshot().generation != 5 ||
        !state.snapshot().rejectedParticipants.empty() ||
        state.health().status != PocoDDS::Health::Status::up) return 7;

    for (std::size_t index = 0;
         index < ParticipantAdmissionState::MAX_RETAINED_FAILURES + 1;
         ++index)
        state.recordFailure("service-" + std::to_string(index),
                            "participant-" + std::to_string(index),
                            "participant-contract-invalid");
    const auto overflow = state.snapshot();
    if (!overflow.overflow || overflow.rejectedParticipants.size() !=
            ParticipantAdmissionState::MAX_RETAINED_FAILURES ||
        state.health().code !=
            "PDR-HEALTH-CONFIGURATION-PARTICIPANT-ADMISSION-OVERFLOW") return 8;
    state.reset();
    if (state.snapshot().overflow || !state.snapshot().rejectedParticipants.empty() ||
        state.health().status != PocoDDS::Health::Status::up) return 9;

    std::cout << "PDR_CONFIGURATION_PARTICIPANT_ADMISSION_PASS "
                 "rejected=1 readinessDegraded=1 recovery=1 sanitized=1 bounded=1\n";
    return 0;
}
