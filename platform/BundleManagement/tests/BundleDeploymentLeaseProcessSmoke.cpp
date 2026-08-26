#include "PocoDDS/BundleManagement/BundleDeploymentCoordinator.h"
#include "PocoDDS/BundleManagement/BundleRepositoryFingerprint.h"

#include "Poco/Exception.h"
#include "Poco/File.h"
#include "Poco/FileStream.h"
#include "Poco/Path.h"
#include "Poco/Process.h"
#include "Poco/Timestamp.h"

#include <chrono>
#include <fstream>
#include <iostream>
#include <string>
#include <thread>

namespace
{
Poco::Path child(const Poco::Path& directory, const std::string& name)
{
    Poco::Path result(directory);
    result.makeDirectory();
    result.setFileName(name);
    return result;
}

void write(const Poco::Path& path, const std::string& value)
{
    Poco::File(path.parent()).createDirectories();
    Poco::FileOutputStream output(path.toString(), std::ios::out | std::ios::trunc);
    output << value;
}

std::string read(const Poco::Path& path)
{
    Poco::FileInputStream input(path.toString());
    return {std::istreambuf_iterator<char>(input), std::istreambuf_iterator<char>()};
}
} // namespace

int main(int argc, char** argv)
{
    if (argc == 5 && std::string(argv[1]) == "--hold")
    {
        PocoDDS::BundleManagement::BundleDeploymentCoordinator coordinator({argv[2], argv[3]});
        coordinator.beginActivation();
        write(Poco::Path(argv[4]), "held\n");
        std::this_thread::sleep_for(std::chrono::seconds(30));
        return 0;
    }
    if (argc != 1) return 64;

    Poco::Path root(Poco::Path::temp());
    root.pushDirectory("pdr-bundle-lease-" +
                       std::to_string(Poco::Timestamp().epochMicroseconds()));
    root.makeDirectory();
    Poco::Path repository(root); repository.pushDirectory("bundles"); repository.makeDirectory();
    Poco::Path state(root); state.pushDirectory("state"); state.makeDirectory();
    Poco::Path lkg(state); lkg.pushDirectory("last-known-good"); lkg.makeDirectory();
    const Poco::Path ready = child(root, "holder.ready");
    Poco::File(repository).createDirectories();
    Poco::File(state).createDirectories();
    Poco::File(lkg).createDirectories();
    write(child(repository, "bundle.bndl"), "candidate");
    write(child(lkg, "bundle.bndl"), "stable");
    const auto digest = PocoDDS::BundleManagement::BundleRepositoryFingerprint::
        calculateDirectory(repository.toString());
    write(child(state, "transaction.properties"),
          "transactionId=tx-process-lease\nstate=restartRequired\nbundleCount=1\n"
          "candidateDigest=" + digest + "\nerror=\n");

    try
    {
        Poco::ProcessHandle holder = Poco::Process::launch(
            argv[0], {"--hold", repository.toString(), state.toString(), ready.toString()});
        const auto readyDeadline = std::chrono::steady_clock::now() + std::chrono::seconds(5);
        while (!Poco::File(ready).exists() && Poco::Process::isRunning(holder) &&
               std::chrono::steady_clock::now() < readyDeadline)
            std::this_thread::sleep_for(std::chrono::milliseconds(25));
        if (!Poco::File(ready).exists())
        {
            if (Poco::Process::isRunning(holder)) Poco::Process::kill(holder);
            return 1;
        }

        bool rejected = false;
        try
        {
            PocoDDS::BundleManagement::BundleDeploymentCoordinator contender(
                {repository.toString(), state.toString()});
            contender.recoverInterruptedActivation();
        }
        catch (const Poco::FileAccessDeniedException&)
        {
            rejected = true;
        }
        if (!rejected)
        {
            Poco::Process::kill(holder);
            return 2;
        }

        Poco::Process::kill(holder.id());
        bool crashRecovered = false;
        const auto recoveryDeadline = std::chrono::steady_clock::now() + std::chrono::seconds(3);
        while (!crashRecovered && std::chrono::steady_clock::now() < recoveryDeadline)
        {
            try
            {
                PocoDDS::BundleManagement::BundleDeploymentCoordinator recovered(
                    {repository.toString(), state.toString()});
                crashRecovered = recovered.recoverInterruptedActivation() &&
                                 recovered.status().state == "rolledBack";
            }
            catch (const Poco::FileAccessDeniedException&)
            {
                std::this_thread::sleep_for(std::chrono::milliseconds(25));
            }
        }
        if (!crashRecovered || read(child(repository, "bundle.bndl")) != "stable")
            return 3;

        Poco::File(root).remove(true);
        std::cout << "BUNDLE_DEPLOYMENT_PROCESS_LEASE_PASS contention=1 crashRelease=1\n";
        return 0;
    }
    catch (const Poco::Exception& exception)
    {
        std::cerr << exception.displayText() << '\n';
        if (Poco::File(root).exists()) Poco::File(root).remove(true);
        return 10;
    }
}
