#include "PocoDDS/ProcessManagement/SubprocessManager.h"
#include "PocoDDS/ProcessManagement/ProcessDependencyGraph.h"

#include <Poco/Exception.h>
#include <Poco/File.h>
#include <Poco/Logger.h>
#include <Poco/Path.h>
#include <Poco/TemporaryFile.h>
#include <Poco/Util/ServerApplication.h>

#include <algorithm>
#include <chrono>
#include <fstream>
#include <functional>
#include <iostream>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

namespace
{
using namespace std::chrono_literals;
using PocoDDS::ProcessManagement::SubprocessInfo;
using PocoDDS::ProcessManagement::SubprocessManager;

void require(bool condition, const std::string& message)
{
    if (!condition)
        throw std::runtime_error(message);
}

void appendEvent(const std::string& path, const std::string& event)
{
    std::ofstream output(path, std::ios::app);
    output << event << '\n';
    require(static_cast<bool>(output), "failed to append dependency event");
}

void writeSignal(const std::string& path)
{
    const auto value = std::chrono::duration_cast<std::chrono::microseconds>(
        std::chrono::system_clock::now().time_since_epoch()).count();
    std::ofstream output(path, std::ios::trunc);
    output << value << '\n';
    require(static_cast<bool>(output), "failed to write dependency readiness");
}

class DependencyChild final : public Poco::Util::ServerApplication
{
  protected:
    int main(const std::vector<std::string>& arguments) override
    {
        const auto marker = std::find(arguments.begin(), arguments.end(),
                                      "--dependency-child");
        if (marker == arguments.end() ||
            std::distance(marker, arguments.end()) != 5)
            return Application::EXIT_CONFIG;
        const auto name = *(marker + 1);
        const auto eventPath = *(marker + 2);
        const auto readinessPath = *(marker + 3);
        const auto readinessDelay = std::chrono::milliseconds(
            std::stoi(*(marker + 4)));
        appendEvent(eventPath, "start:" + name);
        std::thread readiness;
        if (readinessPath != "-")
        {
            readiness = std::thread([=] {
                std::this_thread::sleep_for(readinessDelay);
                writeSignal(readinessPath);
                appendEvent(eventPath, "ready:" + name);
            });
        }
        waitForTerminationRequest();
        if (readiness.joinable())
            readiness.join();
        appendEvent(eventPath, "stop:" + name);
        return Application::EXIT_OK;
    }
};

struct TemporaryWorkspace
{
    Poco::Path path{Poco::TemporaryFile::tempName()};

    TemporaryWorkspace()
    {
        path.makeDirectory();
        Poco::File(path).createDirectories();
    }

    ~TemporaryWorkspace()
    {
        try { Poco::File(path).remove(true); }
        catch (...) { }
    }
};

void writeProcess(std::ofstream& output, int index,
                  const std::string& name,
                  const std::string& executable,
                  const std::string& eventPath,
                  const std::string& readinessPath,
                  int readinessDelay,
                  const std::string& dependency = {})
{
    const auto prefix = "subprocess." + std::to_string(index) + ".";
    output << prefix << "enabled = true\n"
           << prefix << "name = " << name << "\n"
           << prefix << "location = local\n"
           << prefix << "required = true\n"
           << prefix << "path = " << executable << "\n"
           << prefix << "workingDirectory = .\n"
           << prefix << "restartPolicy = never\n";
    if (!dependency.empty())
        output << prefix << "dependency.count = 1\n"
               << prefix << "dependency.0 = " << dependency << "\n";
    else
        output << prefix << "dependency.count = 0\n";
    if (readinessPath != "-")
        output << prefix << "readinessFile = " << readinessPath << "\n"
               << prefix << "readinessTimeoutMilliseconds = 1000\n";
    output << prefix << "argument.count = 5\n"
           << prefix << "argument.0 = --dependency-child\n"
           << prefix << "argument.1 = " << name << "\n"
           << prefix << "argument.2 = " << eventPath << "\n"
           << prefix << "argument.3 = " << readinessPath << "\n"
           << prefix << "argument.4 = " << readinessDelay << "\n";
}

void writeDependencyConfiguration(const std::string& path,
                                  const std::string& executable,
                                  const std::string& eventPath)
{
    std::ofstream output(path, std::ios::trunc);
    output << "subprocess.count = 2\n"
           << "subprocess.supervisionIntervalMilliseconds = 20\n";
    // Deliberately declare the dependent first. The manager must derive the
    // lifecycle order from the graph instead of configuration position.
    writeProcess(output, 0, "worker", executable, eventPath, "worker.ready", 50,
                 "foundation");
    writeProcess(output, 1, "foundation", executable, eventPath,
                 "foundation.ready", 200);
    require(static_cast<bool>(output), "failed to write dependency fixture");
}

void writeInvalidConfiguration(const std::string& path,
                               const std::string& executable,
                               bool cycle)
{
    std::ofstream output(path, std::ios::trunc);
    output << "subprocess.count = 2\n";
    writeProcess(output, 0, "first", executable, "events.log", "-", 0,
                 cycle ? "second" : "missing");
    writeProcess(output, 1, "second", executable, "events.log", "-", 0,
                 cycle ? "first" : "");
    require(static_cast<bool>(output), "failed to write invalid dependency fixture");
}

std::vector<SubprocessInfo> waitForInventory(
    SubprocessManager& manager,
    const std::function<bool(const std::vector<SubprocessInfo>&)>& predicate,
    std::chrono::milliseconds timeout = 5s)
{
    const auto deadline = std::chrono::steady_clock::now() + timeout;
    do
    {
        const auto inventory = manager.processes();
        if (predicate(inventory))
            return inventory;
        std::this_thread::sleep_for(20ms);
    } while (std::chrono::steady_clock::now() < deadline);
    std::string detail;
    for (const auto& process : manager.processes())
        detail += process.name + "=" + process.state + ";";
    throw std::runtime_error(
        "timed out waiting for dependency lifecycle state: " + detail);
}

const SubprocessInfo& findProcess(const std::vector<SubprocessInfo>& inventory,
                                  const std::string& name)
{
    const auto process = std::find_if(
        inventory.begin(), inventory.end(), [&](const auto& candidate) {
            return candidate.name == name;
        });
    if (process == inventory.end())
        throw std::runtime_error("dependency process missing from inventory: " + name);
    return *process;
}

std::vector<std::string> readEvents(const std::string& path)
{
    std::ifstream input(path);
    std::vector<std::string> events;
    std::string event;
    while (std::getline(input, event))
        events.push_back(event);
    return events;
}

std::size_t eventIndex(const std::vector<std::string>& events,
                       const std::string& event, std::size_t offset = 0)
{
    const auto found = std::find(events.begin() +
        static_cast<std::ptrdiff_t>(offset), events.end(), event);
    if (found == events.end())
        throw std::runtime_error("dependency event missing: " + event);
    return static_cast<std::size_t>(std::distance(events.begin(), found));
}
} // namespace

int main(int argc, char** argv)
{
    if (argc > 1 && std::string(argv[1]) == "--dependency-child")
    {
        DependencyChild child;
        return child.run(argc, argv);
    }

    try
    {
        require(argc >= 1, "test executable path is unavailable");
        Poco::Path executable(argv[0]);
        executable.makeAbsolute();
        TemporaryWorkspace workspace;
        Poco::Path worker(workspace.path);
        worker.append(executable.getFileName());
        Poco::File(executable).copyTo(worker.toString());
        Poco::Path configuration(workspace.path);
        configuration.append("dependencies.properties");
        Poco::Path eventLog(workspace.path);
        eventLog.append("events.log");
        auto eventArgument = eventLog.toString();
        std::replace(eventArgument.begin(), eventArgument.end(), '\\', '/');
        writeDependencyConfiguration(configuration.toString(),
                                     worker.getFileName(), eventArgument);

        PocoDDS::ProcessManagement::SubprocessManagerOptions options;
        options.shutdownTimeoutMilliseconds = 1500;
        SubprocessManager manager(Poco::Logger::get("SubprocessDependencySmoke"),
                                  options);
        require(manager.startFromConfiguration(configuration.toString(),
                                               workspace.path.toString()) == 1,
                "dependent launched before foundation readiness");
        const auto waiting = manager.processes();
        require(waiting.size() == 2 &&
                    findProcess(waiting, "foundation").state == "starting" &&
                    findProcess(waiting, "worker").state == "waiting-dependency",
                "initial dependency gate state is incorrect");
        const auto initialGraph =
            PocoDDS::ProcessManagement::activeProcessDependencyGraph();
        require(initialGraph.available && initialGraph.schemaVersion == 1 &&
                    initialGraph.generation == 1 &&
                    initialGraph.nodes.size() == 2 &&
                    initialGraph.nodes[0].name == "foundation" &&
                    initialGraph.nodes[1].name == "worker" &&
                    initialGraph.nodes[1].dependencies.size() == 1 &&
                    initialGraph.nodes[1].dependencies.front() == "foundation" &&
                    initialGraph.nodes[1].state == "waiting-dependency",
                "dependency graph snapshot is not topologically authoritative");
        waitForInventory(manager, [](const auto& inventory) {
            return inventory.size() == 2 &&
                findProcess(inventory, "foundation").state == "running" &&
                findProcess(inventory, "worker").state == "running";
        });
        auto events = readEvents(eventLog.toString());
        require(eventIndex(events, "start:foundation") <
                    eventIndex(events, "ready:foundation") &&
                eventIndex(events, "ready:foundation") <
                    eventIndex(events, "start:worker"),
                "dependent started before its dependency became ready");

        require(manager.stop("foundation"),
                "manual dependency stop was rejected");
        const auto blocked = manager.processes();
        require(findProcess(blocked, "foundation").state == "stopped" &&
                    findProcess(blocked, "worker").state == "dependency-failed" &&
                    manager.runningCount() == 0,
                "dependency stop did not propagate to its dependent");
        const auto blockedGraph =
            PocoDDS::ProcessManagement::activeProcessDependencyGraph();
        require(blockedGraph.nodes.size() == 2 &&
                    !blockedGraph.nodes[0].desiredRunning &&
                    blockedGraph.nodes[1].desiredRunning &&
                    blockedGraph.nodes[1].state == "dependency-failed",
                "dependency graph snapshot lost desired or blocked state");
        events = readEvents(eventLog.toString());
        require(eventIndex(events, "stop:worker") <
                    eventIndex(events, "stop:foundation"),
                "dependency shutdown order was not reversed");

        require(manager.start("worker"),
                "starting a dependent did not reauthorize its dependency closure");
        waitForInventory(manager, [](const auto& inventory) {
            return findProcess(inventory, "foundation").state == "running" &&
                findProcess(inventory, "worker").state == "running";
        });
        manager.stopAll();
        events = readEvents(eventLog.toString());
        const auto firstWorkerStop = eventIndex(events, "stop:worker");
        const auto secondWorkerStop = eventIndex(
            events, "stop:worker", firstWorkerStop + 1);
        const auto firstFoundationStop = eventIndex(events, "stop:foundation");
        const auto secondFoundationStop = eventIndex(
            events, "stop:foundation", firstFoundationStop + 1);
        require(secondWorkerStop < secondFoundationStop,
                "stopAll did not use reverse dependency order");

        writeInvalidConfiguration(configuration.toString(),
                                  worker.getFileName(), false);
        bool unknownRejected = false;
        try
        {
            manager.startFromConfiguration(configuration.toString(),
                                           workspace.path.toString());
        }
        catch (const Poco::InvalidArgumentException&)
        {
            unknownRejected = true;
        }
        require(unknownRejected, "unknown subprocess dependency was accepted");

        writeInvalidConfiguration(configuration.toString(),
                                  worker.getFileName(), true);
        bool cycleRejected = false;
        try
        {
            manager.startFromConfiguration(configuration.toString(),
                                           workspace.path.toString());
        }
        catch (const Poco::InvalidArgumentException&)
        {
            cycleRejected = true;
        }
        require(cycleRejected, "cyclic subprocess dependency was accepted");

        std::cout << "SUBPROCESS_DEPENDENCY_DAG_PASS dependencyGate=1 "
                     "dependencyFailure=1 dependencyRecovery=1 reverseShutdown=1 "
                     "invalidDependency=1 cycleDetection=1 graphSnapshot=1\n";
        return 0;
    }
    catch (const std::exception& exception)
    {
        std::cerr << "Subprocess dependency smoke failed: "
                  << exception.what() << '\n';
        return 1;
    }
}
