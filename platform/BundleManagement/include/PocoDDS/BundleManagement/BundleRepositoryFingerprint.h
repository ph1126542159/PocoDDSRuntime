#pragma once

#include <string>

#if defined(_WIN32)
#if defined(PDR_BUNDLE_MANAGEMENT_EXPORTS)
#define PDR_BUNDLE_FINGERPRINT_API __declspec(dllexport)
#else
#define PDR_BUNDLE_FINGERPRINT_API __declspec(dllimport)
#endif
#else
#define PDR_BUNDLE_FINGERPRINT_API
#endif

namespace PocoDDS::BundleManagement
{
/// Returns a deterministic SHA-256 digest of names, types and contents below a
/// single Bundle repository directory. Timestamps and absolute paths are not
/// included, so the same repository generation has the same digest after copy.
class PDR_BUNDLE_FINGERPRINT_API BundleRepositoryFingerprint final
{
  public:
    static std::string calculateDirectory(const std::string& repositoryDirectory);
};
} // namespace PocoDDS::BundleManagement
