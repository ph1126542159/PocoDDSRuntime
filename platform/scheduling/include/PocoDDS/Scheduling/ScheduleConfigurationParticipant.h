#pragma once

#include "PocoDDS/Scheduling/ConfigurationExport.h"
#include "PocoDDS/Scheduling/SchedulerService.h"

#include "PocoDDS/ConfigTransaction/ConfigurationParticipantService.h"

#include <string>

namespace PocoDDS::Scheduling
{
struct ScheduleConfigurationBinding
{
    std::string participantId;
    std::string taskId;
    std::string owner;
    std::string enabledKey;
    std::string intervalMillisecondsKey;
    std::string jitterMillisecondsKey;
};

class PDR_SCHEDULING_CONFIGURATION_API ScheduleConfigurationParticipant final
    : public ConfigTransaction::ConfigurationParticipantService
{
public:
    ScheduleConfigurationParticipant(ScheduleConfigurationBinding binding,
                                     SchedulerService::Ptr scheduler);

    ConfigTransaction::ParticipantDescriptor descriptor() const override;
    ConfigTransaction::ParticipantResult preflight(
        const ConfigTransaction::Context& context) override;
    ConfigTransaction::ParticipantResult commit(
        const ConfigTransaction::Context& context) override;
    ConfigTransaction::ParticipantResult rollback(
        const ConfigTransaction::Context& context) override;

private:
    ConfigTransaction::ParticipantResult apply(
        const ConfigTransaction::Values& values);
    ConfigTransaction::ParticipantResult validate(
        const ConfigTransaction::Values& values) const;
    TaskSpec configuredSpec(const ConfigTransaction::Values& values) const;

    ScheduleConfigurationBinding _binding;
    SchedulerService::Ptr _scheduler;
};
} // namespace PocoDDS::Scheduling
