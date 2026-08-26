#include "PocoDDS/Security/SecretFile.h"

#include <Poco/Exception.h>
#include <Poco/File.h>
#include <Poco/Path.h>
#include <Poco/UnicodeConverter.h>

#include <fstream>
#include <iterator>
#include <limits>

#ifdef _WIN32
#include <Windows.h>
#include <Aclapi.h>
#else
#include <sys/stat.h>
#endif

namespace PocoDDS::Security
{
std::pair<bool, bool> inspectSecretFilePermissions(
    const std::string& absolutePath) noexcept
{
#ifdef _WIN32
    PACL dacl = nullptr;
    PSECURITY_DESCRIPTOR descriptor = nullptr;
    std::wstring widePath;
    Poco::UnicodeConverter::toUTF16(absolutePath, widePath);
    const DWORD status = GetNamedSecurityInfoW(
        const_cast<wchar_t*>(widePath.c_str()), SE_FILE_OBJECT,
        DACL_SECURITY_INFORMATION, nullptr, nullptr, &dacl, nullptr,
        &descriptor);
    if (status != ERROR_SUCCESS || !dacl)
    {
        if (descriptor) LocalFree(descriptor);
        return {false, false};
    }
    bool restricted = true;
    for (const WELL_KNOWN_SID_TYPE type : {
             WinWorldSid, WinAuthenticatedUserSid, WinBuiltinUsersSid,
             WinBuiltinGuestsSid})
    {
        BYTE sidBuffer[SECURITY_MAX_SID_SIZE];
        DWORD sidSize = sizeof(sidBuffer);
        if (!CreateWellKnownSid(type, nullptr, sidBuffer, &sidSize))
        {
            LocalFree(descriptor);
            return {false, false};
        }
        TRUSTEE_W trustee{};
        trustee.TrusteeForm = TRUSTEE_IS_SID;
        trustee.TrusteeType = TRUSTEE_IS_WELL_KNOWN_GROUP;
        trustee.ptstrName = reinterpret_cast<LPWSTR>(sidBuffer);
        ACCESS_MASK rights = 0;
        if (GetEffectiveRightsFromAclW(dacl, &trustee, &rights) !=
            ERROR_SUCCESS)
        {
            LocalFree(descriptor);
            return {false, false};
        }
        constexpr ACCESS_MASK sensitive =
            GENERIC_READ | GENERIC_WRITE | FILE_GENERIC_READ |
            FILE_GENERIC_WRITE | FILE_READ_DATA | FILE_WRITE_DATA |
            FILE_APPEND_DATA | DELETE | WRITE_DAC | WRITE_OWNER;
        if ((rights & sensitive) != 0) restricted = false;
    }
    LocalFree(descriptor);
    return {true, restricted};
#else
    struct stat information{};
    if (::stat(absolutePath.c_str(), &information) != 0)
        return {false, false};
    return {true, (information.st_mode & (S_IRWXG | S_IRWXO)) == 0};
#endif
}

SecretFileMaterial loadSecretFile(const std::string& configuredPath,
                                  std::size_t maximumBytes,
                                  const std::string& description)
{
    if (configuredPath.empty())
        throw Poco::InvalidArgumentException(description + " path is empty");
    if (maximumBytes == 0 ||
        maximumBytes > static_cast<std::size_t>(
                           std::numeric_limits<std::streamsize>::max()))
        throw Poco::InvalidArgumentException(
            description + " maximum byte limit is invalid");

    Poco::Path path(configuredPath);
    path.makeAbsolute();
    Poco::File file(path);
    if (!file.exists() || !file.isFile())
        throw Poco::NotFoundException(
            description + " file is missing", path.toString());
    const auto fileSize = file.getSize();
    if (fileSize > maximumBytes)
        throw Poco::RangeException(
            description + " file exceeds configured capacity",
            path.toString());

    std::ifstream stream(path.toString(), std::ios::binary);
    if (!stream)
        throw Poco::OpenFileException(description + " file", path.toString());
    std::string value((std::istreambuf_iterator<char>(stream)),
                      std::istreambuf_iterator<char>());
    if (!stream.eof() && stream.fail())
        throw Poco::ReadFileException(description + " file", path.toString());
    while (!value.empty() &&
           (value.back() == '\n' || value.back() == '\r'))
        value.pop_back();
    if (value.find('\n') != std::string::npos ||
        value.find('\r') != std::string::npos)
        throw Poco::InvalidArgumentException(
            description + " file contains embedded newline");
    if (value.empty())
        throw Poco::InvalidArgumentException(
            description + " file is empty", path.toString());

    const auto [verified, restricted] =
        inspectSecretFilePermissions(path.toString());
    return {std::move(value), path.toString(),
            static_cast<std::size_t>(fileSize), file.getLastModified(),
            verified, restricted};
}
} // namespace PocoDDS::Security
