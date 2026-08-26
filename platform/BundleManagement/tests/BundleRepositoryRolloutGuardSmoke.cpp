#include "PocoDDS/BundleManagement/BundleRepositoryRolloutGuard.h"

#include "Poco/Exception.h"
#include "Poco/File.h"
#include "Poco/FileStream.h"
#include "Poco/Path.h"
#include "Poco/Timestamp.h"

#include <functional>
#include <iostream>
#include <string>

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

PocoDDS::BundleManagement::BundleRepositoryAuthorizationEvidence evidence(
    std::uint64_t sequence)
{
    PocoDDS::BundleManagement::BundleRepositoryAuthorizationEvidence result;
    result.verified = true;
    result.repositoryId = "runtime-main";
    result.publisherId = "release-team";
    result.keyId = "bundle-2026";
    result.policyId = "bundle-policy-v1";
    result.policySha256 = std::string(64, 'a');
    result.attestationSha256 = std::string(64, sequence % 2 == 0 ? 'b' : 'c');
    result.rolloutSequence = sequence;
    result.releaseManifestSha256 = std::string(64, 'd');
    result.sbomSha256 = std::string(64, 'e');
    result.artifactSetSha256 = std::string(64, 'f');
    result.releaseVersion = "0.1.0";
    result.gitCommit = std::string(40, '1');
    result.builderId = "test-builder";
    result.buildProfile = "server";
    return result;
}

bool rejected(const std::function<void()>& operation)
{
    try
    {
        operation();
        return false;
    }
    catch (const Poco::Exception&)
    {
        return true;
    }
}
} // namespace

int main()
{
    Poco::Path root(Poco::Path::temp());
    root.pushDirectory("pdr-bundle-rollout-" +
                       std::to_string(Poco::Timestamp().epochMicroseconds()));
    root.makeDirectory();
    Poco::File(root).createDirectories();
    const std::string digest10(64, '1');
    const std::string digest11(64, '2');

    try
    {
        using PocoDDS::BundleManagement::BundleRepositoryRolloutGuard;
        BundleRepositoryRolloutGuard::verifyCandidate(
            root.toString(), digest10, evidence(10));
        auto committed = BundleRepositoryRolloutGuard::commitCandidate(
            root.toString(), digest10, evidence(10));
        if (!committed.initialized || !committed.provenanceBound ||
            committed.rolloutSequence != 10 ||
            committed.candidateDigest != digest10)
            return 1;

        BundleRepositoryRolloutGuard::verifyCandidate(
            root.toString(), digest10, evidence(10));
        if (!rejected([&] {
                BundleRepositoryRolloutGuard::verifyCandidate(
                    root.toString(), digest10, evidence(9));
            })) return 2;
        if (!rejected([&] {
                BundleRepositoryRolloutGuard::verifyCandidate(
                    root.toString(), digest11, evidence(10));
            })) return 3;

        // A higher candidate is admissible during probation, but does not advance
        // the accepted sequence until the process-level commit succeeds.
        BundleRepositoryRolloutGuard::verifyCandidate(
            root.toString(), digest11, evidence(11));
        if (BundleRepositoryRolloutGuard::state(root.toString()).rolloutSequence != 10)
            return 4;
        BundleRepositoryRolloutGuard::verifyCandidate(
            root.toString(), digest10, evidence(10));

        committed = BundleRepositoryRolloutGuard::commitCandidate(
            root.toString(), digest11, evidence(11));
        if (committed.rolloutSequence != 11 || committed.candidateDigest != digest11)
            return 5;
        if (!rejected([&] {
                BundleRepositoryRolloutGuard::verifyCandidate(
                    root.toString(), digest10, evidence(10));
            })) return 6;
        BundleRepositoryRolloutGuard::verifyCandidate(
            root.toString(), digest11, evidence(11));

        // An early sequence-only high-water state is upgraded in place only
        // after the same accepted digest receives complete provenance evidence.
        write(child(root, "repository-rollout-high-water.properties"),
              "schemaVersion=1\nrepositoryId=runtime-main\nrolloutSequence=11\n"
              "candidateDigest=" + digest11 + "\npublisherId=release-team\n"
              "signingKeyId=bundle-2026\ntrustPolicyId=bundle-policy-v1\n"
              "trustPolicySha256=" + std::string(64, 'a') +
              "\nattestationSha256=" + std::string(64, 'c') + "\n");
        committed = BundleRepositoryRolloutGuard::commitCandidate(
            root.toString(), digest11, evidence(11));
        if (!committed.provenanceBound || committed.releaseVersion != "0.1.0")
            return 7;

        write(child(root, "repository-rollout-high-water.properties"),
              "schemaVersion=1\nrepositoryId=runtime-main\nrolloutSequence=broken\n");
        if (!rejected([&] { BundleRepositoryRolloutGuard::state(root.toString()); }))
            return 8;

        Poco::File(root).remove(true);
        std::cout << "BUNDLE_REPOSITORY_ROLLOUT_GUARD_PASS bootstrap=1 retry=1 "
                     "lowerRejected=1 sequenceReuseRejected=1 probation=1 replayRejected=1 "
                     "provenanceMigration=1 malformedStateRejected=1\n";
        return 0;
    }
    catch (const Poco::Exception& error)
    {
        std::cerr << error.displayText() << '\n';
        if (Poco::File(root).exists()) Poco::File(root).remove(true);
        return 10;
    }
}
