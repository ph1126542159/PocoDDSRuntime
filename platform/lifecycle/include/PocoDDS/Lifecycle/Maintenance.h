#pragma once

#include "PocoDDS/Lifecycle/Export.h"

#include <cstdint>
#include <string>
#include <vector>

namespace PocoDDS::Lifecycle
{
enum class MaintenanceStatus
{
    draining,
    restoring,
    drainRecoveryPending,
    restoreRecoveryPending,
    drained,
    restored,
    rolledBack,
    restoreRolledBack,
    failed
};

PDR_LIFECYCLE_API const char* toString(MaintenanceStatus status) noexcept;
PDR_LIFECYCLE_API MaintenanceStatus maintenanceStatusFromString(
    const std::string& value);
PDR_LIFECYCLE_API bool recoveryPending(MaintenanceStatus status) noexcept;

struct MaintenanceStep
{
    std::string phase;
    std::string target;
    bool succeeded{false};
    std::string detail;
};

struct MaintenancePlan
{
    std::string id;
    std::string target;
    MaintenanceStatus status{MaintenanceStatus::failed};
    std::vector<std::string> consumers;
    std::vector<MaintenanceStep> steps;
    bool rollbackComplete{false};
    std::string code;
    std::string detail;
    std::int64_t createdMicroseconds{0};
    std::int64_t updatedMicroseconds{0};
    std::uint32_t recoveryAttempts{0};
};

struct MaintenanceOperation
{
    bool succeeded{false};
    bool idempotentReplay{false};
    MaintenancePlan plan;
};
} // namespace PocoDDS::Lifecycle
