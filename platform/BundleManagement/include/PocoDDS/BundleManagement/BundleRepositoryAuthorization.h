#pragma once

#include <cstdint>
#include <string>

#if defined(_WIN32)
#if defined(PDR_BUNDLE_MANAGEMENT_EXPORTS)
#define PDR_BUNDLE_AUTHORIZATION_API __declspec(dllexport)
#else
#define PDR_BUNDLE_AUTHORIZATION_API __declspec(dllimport)
#endif
#else
#define PDR_BUNDLE_AUTHORIZATION_API
#endif

namespace PocoDDS::BundleManagement
{
struct BundleRepositoryAuthorizationOptions
{
    bool required{false};
    std::string repositoryId;
    std::string evidenceDirectory;
    std::string trustPolicyFile;
    std::string expectedTrustPolicyId;
    std::string expectedTrustPolicySha256;
    std::string trustedKeysDirectory;
};

struct BundleRepositoryAuthorizationEvidence
{
    bool verified{false};
    std::string repositoryId;
    std::string publisherId;
    std::string keyId;
    std::string policyId;
    std::string policySha256;
    std::string attestationSha256;
    std::uint64_t rolloutSequence{0};
    std::string releaseManifestSha256;
    std::string sbomSha256;
    std::string artifactSetSha256;
    std::string releaseVersion;
    std::string gitCommit;
    std::string builderId;
    std::string buildProfile;
};

/// Verifies publisher authorization for an already calculated repository digest.
/// Attestations are stored outside the candidate repository as
/// <digest>.attestation.json and <digest>.sig.json to avoid digest cycles.
class PDR_BUNDLE_AUTHORIZATION_API BundleRepositoryAuthorization final
{
  public:
    static BundleRepositoryAuthorizationEvidence verify(
        const std::string& repositoryDirectory,
        const std::string& candidateDigest,
        const BundleRepositoryAuthorizationOptions& options);
};
} // namespace PocoDDS::BundleManagement
