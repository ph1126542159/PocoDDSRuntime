#include "PocoDDS/Lifecycle/SqliteMaintenanceStore.h"

#include <Poco/Exception.h>
#include <Poco/File.h>
#include <Poco/JSON/Array.h>
#include <Poco/JSON/Object.h>
#include <Poco/JSON/Stringifier.h>
#include <Poco/Path.h>

#include <iostream>
#include <map>
#include <set>
#include <stdexcept>
#include <string>

namespace
{
using namespace PocoDDS::Lifecycle;

std::map<std::string, std::string> arguments(int argc, char** argv)
{
    std::map<std::string, std::string> result;
    for (int index = 1; index < argc; ++index)
    {
        const std::string name = argv[index];
        if (name.rfind("--", 0) != 0 || index + 1 >= argc)
            throw Poco::InvalidArgumentException("Invalid command line argument", name);
        if (!result.emplace(name, argv[++index]).second)
            throw Poco::InvalidArgumentException("Duplicate command line argument", name);
    }
    return result;
}

std::string required(const std::map<std::string, std::string>& values,
                     const std::string& name)
{
    const auto found = values.find(name);
    if (found == values.end() || found->second.empty())
        throw Poco::InvalidArgumentException("Missing command line argument", name);
    return found->second;
}

std::string absolute(const std::string& value)
{
    Poco::Path path(value);
    path.makeAbsolute();
    return path.toString();
}

void rejectUnknown(const std::map<std::string, std::string>& values,
                   const std::set<std::string>& allowed)
{
    for (const auto& [name, unused] : values)
    {
        static_cast<void>(unused);
        if (allowed.find(name) == allowed.end())
            throw Poco::InvalidArgumentException("Unknown command line argument", name);
    }
}

std::size_t limit(const std::map<std::string, std::string>& values)
{
    const auto found = values.find("--limit");
    if (found == values.end()) return 256;
    try
    {
        std::size_t consumed = 0;
        const auto parsed = std::stoull(found->second, &consumed);
        if (consumed != found->second.size() || parsed == 0 || parsed > 100000)
            throw std::invalid_argument("outside safe bounds");
        return static_cast<std::size_t>(parsed);
    }
    catch (const std::exception&)
    {
        throw Poco::InvalidArgumentException(
            "Lifecycle maintenance history limit must be between 1 and 100000");
    }
}

Poco::JSON::Object::Ptr snapshotObject(const MaintenanceStoreSnapshot& value)
{
    Poco::JSON::Object::Ptr result = new Poco::JSON::Object;
    result->set("healthy", value.healthy);
    result->set("database", value.databasePath);
    result->set("schemaVersion", value.schemaVersion);
    result->set("nextPlanId", value.nextPlanId);
    result->set("planRecords", static_cast<Poco::UInt64>(value.planRecords));
    result->set("requestRecords", static_cast<Poco::UInt64>(value.requestRecords));
    result->set("openPlans", static_cast<Poco::UInt64>(value.openPlans));
    return result;
}

Poco::JSON::Object::Ptr planObject(const MaintenancePlan& value)
{
    Poco::JSON::Object::Ptr result = new Poco::JSON::Object;
    result->set("id", value.id);
    result->set("target", value.target);
    result->set("status", toString(value.status));
    result->set("rollbackComplete", value.rollbackComplete);
    result->set("code", value.code);
    result->set("detail", value.detail);
    result->set("createdMicroseconds", value.createdMicroseconds);
    result->set("updatedMicroseconds", value.updatedMicroseconds);
    result->set("recoveryAttempts", value.recoveryAttempts);
    Poco::JSON::Array::Ptr consumers = new Poco::JSON::Array;
    for (const auto& consumer : value.consumers) consumers->add(consumer);
    result->set("consumers", consumers);
    Poco::JSON::Array::Ptr steps = new Poco::JSON::Array;
    for (const auto& step : value.steps)
    {
        Poco::JSON::Object::Ptr item = new Poco::JSON::Object;
        item->set("phase", step.phase);
        item->set("target", step.target);
        item->set("succeeded", step.succeeded);
        item->set("detail", step.detail);
        steps->add(item);
    }
    result->set("steps", steps);
    return result;
}

void output(const Poco::JSON::Object& value)
{
    Poco::JSON::Stringifier::stringify(value, std::cout);
    std::cout << '\n';
}
} // namespace

int main(int argc, char** argv)
{
    std::string action = "unknown";
    try
    {
        const auto values = arguments(argc, argv);
        action = required(values, "--action");
        const auto database = absolute(required(values, "--database"));
        if (action == "check")
        {
            rejectUnknown(values, {"--action", "--database", "--limit"});
            const auto maximum = limit(values);
            SqliteMaintenanceStore store(database);
            store.openExisting();
            const auto state = store.snapshot();
            const auto plans = store.history(maximum);
            Poco::JSON::Array::Ptr history = new Poco::JSON::Array;
            for (const auto& plan : plans) history->add(planObject(plan));
            Poco::JSON::Object result;
            result.set("action", action);
            result.set("healthy", true);
            result.set("store", snapshotObject(state));
            result.set("plans", history);
            result.set("returnedPlans", static_cast<Poco::UInt64>(plans.size()));
            result.set("truncated", state.planRecords > plans.size());
            output(result);
            return 0;
        }
        if (action == "backup")
        {
            rejectUnknown(values, {"--action", "--database", "--destination"});
            const auto destination = absolute(required(values, "--destination"));
            SqliteMaintenanceStore store(database);
            store.openExisting(MaintenanceStoreOpenMode::backupSource);
            const auto source = store.snapshot();
            const auto backup = store.backupTo(destination);
            Poco::JSON::Object result;
            result.set("action", action);
            result.set("healthy", true);
            result.set("source", snapshotObject(source));
            result.set("backup", snapshotObject(backup));
            result.set("bytes", Poco::File(destination).getSize());
            output(result);
            return 0;
        }
        throw Poco::InvalidArgumentException(
            "Lifecycle maintenance action must be check or backup", action);
    }
    catch (const Poco::Exception& exception)
    {
        Poco::JSON::Object result;
        result.set("action", action);
        result.set("healthy", false);
        result.set("recoveryRequired", true);
        result.set("error", exception.displayText());
        output(result);
        return 2;
    }
    catch (const std::exception& exception)
    {
        Poco::JSON::Object result;
        result.set("action", action);
        result.set("healthy", false);
        result.set("recoveryRequired", true);
        result.set("error", exception.what());
        output(result);
        return 2;
    }
}
