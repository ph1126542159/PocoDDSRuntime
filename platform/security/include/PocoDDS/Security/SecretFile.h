#pragma once

#include <Poco/Timestamp.h>

#include <cstddef>
#include <string>
#include <utility>

namespace PocoDDS::Security
{
struct SecretFileMaterial
{
    std::string value;
    std::string absolutePath;
    std::size_t size{0};
    Poco::Timestamp lastModified;
    bool permissionsVerified{false};
    bool restricted{false};
};

std::pair<bool, bool> inspectSecretFilePermissions(
    const std::string& absolutePath) noexcept;

SecretFileMaterial loadSecretFile(
    const std::string& path,
    std::size_t maximumBytes = 16 * 1024,
    const std::string& description = "secret");
} // namespace PocoDDS::Security
