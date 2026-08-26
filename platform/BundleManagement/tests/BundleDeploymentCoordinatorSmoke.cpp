#include "PocoDDS/BundleManagement/BundleDeploymentCoordinator.h"
#include "PocoDDS/BundleManagement/BundleRepositoryFingerprint.h"

#include "Poco/Exception.h"
#include "Poco/File.h"
#include "Poco/FileStream.h"
#include "Poco/Path.h"
#include "Poco/Timestamp.h"

#include <iostream>

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

void request(const Poco::Path& state, const std::string& id, const std::string& digest)
{
    write(child(state, "transaction.properties"),
          "transactionId=" + id + "\nstate=restartRequired\nbundleCount=1\n"
          "candidateDigest=" + digest + "\nerror=\n");
}

void acknowledge(const Poco::Path& state, const std::string& id, const std::string& digest)
{
    write(child(state, "transaction.properties"),
          "transactionId=" + id + "\nstate=activationReady\nbundleCount=1\n"
          "candidateDigest=" + digest + "\nerror=\n");
}
} // namespace

int main()
{
    Poco::Path root(Poco::Path::temp());
    root.pushDirectory("pdr-bundle-deployment-" +
                       std::to_string(Poco::Timestamp().epochMicroseconds()));
    root.makeDirectory();
    Poco::Path repository(root); repository.pushDirectory("bundles"); repository.makeDirectory();
    Poco::Path state(root); state.pushDirectory("state"); state.makeDirectory();
    Poco::Path lkg(state); lkg.pushDirectory("last-known-good"); lkg.makeDirectory();
    Poco::File(repository).createDirectories();
    Poco::File(state).createDirectories();
    Poco::File(lkg).createDirectories();
    write(child(repository, "bundle.bndl"), "candidate-v1");
    write(child(lkg, "bundle.bndl"), "stable-v0");

    try
    {
        PocoDDS::BundleManagement::BundleDeploymentCoordinator coordinator(
            {repository.toString(), state.toString()});

        const auto digestV1 = PocoDDS::BundleManagement::BundleRepositoryFingerprint::
            calculateDirectory(repository.toString());
        Poco::Path clone(root); clone.pushDirectory("repository-clone"); clone.makeDirectory();
        Poco::File(clone).createDirectories();
        write(child(clone, "bundle.bndl"), "candidate-v1");
        if (PocoDDS::BundleManagement::BundleRepositoryFingerprint::calculateDirectory(
                clone.toString()) != digestV1)
            return 1;
        Poco::File(clone).remove(true);
        request(state, "tx-commit", digestV1);
        if (!coordinator.activationRequested() || coordinator.beginActivation() != "tx-commit")
            return 2;
        acknowledge(state, "tx-commit", digestV1);
        if (!coordinator.activationReady("tx-commit"))
            return 3;
        coordinator.commit("tx-commit");
        if (coordinator.status().state != "committed" ||
            Poco::File(child(state, "deployment-rollback")).exists())
            return 4;

        write(child(repository, "bundle.bndl"), "candidate-v2");
        write(child(lkg, "bundle.bndl"), "stable-v1");
        const auto digestV2 = PocoDDS::BundleManagement::BundleRepositoryFingerprint::
            calculateDirectory(repository.toString());
        request(state, "tx-rollback", digestV2);
        coordinator.beginActivation();
        coordinator.rollback("tx-rollback", "fault injection");
        if (coordinator.status().state != "rolledBack" ||
            read(child(repository, "bundle.bndl")) != "stable-v1")
            return 5;

        write(child(repository, "bundle.bndl"), "candidate-tamper");
        write(child(lkg, "bundle.bndl"), "stable-v2");
        const auto tamperDigest = PocoDDS::BundleManagement::BundleRepositoryFingerprint::
            calculateDirectory(repository.toString());
        request(state, "tx-tamper", tamperDigest);
        coordinator.beginActivation();
        write(child(repository, "bundle.bndl"), "candidate-tampered-after-preflight");
        acknowledge(state, "tx-tamper", tamperDigest);
        if (coordinator.activationReady("tx-tamper"))
            return 6;
        coordinator.rollback("tx-tamper", "candidate digest changed");

        write(child(repository, "bundle.bndl"), "candidate-v3");
        const auto digestV3 = PocoDDS::BundleManagement::BundleRepositoryFingerprint::
            calculateDirectory(repository.toString());
        request(state, "tx-recover", digestV3);
        {
            PocoDDS::BundleManagement::BundleDeploymentCoordinator abandoned(
                {repository.toString(), state.toString()});
            abandoned.beginActivation();
            bool leaseRejected = false;
            try
            {
                PocoDDS::BundleManagement::BundleDeploymentCoordinator contender(
                    {repository.toString(), state.toString()});
                contender.recoverInterruptedActivation();
            }
            catch (const Poco::FileAccessDeniedException&)
            {
                leaseRejected = true;
            }
            if (!leaseRejected) return 7;
        }
        if (!coordinator.recoverInterruptedActivation() ||
            coordinator.status().state != "rolledBack" ||
            read(child(repository, "bundle.bndl")) != "stable-v2")
            return 8;

        // A crash after the durable "committing" transition must resume commit,
        // never take the now-ambiguous rollback path.
        write(child(repository, "bundle.bndl"), "candidate-v4");
        const auto digestV4 = PocoDDS::BundleManagement::BundleRepositoryFingerprint::
            calculateDirectory(repository.toString());
        Poco::Path staleRollback(state);
        staleRollback.pushDirectory("deployment-rollback");
        staleRollback.makeDirectory();
        Poco::File(staleRollback).createDirectories();
        write(child(staleRollback, "bundle.bndl"), "stable-v3");
        write(child(state, "deployment.properties"),
              "transactionId=tx-resume-commit\nstate=committing\n"
              "candidateDigest=" + digestV4 + "\nauthorizationVerified=false\n"
              "rolloutSequence=0\nerror=\n");
        if (!coordinator.recoverInterruptedActivation() ||
            coordinator.status().state != "committed" ||
            Poco::File(staleRollback).exists())
            return 9;

        Poco::File(root).remove(true);
        std::cout << "Bundle deployment coordinator smoke passed\n";
        return 0;
    }
    catch (const Poco::Exception& exception)
    {
        std::cerr << exception.displayText() << '\n';
        if (Poco::File(root).exists()) Poco::File(root).remove(true);
        return 10;
    }
}
