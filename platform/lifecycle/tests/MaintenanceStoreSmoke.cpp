#include "PocoDDS/Lifecycle/SqliteMaintenanceStore.h"

#include <Poco/File.h>
#include <Poco/FileStream.h>
#include <Poco/Exception.h>
#include <Poco/Path.h>
#include <Poco/TemporaryFile.h>
#include <Poco/UUIDGenerator.h>

#include <iostream>
#include <stdexcept>
#include <string>

namespace
{
using namespace PocoDDS::Lifecycle;

MaintenancePlan plan(const std::string& id, MaintenanceStatus status,
                     std::int64_t timestamp)
{
    return {id, "provider.bundle", status, {"consumer.bundle"},
            {{"test", "provider.bundle", true, "persisted"}}, false,
            "TEST", "maintenance store smoke", timestamp, timestamp, 0};
}

void removeDatabase(const std::string& path)
{
    for (const auto& suffix : {std::string(), std::string("-wal"),
                               std::string("-shm"), std::string(".lock")})
    {
        Poco::File file(path + suffix);
        if (file.exists()) file.remove();
    }
}
}

int main()
{
    Poco::Path path(Poco::TemporaryFile::tempName());
    path.setFileName("pdr-lifecycle-maintenance-" +
        Poco::UUIDGenerator::defaultGenerator().createRandom().toString() +
        ".sqlite");
    const auto database = path.toString();
    const auto backupDatabase = database + "-backup";
    const auto corruptDatabase = database + "-corrupt";
    try
    {
        std::string firstId;
        {
            SqliteMaintenanceStore store(database, 4, 4);
            store.initialize();
            bool duplicateOwnerRejected = false;
            try
            {
                SqliteMaintenanceStore duplicate(database, 4, 4);
                duplicate.initialize();
            }
            catch (const Poco::FileException&)
            {
                duplicateOwnerRejected = true;
            }
            if (!duplicateOwnerRejected)
                throw std::runtime_error(
                    "store allowed two owners for one maintenance database");
            firstId = store.allocatePlanId();
            if (firstId != "maintenance-1")
                throw std::runtime_error("plan sequence did not start at one");
            store.save(plan(firstId, MaintenanceStatus::draining, 100));
        }
        {
            SqliteMaintenanceStore store(database, 4, 4);
            store.initialize();
            const auto incomplete = store.incomplete();
            if (incomplete.size() != 1 || incomplete.front().id != firstId ||
                incomplete.front().status != MaintenanceStatus::draining)
                throw std::runtime_error("incomplete plan did not survive reopen");
            auto completed = incomplete.front();
            completed.status = MaintenanceStatus::rolledBack;
            completed.rollbackComplete = true;
            completed.code = "DRAIN_CRASH_RECOVERED";
            completed.updatedMicroseconds = 101;
            MaintenanceOperation operation{false, false, completed};
            store.complete(completed,
                {"request-1", "drain:provider.bundle:5000", operation});
            const auto replay = store.findByRequestId("request-1");
            if (!replay || replay->fingerprint !=
                    "drain:provider.bundle:5000" ||
                replay->operation.plan.code != "DRAIN_CRASH_RECOVERED")
                throw std::runtime_error("durable idempotency replay was lost");
            bool conflictingBindingRejected = false;
            try
            {
                store.complete(completed,
                    {"request-1", "different-input", operation});
            }
            catch (const Poco::InvalidArgumentException&)
            {
                conflictingBindingRejected = true;
            }
            if (!conflictingBindingRejected)
                throw std::runtime_error(
                    "store allowed durable request ID rebinding");
            bool conflictingResultRejected = false;
            try
            {
                auto changed = operation;
                changed.succeeded = true;
                store.complete(completed,
                    {"request-1", "drain:provider.bundle:5000", changed});
            }
            catch (const Poco::InvalidArgumentException&)
            {
                conflictingResultRejected = true;
            }
            if (!conflictingResultRejected)
                throw std::runtime_error(
                    "store allowed an immutable request result to change");
            if (store.allocatePlanId() != "maintenance-2")
                throw std::runtime_error("plan sequence did not survive reopen");

            auto pending = plan("maintenance-pending",
                                MaintenanceStatus::restoreRecoveryPending, 200);
            store.save(pending);
            auto desiredStopped = plan(
                "maintenance-desired-stopped",
                MaintenanceStatus::restoreRolledBack, 201);
            desiredStopped.rollbackComplete = true;
            store.save(desiredStopped);
            for (int index = 0; index < 8; ++index)
            {
                auto item = plan("maintenance-final-" + std::to_string(index),
                                 MaintenanceStatus::restored, 300 + index);
                item.rollbackComplete = true;
                MaintenanceOperation final{true, false, item};
                store.complete(item, {"request-final-" + std::to_string(index),
                    "restore:" + item.id, final});
            }
            if (store.history(100).size() != 6 ||
                store.incomplete().size() != 2 ||
                store.findByRequestId("request-final-0"))
                throw std::runtime_error(
                    "bounded retention removed pending state or kept stale requests");
            const auto state = store.snapshot();
            if (!state.healthy || state.schemaVersion != 1 ||
                state.nextPlanId != 2 || state.planRecords != 6 ||
                state.requestRecords != 4 || state.openPlans != 2)
                throw std::runtime_error("maintenance store snapshot is inconsistent");
            const auto backup = store.backupTo(backupDatabase);
            if (!backup.healthy || backup.planRecords != state.planRecords ||
                backup.requestRecords != state.requestRecords ||
                backup.openPlans != state.openPlans)
                throw std::runtime_error("maintenance backup snapshot is inconsistent");
            bool existingBackupRejected = false;
            try { static_cast<void>(store.backupTo(backupDatabase)); }
            catch (const Poco::FileExistsException&)
            {
                existingBackupRejected = true;
            }
            if (!existingBackupRejected)
                throw std::runtime_error("maintenance backup overwrote an existing file");
        }
        {
            SqliteMaintenanceStore backup(backupDatabase, 4, 4);
            backup.openExisting();
            const auto state = backup.snapshot();
            if (state.planRecords != 6 || state.requestRecords != 4 ||
                state.openPlans != 2 ||
                !backup.findByRequestId("request-final-7"))
                throw std::runtime_error("maintenance backup did not reopen cleanly");
            bool readOnlyWriteRejected = false;
            try
            {
                backup.save(plan("maintenance-illegal",
                                 MaintenanceStatus::draining, 999));
            }
            catch (const Poco::Exception&)
            {
                readOnlyWriteRejected = true;
            }
            if (!readOnlyWriteRejected)
                throw std::runtime_error("read-only maintenance store accepted a write");
        }
        {
            Poco::FileOutputStream stream(corruptDatabase,
                                          std::ios::out | std::ios::binary);
            stream << "not-a-sqlite-database";
        }
        bool corruptDatabaseRejected = false;
        try
        {
            SqliteMaintenanceStore store(corruptDatabase, 4, 4);
            store.initialize();
        }
        catch (const Poco::Exception&)
        {
            corruptDatabaseRejected = true;
        }
        if (!corruptDatabaseRejected)
            throw std::runtime_error("store accepted a corrupt maintenance database");
        removeDatabase(corruptDatabase);
        removeDatabase(backupDatabase);
        removeDatabase(database);
        std::cout << "MAINTENANCE_STORE_SMOKE_PASS reopen=1 recovery=1 "
                     "idempotency=1 retention=1 exclusive_owner=1 "
                     "integrity_check=1 backup=1 readonly=1\n";
        return 0;
    }
    catch (const std::exception& exception)
    {
        removeDatabase(corruptDatabase);
        removeDatabase(backupDatabase);
        removeDatabase(database);
        std::cerr << "MAINTENANCE_STORE_SMOKE_FAIL: " << exception.what() << '\n';
        return 1;
    }
}
