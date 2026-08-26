#include "ProcessDesiredStateStore.h"

#include <Poco/File.h>
#include <Poco/Path.h>
#include <Poco/Process.h>
#include <Poco/TemporaryFile.h>

#include <cstdlib>
#include <iostream>
#include <map>
#include <stdexcept>
#include <string>

namespace
{
using PocoDDS::ProcessManagement::Detail::ProcessDesiredStateCommitStage;
using PocoDDS::ProcessManagement::Detail::ProcessDesiredStateSnapshot;
using PocoDDS::ProcessManagement::Detail::ProcessDesiredStateStore;

constexpr int crashExitCode = 74;

void require(bool condition, const std::string& message)
{
    if (!condition) throw std::runtime_error(message);
}

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
        try
        {
            Poco::File(path).remove(true);
        }
        catch (...)
        {
        }
    }
};

ProcessDesiredStateCommitStage parseStage(const std::string& value)
{
    if (value == "staging-flushed")
        return ProcessDesiredStateCommitStage::stagingFlushed;
    if (value == "previous-committed")
        return ProcessDesiredStateCommitStage::previousCommitted;
    if (value == "primary-committed")
        return ProcessDesiredStateCommitStage::primaryCommitted;
    throw std::invalid_argument("unknown desired-state commit stage: " + value);
}

int runCrashWriter(const std::string& path, const std::string& stageName)
{
    const auto crashStage = parseStage(stageName);
    ProcessDesiredStateStore store(
        path, [crashStage](ProcessDesiredStateCommitStage observed) {
            if (observed == crashStage) std::_Exit(crashExitCode);
        });
    store.acquireLease();
    const auto current = store.load();
    require(current.available && current.generation == 1,
            "crash writer did not load generation one");
    store.save(2, {{"worker", false}});
    return 75;
}

void establishGenerationOne(const std::string& path)
{
    ProcessDesiredStateStore store(path);
    store.acquireLease();
    store.save(1, {{"worker", true}});
}

ProcessDesiredStateSnapshot inspectAfterCrash(const std::string& path)
{
    ProcessDesiredStateStore store(path);
    store.acquireLease();
    return store.load();
}

void verifyRetryCommit(const std::string& path,
                       std::uint64_t recoveredGeneration)
{
    ProcessDesiredStateStore store(path);
    store.acquireLease();
    store.save(recoveredGeneration + 1, {{"worker", true}});
    const auto committed = store.load();
    require(committed.available && !committed.recovered &&
                committed.generation == recoveredGeneration + 1 &&
                committed.states == std::map<std::string, bool>{{"worker", true}} &&
                !Poco::File(path + ".new").exists(),
            "retry after interrupted commit did not converge");
}

void launchCrashWriter(const std::string& executable,
                       const std::string& workingDirectory,
                       const std::string& path,
                       const std::string& stage)
{
    Poco::Process::Args arguments{
        "--desired-state-store-crash", path, stage};
    auto process = Poco::Process::launch(
        executable, arguments, workingDirectory);
    require(process.wait() == crashExitCode,
            "fault writer did not terminate at " + stage);
}
} // namespace

int main(int argc, char** argv)
{
    if (argc == 4 &&
        std::string(argv[1]) == "--desired-state-store-crash")
    {
        try
        {
            return runCrashWriter(argv[2], argv[3]);
        }
        catch (...)
        {
            return 76;
        }
    }

    try
    {
        require(argc >= 1, "test executable path is unavailable");
        Poco::Path executable(argv[0]);
        executable.makeAbsolute();
        TemporaryWorkspace workspace;

        Poco::Path stagingState(workspace.path);
        stagingState.append("staging-crash.json");
        establishGenerationOne(stagingState.toString());
        launchCrashWriter(executable.toString(), workspace.path.toString(),
                          stagingState.toString(), "staging-flushed");
        const auto stagingSnapshot = inspectAfterCrash(stagingState.toString());
        require(stagingSnapshot.generation == 1 && !stagingSnapshot.recovered &&
                    stagingSnapshot.states.at("worker") &&
                    Poco::File(stagingState.toString() + ".new").exists() &&
                    !Poco::File(stagingState.toString() + ".previous").exists(),
                "staging-flush crash did not preserve the committed primary");
        verifyRetryCommit(stagingState.toString(), stagingSnapshot.generation);

        Poco::Path previousState(workspace.path);
        previousState.append("previous-crash.json");
        establishGenerationOne(previousState.toString());
        launchCrashWriter(executable.toString(), workspace.path.toString(),
                          previousState.toString(), "previous-committed");
        const auto previousSnapshot = inspectAfterCrash(previousState.toString());
        require(previousSnapshot.generation == 1 && previousSnapshot.recovered &&
                    previousSnapshot.states.at("worker") &&
                    !Poco::File(previousState).exists() &&
                    Poco::File(previousState.toString() + ".new").exists() &&
                    Poco::File(previousState.toString() + ".previous").exists(),
                "previous-commit crash did not expose the recovery generation");
        verifyRetryCommit(previousState.toString(), previousSnapshot.generation);

        Poco::Path primaryState(workspace.path);
        primaryState.append("primary-crash.json");
        establishGenerationOne(primaryState.toString());
        launchCrashWriter(executable.toString(), workspace.path.toString(),
                          primaryState.toString(), "primary-committed");
        const auto primarySnapshot = inspectAfterCrash(primaryState.toString());
        require(primarySnapshot.generation == 2 && !primarySnapshot.recovered &&
                    !primarySnapshot.states.at("worker") &&
                    Poco::File(primaryState).exists() &&
                    !Poco::File(primaryState.toString() + ".new").exists() &&
                    Poco::File(primaryState.toString() + ".previous").exists(),
                "primary-commit crash did not expose the new generation");
        verifyRetryCommit(primaryState.toString(), primarySnapshot.generation);

        std::cout <<
            "PROCESS_DESIRED_STATE_DURABILITY_PASS "
            "stagingCrashSafe=1 previousCrashSafe=1 primaryCrashSafe=1 "
            "retryCommit=1 metadataDurable=1\n";
        return 0;
    }
    catch (const std::exception& exception)
    {
        std::cerr << "Process desired-state durability smoke failed: "
                  << exception.what() << '\n';
        return 1;
    }
}
