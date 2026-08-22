#include "PocoDDS/NativeProcess/NativeProcessSupervisor.h"

#include <atomic>
#include <chrono>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <string>
#include <thread>

#ifdef _WIN32
#include <Windows.h>
#else
#include <csignal>
#include <unistd.h>
#endif

namespace
{
using namespace PocoDDS::RuntimeCore;
using namespace std::chrono_literals;

std::atomic<bool> childStopping{false};

#ifdef _WIN32
BOOL WINAPI stopHandler(DWORD signal)
{
    if (signal == CTRL_BREAK_EVENT || signal == CTRL_C_EVENT)
    {
        childStopping = true;
        return TRUE;
    }
    return FALSE;
}
#else
void stopHandler(int) { childStopping = true; }
#endif

int runChild()
{
#ifdef _WIN32
    SetConsoleCtrlHandler(stopHandler, TRUE);
#else
    std::signal(SIGTERM, stopHandler);
#endif
#ifdef _WIN32
    char* environmentValue = nullptr;
    std::size_t environmentSize = 0;
    _dupenv_s(&environmentValue, &environmentSize, "PDR_NATIVE_PROCESS_TEST");
    const std::string environment = environmentValue ? environmentValue : "";
    std::free(environmentValue);
#else
    const auto* environmentValue = std::getenv("PDR_NATIVE_PROCESS_TEST");
    const std::string environment = environmentValue ? environmentValue : "";
#endif
    if (environment != "inherited-and-overridden")
        return 21;
    const auto deadline = std::chrono::steady_clock::now() + 10s;
    while (!childStopping && std::chrono::steady_clock::now() < deadline)
        std::this_thread::sleep_for(10ms);
    return 0;
}

template <typename Predicate> bool waitUntil(Predicate predicate, std::chrono::milliseconds timeout)
{
    const auto deadline = std::chrono::steady_clock::now() + timeout;
    while (std::chrono::steady_clock::now() < deadline)
    {
        if (predicate())
            return true;
        std::this_thread::sleep_for(20ms);
    }
    return predicate();
}
} // namespace

int main(int argc, char** argv)
{
    using namespace PocoDDS::NativeProcess;
    using namespace PocoDDS::RuntimeCore;
    using namespace std::chrono_literals;

    if (argc == 2 && std::string(argv[1]) == "--child")
        return runChild();
    if (argc == 2 && std::string(argv[1]) == "--fail")
        return 7;

    const auto executable = std::filesystem::weakly_canonical(argv[0]);
    NativeProcessSupervisor supervisor({executable.parent_path().string(), false, 20ms});
    ProcessSpec worker;
    worker.id = "worker";
    worker.executable = executable.string();
    worker.arguments = {"--child"};
    worker.environment = {{"PDR_NATIVE_PROCESS_TEST", "inherited-and-overridden"}};
    worker.gracefulStopTimeout = 500ms;
    if (!supervisor.registerProcess(worker) || !supervisor.start("worker"))
        return 1;
    if (!waitUntil(
            [&]
            {
                const auto snapshots = supervisor.snapshots();
                return snapshots.size() == 1 && snapshots.front().state == ProcessState::running &&
                       snapshots.front().processId != 0;
            },
            2s))
        return 2;
    if (!supervisor.stop("worker") || supervisor.snapshots().front().state != ProcessState::stopped)
        return 3;
    if (!supervisor.restart("worker") || !supervisor.stop("worker"))
        return 4;

    ProcessSpec crash;
    crash.id = "crash-loop";
    crash.executable = executable.string();
    crash.arguments = {"--fail"};
    crash.restartPolicy = RestartPolicy::onFailure;
    crash.maximumRestarts = 2;
    crash.restartWindow = 5s;
    if (!supervisor.registerProcess(crash) || !supervisor.start("crash-loop"))
        return 5;
    if (!waitUntil(
            [&]
            {
                const auto snapshots = supervisor.snapshots();
                return snapshots.size() == 2 && snapshots[1].state == ProcessState::quarantined;
            },
            5s))
    {
        const auto observed = supervisor.snapshots()[1];
        std::cerr << "crash-loop state=" << static_cast<int>(observed.state)
                  << " restarts=" << observed.restartCount
                  << " exit=" << observed.lastExitCode.value_or(-1)
                  << " error=" << observed.lastError.message << '\n';
        return 6;
    }
    const auto quarantined = supervisor.snapshots()[1];
    if (quarantined.restartCount != 2 || !quarantined.lastExitCode ||
        *quarantined.lastExitCode != 7 ||
        quarantined.lastError.code != RuntimeErrorCode::unavailable)
        return 7;

    ProcessSpec dependent = worker;
    dependent.id = "dependent";
    dependent.dependencies = {"missing"};
    if (!supervisor.registerProcess(dependent))
        return 8;
    const auto invalidGraph = supervisor.startAll();
    if (invalidGraph || invalidGraph.error().code != RuntimeErrorCode::dependencyFailure)
        return 9;

    ProcessSpec escaped = worker;
    escaped.id = "escaped-output";
    escaped.standardOutputPath = "../outside.log";
    const auto escapedResult = supervisor.registerProcess(escaped);
    if (escapedResult || escapedResult.error().code != RuntimeErrorCode::invalidArgument)
        return 10;

    const auto outsideLog =
        std::filesystem::temp_directory_path() /
        ("pdr-native-process-outside-" +
         std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()) + ".log");
    const auto linkedLog = executable.parent_path() / "pdr-native-process-linked-output.log";
    {
        std::error_code error;
        std::filesystem::remove(linkedLog, error);
        std::filesystem::remove(outsideLog, error);
        {
            std::ofstream output(outsideLog);
            output << "outside";
        }
        std::filesystem::create_symlink(outsideLog, linkedLog, error);
        if (!error)
        {
            ProcessSpec linkedOutput = worker;
            linkedOutput.id = "linked-output";
            linkedOutput.standardOutputPath = linkedLog.string();
            const auto linkedResult = supervisor.registerProcess(linkedOutput);
            std::filesystem::remove(linkedLog, error);
            std::filesystem::remove(outsideLog, error);
            if (linkedResult || linkedResult.error().code != RuntimeErrorCode::invalidArgument)
                return 11;
        }
        else
        {
            std::filesystem::remove(outsideLog, error);
        }
    }

    ProcessSpec invalidEnvironment = worker;
    invalidEnvironment.id = "invalid-environment";
    invalidEnvironment.environment = {{"INVALID=NAME", "value"}};
    const auto environmentResult = supervisor.registerProcess(invalidEnvironment);
    if (environmentResult || environmentResult.error().code != RuntimeErrorCode::invalidArgument)
        return 12;
    supervisor.stopAll();

    std::cout << "PDR_NATIVE_PROCESS_PASS lifecycle=verified restartBudget=quarantined "
                 "dependencyGate=verified\n";
    return 0;
}
