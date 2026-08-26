#include "PocoDDS/Lifecycle/SqliteMaintenanceStore.h"

#include <Poco/Timestamp.h>
#include <Poco/Thread.h>

#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

int main(int argc, char** argv)
{
    using namespace PocoDDS::Lifecycle;
    try
    {
        std::string database;
        std::string target;
        MaintenanceStatus status = MaintenanceStatus::draining;
        std::vector<std::string> consumers;
        int holdMilliseconds = 0;
        for (int index = 1; index < argc; ++index)
        {
            const std::string argument = argv[index];
            if (argument == "--database" && index + 1 < argc)
                database = argv[++index];
            else if (argument == "--target" && index + 1 < argc)
                target = argv[++index];
            else if (argument == "--consumer" && index + 1 < argc)
                consumers.emplace_back(argv[++index]);
            else if (argument == "--status" && index + 1 < argc)
            {
                status = maintenanceStatusFromString(argv[++index]);
                if (status != MaintenanceStatus::draining &&
                    status != MaintenanceStatus::restoring &&
                    status != MaintenanceStatus::drained)
                    throw std::invalid_argument(
                        "seed status must be draining, restoring or drained");
            }
            else if (argument == "--hold-milliseconds" && index + 1 < argc)
            {
                holdMilliseconds = std::stoi(argv[++index]);
                if (holdMilliseconds < 0 || holdMilliseconds > 30000)
                    throw std::invalid_argument(
                        "hold milliseconds must be between 0 and 30000");
            }
            else throw std::invalid_argument("invalid seed argument: " + argument);
        }
        if (database.empty() || target.empty())
            throw std::invalid_argument("--database and --target are required");
        SqliteMaintenanceStore store(database);
        store.initialize();
        const auto now = Poco::Timestamp().epochMicroseconds();
        MaintenancePlan plan;
        plan.id = store.allocatePlanId();
        plan.target = target;
        plan.status = status;
        plan.consumers = std::move(consumers);
        plan.steps.push_back({"crash-seed", target, false,
                              "simulated write-ahead record"});
        plan.code = "MAINTENANCE_IN_PROGRESS";
        plan.detail = "Simulated process loss after durable intent";
        plan.createdMicroseconds = now;
        plan.updatedMicroseconds = now;
        store.save(plan);
        std::cout << plan.id << '\n' << std::flush;
        if (holdMilliseconds > 0) Poco::Thread::sleep(holdMilliseconds);
        return 0;
    }
    catch (const std::exception& exception)
    {
        std::cerr << "MAINTENANCE_JOURNAL_SEED_FAIL: "
                  << exception.what() << '\n';
        return 1;
    }
}
