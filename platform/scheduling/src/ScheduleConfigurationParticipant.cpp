#include "PocoDDS/Scheduling/ScheduleConfigurationParticipant.h"

#include <Poco/Exception.h>

#include <algorithm>
#include <charconv>
#include <chrono>
#include <cctype>
#include <stdexcept>
#include <utility>

namespace PocoDDS::Scheduling
{
namespace
{
std::string required(const ConfigTransaction::Values& values,
                     const std::string& key)
{
    const auto found = values.find(key);
    if (found == values.end()) throw std::invalid_argument("missing configuration key " + key);
    return found->second;
}

bool parseEnabled(const std::string& value, const std::string& key)
{
    std::string normalized = value;
    std::transform(normalized.begin(), normalized.end(), normalized.begin(),
        [](unsigned char character) { return static_cast<char>(std::tolower(character)); });
    if (normalized == "true" || normalized == "1" || normalized == "yes" || normalized == "on")
        return true;
    if (normalized == "false" || normalized == "0" || normalized == "no" || normalized == "off")
        return false;
    throw std::invalid_argument(key + " must be a boolean");
}

std::chrono::milliseconds parseMilliseconds(const std::string& value,
                                             const std::string& key)
{
    unsigned long long parsed = 0;
    const auto conversion = std::from_chars(value.data(), value.data() + value.size(), parsed);
    if (conversion.ec != std::errc{} || conversion.ptr != value.data() + value.size())
        throw std::invalid_argument(key + " must be an unsigned integer");
    if (parsed > 86400000ULL)
        throw std::invalid_argument(key + " must not exceed 86400000");
    return std::chrono::milliseconds(parsed);
}

ConfigTransaction::ParticipantResult rejected(const std::exception& exception)
{
    return ConfigTransaction::ParticipantResult::rejected(
        "invalid-schedule-configuration", exception.what());
}
} // namespace

ScheduleConfigurationParticipant::ScheduleConfigurationParticipant(
    ScheduleConfigurationBinding binding, SchedulerService::Ptr scheduler)
    : _binding(std::move(binding)), _scheduler(std::move(scheduler))
{
    if (!_scheduler) throw Poco::InvalidArgumentException("Scheduler service is required");
    if (_binding.participantId.empty() || _binding.taskId.empty() || _binding.owner.empty() ||
        _binding.enabledKey.empty() || _binding.intervalMillisecondsKey.empty() ||
        _binding.jitterMillisecondsKey.empty())
        throw Poco::InvalidArgumentException(
            "Schedule configuration binding fields must not be empty");
}

ConfigTransaction::ParticipantDescriptor
ScheduleConfigurationParticipant::descriptor() const
{
    return {_binding.participantId,
            {_binding.enabledKey, _binding.intervalMillisecondsKey,
             _binding.jitterMillisecondsKey}, {}};
}

TaskSpec ScheduleConfigurationParticipant::configuredSpec(
    const ConfigTransaction::Values& values) const
{
    const auto current = _scheduler->snapshot(_binding.taskId);
    if (!current) throw std::runtime_error("scheduled task is not registered: " + _binding.taskId);
    if (current->spec.owner != _binding.owner)
        throw std::runtime_error("scheduled task owner does not match configuration binding");

    auto spec = current->spec;
    spec.enabled = parseEnabled(required(values, _binding.enabledKey), _binding.enabledKey);
    spec.interval = parseMilliseconds(
        required(values, _binding.intervalMillisecondsKey),
        _binding.intervalMillisecondsKey);
    spec.jitter = parseMilliseconds(
        required(values, _binding.jitterMillisecondsKey),
        _binding.jitterMillisecondsKey);
    spec.initialDelay = spec.interval;
    spec.rejectionBackoff = std::min(
        spec.interval,
        std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::hours(1)));
    const auto error = validateTaskSpec(spec);
    if (!error.empty()) throw std::invalid_argument(error);
    return spec;
}

ConfigTransaction::ParticipantResult ScheduleConfigurationParticipant::validate(
    const ConfigTransaction::Values& values) const
{
    try
    {
        static_cast<void>(configuredSpec(values));
        return ConfigTransaction::ParticipantResult::accepted();
    }
    catch (const std::exception& exception)
    {
        return rejected(exception);
    }
}

ConfigTransaction::ParticipantResult ScheduleConfigurationParticipant::apply(
    const ConfigTransaction::Values& values)
{
    try
    {
        const auto result = _scheduler->reconfigure(configuredSpec(values));
        if (result.status == ReconfigurationStatus::reconfigured)
            return ConfigTransaction::ParticipantResult::accepted();
        return ConfigTransaction::ParticipantResult::rejected(
            "schedule-reconfiguration-failed",
            std::string(toString(result.status)) + ": " + result.message);
    }
    catch (const std::exception& exception)
    {
        return rejected(exception);
    }
}

ConfigTransaction::ParticipantResult ScheduleConfigurationParticipant::preflight(
    const ConfigTransaction::Context& context)
{
    return validate(context.candidate.values);
}

ConfigTransaction::ParticipantResult ScheduleConfigurationParticipant::commit(
    const ConfigTransaction::Context& context)
{
    return apply(context.candidate.values);
}

ConfigTransaction::ParticipantResult ScheduleConfigurationParticipant::rollback(
    const ConfigTransaction::Context& context)
{
    return apply(context.previous.values);
}
} // namespace PocoDDS::Scheduling
