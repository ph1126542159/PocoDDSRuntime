#pragma once

#include "PocoDDS/Lifecycle/Maintenance.h"

#include <cstddef>
#include <optional>
#include <string>
#include <vector>

namespace PocoDDS::Lifecycle
{
struct StoredMaintenanceRequest
{
    std::string requestId;
    std::string fingerprint;
    MaintenanceOperation operation;
};

class MaintenanceStore
{
public:
    virtual ~MaintenanceStore() = default;
    virtual void initialize() = 0;
    virtual std::string allocatePlanId() = 0;
    virtual void save(const MaintenancePlan& plan) = 0;
    virtual void complete(const MaintenancePlan& plan,
                          const StoredMaintenanceRequest& request) = 0;
    virtual std::optional<StoredMaintenanceRequest> findByRequestId(
        const std::string& requestId) const = 0;
    virtual std::vector<MaintenancePlan> incomplete() const = 0;
    virtual std::vector<MaintenancePlan> history(std::size_t limit) const = 0;
};
} // namespace PocoDDS::Lifecycle
