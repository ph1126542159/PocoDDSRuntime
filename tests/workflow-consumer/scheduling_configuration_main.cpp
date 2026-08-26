#include <PocoDDS/Scheduling/ScheduleConfigurationParticipant.h>

#include <chrono>

int main()
{
    PocoDDS::Scheduling::TaskSpec spec;
    spec.id = "consumer.schedule";
    spec.owner = "consumer.bundle";
    spec.enabled = false;
    spec.interval = std::chrono::milliseconds(100);
    spec.rejectionBackoff = std::chrono::milliseconds(100);
    PocoDDS::Scheduling::ScheduleConfigurationBinding binding{
        "consumer-scheduler", spec.id, spec.owner,
        "consumer.schedulerEnabled", "consumer.schedulerIntervalMilliseconds",
        "consumer.schedulerJitterMilliseconds"};
    return PocoDDS::Scheduling::validateTaskSpec(spec).empty() &&
        !binding.participantId.empty() ? 0 : 1;
}
