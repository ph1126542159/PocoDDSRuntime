#pragma once

#include "PocoDDS/BundleManagement/BundleRepositoryAuthorization.h"

#include <cstdint>
#include <string>

#if defined(_WIN32)
#if defined(PDR_BUNDLE_MANAGEMENT_EXPORTS)
#define PDR_BUNDLE_ROLLOUT_API __declspec(dllexport)
#else
#define PDR_BUNDLE_ROLLOUT_API __declspec(dllimport)
#endif
#else
#define PDR_BUNDLE_ROLLOUT_API
#endif

namespace PocoDDS::BundleManagement
{
struct BundleRepositoryRolloutState
{
    bool initialized{false};
    bool provenanceBound{false};
    std::string repositoryId;
    std::uint64_t rolloutSequence{0};
    std::string candidateDigest;
    std::string publisherId;
    std::string signingKeyId;
    std::string trustPolicyId;
    std::string trustPolicySha256;
    std::string attestationSha256;
    std::string releaseManifestSha256;
    std::string sbomSha256;
    std::string artifactSetSha256;
    std::string releaseVersion;
    std::string gitCommit;
    std::string builderId;
    std::string buildProfile;
};

/// Enforces a durable monotonic rollout sequence for one authorized repository.
/// A sequence can be retried only with the same candidate digest. The high-water
/// mark is advanced only by commitCandidate(), after process-level readiness.
class PDR_BUNDLE_ROLLOUT_API BundleRepositoryRolloutGuard final
{
  public:
    static BundleRepositoryRolloutState state(const std::string& stateDirectory);

    static void verifyCandidate(
        const std::string& stateDirectory,
        const std::string& candidateDigest,
        const BundleRepositoryAuthorizationEvidence& authorization);

    static BundleRepositoryRolloutState commitCandidate(
        const std::string& stateDirectory,
        const std::string& candidateDigest,
        const BundleRepositoryAuthorizationEvidence& authorization);
};
} // namespace PocoDDS::BundleManagement
