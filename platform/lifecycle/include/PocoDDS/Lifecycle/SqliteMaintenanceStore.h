#pragma once

#include "PocoDDS/Lifecycle/MaintenanceStore.h"

#include <memory>
#include <string>

namespace PocoDDS::Lifecycle
{
struct MaintenanceStoreSnapshot
{
    bool healthy{false};
    std::string databasePath;
    std::uint32_t schemaVersion{0};
    std::uint64_t nextPlanId{0};
    std::size_t planRecords{0};
    std::size_t requestRecords{0};
    std::size_t openPlans{0};
};

enum class MaintenanceStoreOpenMode
{
    readOnly,
    backupSource
};

class PDR_LIFECYCLE_API SqliteMaintenanceStore final : public MaintenanceStore
{
public:
    explicit SqliteMaintenanceStore(std::string path,
                                    std::size_t maximumPlans = 128,
                                    std::size_t maximumRequests = 256);
    ~SqliteMaintenanceStore() override;

    void initialize() override;
    void openExisting(
        MaintenanceStoreOpenMode mode = MaintenanceStoreOpenMode::readOnly);
    std::string allocatePlanId() override;
    void save(const MaintenancePlan& plan) override;
    void complete(const MaintenancePlan& plan,
                  const StoredMaintenanceRequest& request) override;
    std::optional<StoredMaintenanceRequest> findByRequestId(
        const std::string& requestId) const override;
    std::vector<MaintenancePlan> incomplete() const override;
    std::vector<MaintenancePlan> history(std::size_t limit) const override;

    void verifyIntegrity() const;
    MaintenanceStoreSnapshot snapshot() const;
    MaintenanceStoreSnapshot backupTo(const std::string& destination) const;

private:
    class Impl;
    std::unique_ptr<Impl> _impl;
};
} // namespace PocoDDS::Lifecycle
