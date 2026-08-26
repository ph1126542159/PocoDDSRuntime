#include "PocoDDS/Lifecycle/Maintenance.h"

#include <stdexcept>

namespace PocoDDS::Lifecycle
{
const char* toString(MaintenanceStatus status) noexcept
{
    switch (status)
    {
    case MaintenanceStatus::draining: return "draining";
    case MaintenanceStatus::restoring: return "restoring";
    case MaintenanceStatus::drainRecoveryPending: return "drainRecoveryPending";
    case MaintenanceStatus::restoreRecoveryPending: return "restoreRecoveryPending";
    case MaintenanceStatus::drained: return "drained";
    case MaintenanceStatus::restored: return "restored";
    case MaintenanceStatus::rolledBack: return "rolledBack";
    case MaintenanceStatus::restoreRolledBack: return "restoreRolledBack";
    case MaintenanceStatus::failed: return "failed";
    }
    return "failed";
}

MaintenanceStatus maintenanceStatusFromString(const std::string& value)
{
    if (value == "draining") return MaintenanceStatus::draining;
    if (value == "restoring") return MaintenanceStatus::restoring;
    if (value == "drainRecoveryPending")
        return MaintenanceStatus::drainRecoveryPending;
    if (value == "restoreRecoveryPending")
        return MaintenanceStatus::restoreRecoveryPending;
    if (value == "drained") return MaintenanceStatus::drained;
    if (value == "restored") return MaintenanceStatus::restored;
    if (value == "rolledBack") return MaintenanceStatus::rolledBack;
    if (value == "restoreRolledBack")
        return MaintenanceStatus::restoreRolledBack;
    if (value == "failed") return MaintenanceStatus::failed;
    throw std::invalid_argument("unknown maintenance status: " + value);
}

bool recoveryPending(MaintenanceStatus status) noexcept
{
    return status == MaintenanceStatus::drainRecoveryPending ||
           status == MaintenanceStatus::restoreRecoveryPending;
}
} // namespace PocoDDS::Lifecycle
