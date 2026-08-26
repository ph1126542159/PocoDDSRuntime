#include <PocoDDS/Lifecycle/SqliteMaintenanceStore.h>

#include <Poco/File.h>
#include <Poco/TemporaryFile.h>

#include <string>

int main()
{
    const std::string path = Poco::TemporaryFile::tempName() + ".sqlite";
    const std::string backupPath = path + ".backup";
    try
    {
        PocoDDS::Lifecycle::SqliteMaintenanceStore store(path, 8, 16);
        store.initialize();
        PocoDDS::Lifecycle::MaintenancePlan plan;
        plan.id = store.allocatePlanId();
        plan.target = "external.provider";
        plan.status = PocoDDS::Lifecycle::MaintenanceStatus::draining;
        plan.code = "EXTERNAL_TEST";
        plan.detail = "installed persistence consumer";
        plan.createdMicroseconds = 1;
        plan.updatedMicroseconds = 1;
        store.save(plan);
        const auto recovered = store.incomplete();
        if (recovered.size() != 1 || recovered.front().id != plan.id) return 1;
        const auto state = store.snapshot();
        if (!state.healthy || state.schemaVersion != 1 ||
            state.planRecords != 1 || state.openPlans != 1) return 1;
        const auto backup = store.backupTo(backupPath);
        if (!backup.healthy || backup.planRecords != 1 || backup.openPlans != 1)
            return 1;
        PocoDDS::Lifecycle::SqliteMaintenanceStore reopened(backupPath, 8, 16);
        reopened.openExisting();
        if (reopened.history(8).size() != 1) return 1;
    }
    catch (...)
    {
        return 2;
    }
    for (const auto& suffix : {std::string(), std::string("-wal"),
                               std::string("-shm"), std::string(".lock")})
    {
        Poco::File file(path + suffix);
        if (file.exists()) file.remove();
        Poco::File backup(backupPath + suffix);
        if (backup.exists()) backup.remove();
    }
    return 0;
}
