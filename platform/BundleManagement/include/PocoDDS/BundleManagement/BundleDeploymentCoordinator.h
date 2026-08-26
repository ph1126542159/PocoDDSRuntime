#pragma once

#include "PocoDDS/BundleManagement/BundleRepositoryAuthorization.h"

#include <cstdint>
#include <string>

#if defined(_WIN32)
#if defined(PDR_BUNDLE_MANAGEMENT_EXPORTS)
#define PDR_BUNDLE_DEPLOYMENT_API __declspec(dllexport)
#else
#define PDR_BUNDLE_DEPLOYMENT_API __declspec(dllimport)
#endif
#else
#define PDR_BUNDLE_DEPLOYMENT_API
#endif

namespace PocoDDS::BundleManagement
{
struct BundleDeploymentOptions
{
    std::string repositoryDirectory;
    std::string stateDirectory;
    BundleRepositoryAuthorizationOptions authorization;
};

struct BundleDeploymentStatus
{
    std::string transactionId;
    std::string state{"idle"};
    std::string candidateDigest;
    std::string error;
    std::string repositoryId;
    std::string publisherId;
    std::string signingKeyId;
    std::string trustPolicyId;
    std::string trustPolicySha256;
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

/// Coordinates the process boundary of a native Bundle repository deployment.
/// The caller must stop the supervised Runtime before calling rollback().
class PDR_BUNDLE_DEPLOYMENT_API BundleDeploymentCoordinator final
{
  public:
    explicit BundleDeploymentCoordinator(BundleDeploymentOptions options);
    ~BundleDeploymentCoordinator();

    BundleDeploymentCoordinator(const BundleDeploymentCoordinator&) = delete;
    BundleDeploymentCoordinator& operator=(const BundleDeploymentCoordinator&) = delete;

    BundleDeploymentStatus status() const;
    bool activationRequested() const;
    std::string beginActivation();
    bool activationReady(const std::string& transactionId) const;
    void commit(const std::string& transactionId);
    void rollback(const std::string& transactionId, const std::string& error);
    bool recoverInterruptedActivation();

  private:
    class Lease;
    BundleDeploymentOptions _options;
    Lease* _lease;
};
} // namespace PocoDDS::BundleManagement
