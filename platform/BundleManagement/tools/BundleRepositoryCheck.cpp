#include "PocoDDS/BundleManagement/BundleRepositoryAuthorization.h"
#include "PocoDDS/BundleManagement/BundleRepositoryFingerprint.h"

#include "Poco/Exception.h"
#include "Poco/JSON/Object.h"
#include "Poco/JSON/Stringifier.h"

#include <iostream>
#include <map>
#include <sstream>
#include <string>

namespace
{
void usage()
{
    std::cerr
        << "usage:\n"
        << "  pdr-bundle-repository-check fingerprint REPOSITORY_DIRECTORY\n"
        << "  pdr-bundle-repository-check authorize REPOSITORY_DIRECTORY"
           " --repository-id ID --evidence-directory DIRECTORY"
           " --trust-policy-file FILE --expected-trust-policy-id ID"
           " --expected-trust-policy-sha256 SHA256"
           " --trusted-keys-directory DIRECTORY\n";
}

std::map<std::string, std::string> options(int argc, char** argv)
{
    if ((argc - 3) % 2 != 0) throw Poco::InvalidArgumentException("missing option value");
    std::map<std::string, std::string> result;
    for (int index = 3; index < argc; index += 2)
    {
        const std::string name(argv[index]);
        if (name.rfind("--", 0) != 0 || argv[index + 1][0] == '\0' ||
            !result.emplace(name, argv[index + 1]).second)
            throw Poco::InvalidArgumentException("invalid or duplicate option", name);
    }
    return result;
}

const std::string& required(const std::map<std::string, std::string>& values,
                            const std::string& name)
{
    const auto found = values.find(name);
    if (found == values.end()) throw Poco::InvalidArgumentException("missing option", name);
    return found->second;
}

void authorize(int argc, char** argv)
{
    const auto values = options(argc, argv);
    if (values.size() != 6) throw Poco::InvalidArgumentException("unexpected authorize option");
    PocoDDS::BundleManagement::BundleRepositoryAuthorizationOptions authorization;
    authorization.required = true;
    authorization.repositoryId = required(values, "--repository-id");
    authorization.evidenceDirectory = required(values, "--evidence-directory");
    authorization.trustPolicyFile = required(values, "--trust-policy-file");
    authorization.expectedTrustPolicyId = required(values, "--expected-trust-policy-id");
    authorization.expectedTrustPolicySha256 =
        required(values, "--expected-trust-policy-sha256");
    authorization.trustedKeysDirectory = required(values, "--trusted-keys-directory");

    const std::string digest =
        PocoDDS::BundleManagement::BundleRepositoryFingerprint::calculateDirectory(argv[2]);
    const auto evidence = PocoDDS::BundleManagement::BundleRepositoryAuthorization::verify(
        argv[2], digest, authorization);
    Poco::JSON::Object report;
    report.set("result", "BUNDLE_REPOSITORY_AUTHORIZATION_PASS");
    report.set("verified", evidence.verified);
    report.set("candidateDigest", digest);
    report.set("repositoryId", evidence.repositoryId);
    report.set("publisherId", evidence.publisherId);
    report.set("signingKeyId", evidence.keyId);
    report.set("trustPolicyId", evidence.policyId);
    report.set("trustPolicySha256", evidence.policySha256);
    report.set("attestationSha256", evidence.attestationSha256);
    report.set("rolloutSequence", evidence.rolloutSequence);
    report.set("releaseManifestSha256", evidence.releaseManifestSha256);
    report.set("sbomSha256", evidence.sbomSha256);
    report.set("artifactSetSha256", evidence.artifactSetSha256);
    report.set("releaseVersion", evidence.releaseVersion);
    report.set("gitCommit", evidence.gitCommit);
    report.set("builderId", evidence.builderId);
    report.set("buildProfile", evidence.buildProfile);
    std::ostringstream rendered;
    Poco::JSON::Stringifier::stringify(report, rendered);
    std::cout << rendered.str() << '\n';
}
} // namespace

int main(int argc, char** argv)
{
    if (argc < 3)
    {
        usage();
        return 2;
    }
    try
    {
        const std::string command(argv[1]);
        if (command == "fingerprint" && argc == 3)
        {
            const std::string digest =
                PocoDDS::BundleManagement::BundleRepositoryFingerprint::calculateDirectory(argv[2]);
            std::cout << "BUNDLE_REPOSITORY_FINGERPRINT sha256=" << digest << '\n';
        }
        else if (command == "authorize")
            authorize(argc, argv);
        else
        {
            usage();
            return 2;
        }
        return 0;
    }
    catch (const Poco::Exception& error)
    {
        std::cerr << "BUNDLE_REPOSITORY_ERROR: " << error.displayText() << '\n';
        return 1;
    }
    catch (const std::exception& error)
    {
        std::cerr << "BUNDLE_REPOSITORY_ERROR: " << error.what() << '\n';
        return 1;
    }
}
