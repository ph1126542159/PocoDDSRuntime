#include "ParticipantAdmissionState.h"

#include <algorithm>
#include <cctype>
#include <functional>
#include <utility>
#include <vector>

namespace PocoDDS::ConfigTransaction
{
namespace
{
constexpr const char* UNKNOWN_PARTICIPANT = "unknown";
constexpr const char* FALLBACK_CODE = "participant-registration-failed";

bool validToken(const std::string& value, std::size_t maximum)
{
    return !value.empty() && value.size() <= maximum &&
           std::all_of(value.begin(), value.end(), [](unsigned char character) {
               return std::islower(character) || std::isdigit(character) ||
                      character == '.' || character == '-';
           });
}

bool validParticipantId(const std::string& value)
{
    return validToken(value, 128) &&
           std::islower(static_cast<unsigned char>(value.front()));
}
} // namespace

void ParticipantAdmissionState::recordFailure(
    const std::string& referenceKey, const std::string& participantId,
    const std::string& code)
{
    const auto safeReference = safeReferenceKey(referenceKey);
    const auto safeId = safeParticipantId(participantId);
    const auto safeFailureCode = safeCode(code);
    std::lock_guard<std::mutex> lock(_mutex);
    const auto found = _failures.find(safeReference);
    if (found != _failures.end())
    {
        if (found->second.participantId == safeId &&
            found->second.code == safeFailureCode) return;
        const auto generation = ++_generation;
        found->second = {safeId, safeFailureCode, generation};
        return;
    }
    if (_failures.size() >= MAX_RETAINED_FAILURES)
    {
        if (!_overflow)
        {
            _overflow = true;
            ++_generation;
        }
        return;
    }
    const auto generation = ++_generation;
    _failures.emplace(safeReference,
                      Entry{safeId, safeFailureCode, generation});
}

void ParticipantAdmissionState::clear(const std::string& referenceKey)
{
    std::lock_guard<std::mutex> lock(_mutex);
    if (_failures.erase(safeReferenceKey(referenceKey)) != 0) ++_generation;
}

void ParticipantAdmissionState::reset()
{
    std::lock_guard<std::mutex> lock(_mutex);
    if (_failures.empty() && !_overflow) return;
    _failures.clear();
    _overflow = false;
    ++_generation;
}

ConfigurationParticipantAdmissionSnapshot
ParticipantAdmissionState::snapshot() const
{
    std::lock_guard<std::mutex> lock(_mutex);
    ConfigurationParticipantAdmissionSnapshot result;
    result.generation = _generation;
    result.overflow = _overflow;
    result.rejectedParticipants.reserve(_failures.size());
    for (const auto& [referenceKey, failure] : _failures)
    {
        static_cast<void>(referenceKey);
        result.rejectedParticipants.push_back(
            {failure.participantId, failure.code,
             failure.observationGeneration});
    }
    std::sort(result.rejectedParticipants.begin(),
              result.rejectedParticipants.end(),
              [](const auto& left, const auto& right) {
                  if (left.participantId != right.participantId)
                      return left.participantId < right.participantId;
                  if (left.code != right.code) return left.code < right.code;
                  return left.observationGeneration <
                         right.observationGeneration;
              });
    return result;
}

Health::Report ParticipantAdmissionState::health() const
{
    const auto current = snapshot();
    if (current.rejectedParticipants.empty() && !current.overflow)
        return {"configuration-participant-admission", Health::Status::up,
                "All discovered transactional configuration participants were admitted",
                "PDR-HEALTH-CONFIGURATION-PARTICIPANT-ADMISSION-UP", "", {}};

    std::vector<std::string> affected;
    constexpr std::size_t MAX_AFFECTED = 16;
    for (const auto& failure : current.rejectedParticipants)
    {
        if (affected.size() == MAX_AFFECTED) break;
        affected.push_back(failure.participantId);
    }
    const auto retained = current.rejectedParticipants.size();
    return {"configuration-participant-admission", Health::Status::degraded,
            std::to_string(retained) +
                " transactional configuration participant registration(s) rejected" +
                (current.overflow ? "; diagnostic capacity exceeded" : ""),
            current.overflow
                ? "PDR-HEALTH-CONFIGURATION-PARTICIPANT-ADMISSION-OVERFLOW"
                : "PDR-HEALTH-CONFIGURATION-PARTICIPANT-ADMISSION-REJECTED",
            "Resolve participant identity, ownership-prefix and dependency contracts, "
            "then unregister and register the affected service again.",
            std::move(affected)};
}

std::string ParticipantAdmissionState::safeParticipantId(
    const std::string& value)
{
    return validParticipantId(value) ? value : UNKNOWN_PARTICIPANT;
}

std::string ParticipantAdmissionState::safeCode(const std::string& value)
{
    return validToken(value, 96) ? value : FALLBACK_CODE;
}

std::string ParticipantAdmissionState::safeReferenceKey(
    const std::string& value)
{
    constexpr std::size_t MAXIMUM_REFERENCE_KEY = 256;
    if (value.size() <= MAXIMUM_REFERENCE_KEY) return value;
    return value.substr(0, 192) + "-" +
           std::to_string(std::hash<std::string>{}(value));
}
} // namespace PocoDDS::ConfigTransaction
