#include "PocoDDS/Security/PrincipalStore.h"

#include "Poco/Environment.h"
#include "Poco/Exception.h"
#include "Poco/File.h"
#include "Poco/Path.h"
#include "Poco/UnicodeConverter.h"

#include <algorithm>
#include <cctype>
#include <fstream>
#include <mutex>
#include <sstream>
#include <utility>

#ifdef _WIN32
#include <Windows.h>
#include <Aclapi.h>
#else
#include <sys/stat.h>
#endif

namespace PocoDDS::Security
{
namespace
{
bool constantTimeEquals(const std::string& supplied, const std::string& expected) noexcept
{
    const std::size_t size = std::max(supplied.size(), expected.size());
    unsigned char difference = static_cast<unsigned char>(supplied.size() ^ expected.size());
    for (std::size_t index = 0; index < size; ++index)
    {
        const unsigned char left = index < supplied.size() ?
            static_cast<unsigned char>(supplied[index]) : 0;
        const unsigned char right = index < expected.size() ?
            static_cast<unsigned char>(expected[index]) : 0;
        difference = static_cast<unsigned char>(difference | (left ^ right));
    }
    return difference == 0 && !supplied.empty();
}

PermissionSet parsePermissions(const std::string& value)
{
    PermissionSet permissions;
    std::istringstream stream(value);
    std::string item;
    while (std::getline(stream, item, ','))
    {
        item.erase(item.begin(), std::find_if(item.begin(), item.end(), [](unsigned char ch) {
            return !std::isspace(ch);
        }));
        item.erase(std::find_if(item.rbegin(), item.rend(), [](unsigned char ch) {
            return !std::isspace(ch);
        }).base(), item.end());
        if (item == "*") return managementPermissions();
        if (!item.empty()) permissions.insert(item);
    }
    return permissions;
}

struct TokenMaterial
{
    std::string token;
    bool fileBacked{false};
    bool permissionsVerified{true};
    bool restricted{true};
};

std::pair<bool, bool> restrictedTokenFile(const std::string& path)
{
#ifdef _WIN32
    PACL dacl = nullptr;
    PSECURITY_DESCRIPTOR descriptor = nullptr;
    std::wstring widePath;
    Poco::UnicodeConverter::toUTF16(path, widePath);
    const DWORD status = GetNamedSecurityInfoW(
        const_cast<wchar_t*>(widePath.c_str()), SE_FILE_OBJECT, DACL_SECURITY_INFORMATION,
        nullptr, nullptr, &dacl, nullptr, &descriptor);
    if (status != ERROR_SUCCESS || !dacl)
    {
        if (descriptor) LocalFree(descriptor);
        return {false, false};
    }
    bool restricted = true;
    for (const WELL_KNOWN_SID_TYPE type : {
             WinWorldSid, WinAuthenticatedUserSid, WinBuiltinUsersSid, WinBuiltinGuestsSid})
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
        if (GetEffectiveRightsFromAclW(dacl, &trustee, &rights) != ERROR_SUCCESS)
        {
            LocalFree(descriptor);
            return {false, false};
        }
        constexpr ACCESS_MASK sensitive = GENERIC_READ | GENERIC_WRITE | FILE_GENERIC_READ |
            FILE_GENERIC_WRITE | FILE_READ_DATA | FILE_WRITE_DATA | FILE_APPEND_DATA |
            DELETE | WRITE_DAC | WRITE_OWNER;
        if ((rights & sensitive) != 0) restricted = false;
    }
    LocalFree(descriptor);
    return {true, restricted};
#else
    struct stat information{};
    if (::stat(path.c_str(), &information) != 0) return {false, false};
    return {true, (information.st_mode & (S_IRWXG | S_IRWXO)) == 0};
#endif
}

TokenMaterial tokenFromFile(const std::string& configuredPath,
                          const Poco::Util::AbstractConfiguration& configuration,
                          const std::string& description)
{
    Poco::Path path(configuration.expand(configuredPath));
    path.makeAbsolute();
    Poco::File file(path);
    if (!file.exists() || !file.isFile())
        throw Poco::NotFoundException(description + " file is missing", path.toString());
    if (file.getSize() > 16 * 1024)
        throw Poco::RangeException(description + " file exceeds 16 KiB", path.toString());
    std::ifstream stream(path.toString(), std::ios::binary);
    if (!stream) throw Poco::OpenFileException(description + " file", path.toString());
    std::string token((std::istreambuf_iterator<char>(stream)),
                      std::istreambuf_iterator<char>());
    while (!token.empty() && (token.back() == '\n' || token.back() == '\r')) token.pop_back();
    if (token.find('\n') != std::string::npos || token.find('\r') != std::string::npos)
        throw Poco::InvalidArgumentException(description + " file contains embedded newline");
    if (token.empty())
        throw Poco::InvalidArgumentException(description + " file is empty", path.toString());
    const auto [verified, restricted] = restrictedTokenFile(path.toString());
    return {std::move(token), true, verified, restricted};
}

TokenMaterial tokenFromSource(const Poco::Util::AbstractConfiguration& configuration,
                            const std::string& environmentKey,
                            const std::string& fileKey,
                            const std::string& description)
{
    const std::string environmentName = configuration.getString(environmentKey, "");
    const std::string configuredPath = configuration.getString(fileKey, "");
    if (environmentName.empty() == configuredPath.empty())
        throw Poco::InvalidArgumentException(
            description + " requires exactly one tokenEnvironment or tokenFile");
    if (!configuredPath.empty())
        return tokenFromFile(configuredPath, configuration, description);
    if (!Poco::Environment::has(environmentName))
        throw Poco::NotFoundException(description + " environment is missing", environmentName);
    const std::string token = Poco::Environment::get(environmentName);
    if (token.empty())
        throw Poco::InvalidArgumentException(description + " environment is empty", environmentName);
    return {token, false, true, true};
}

AuthenticatedPrincipal copyPrincipal(const Principal& principal)
{
    return {principal.id(), principal.permissions()};
}

}

const PermissionSet& managementPermissions()
{
    static const PermissionSet permissions{
        "protocol.manage", "process.manage", "bundle.manage", "configuration.manage",
        "identity.manage", "audit.read", "task.read", "task.cancel"};
    return permissions;
}

bool Principal::authorized(const std::string& permission) const noexcept
{
    return _permissions.count(permission) != 0;
}

PrincipalStore PrincipalStore::fromManagementConfiguration(
    const Poco::Util::AbstractConfiguration& configuration)
{
    PrincipalStore store;
    store._required = configuration.getBool(
        "pdr.management.authentication.required", false);
    const std::string legacyEnvironmentKey =
        "pdr.management.authentication.tokenEnvironment";
    const std::string legacyFileKey = "pdr.management.authentication.tokenFile";
    if (!configuration.getString(legacyEnvironmentKey, "").empty() ||
        !configuration.getString(legacyFileKey, "").empty())
    {
        auto material = tokenFromSource(configuration, legacyEnvironmentKey, legacyFileKey,
                                        "management token");
        PrincipalStore::recordSource(store, material.fileBacked,
                                     material.permissionsVerified, material.restricted);
        PrincipalStore::appendEntry(store, "legacy-admin", std::move(material.token),
                                    managementPermissions());
    }

    const int count = configuration.getInt(
        "pdr.management.authentication.principals.count", 0);
    if (count < 0 || count > 64)
        throw Poco::RangeException("management principal count", std::to_string(count));
    for (int index = 0; index < count; ++index)
    {
        const std::string prefix = "pdr.management.authentication.principals." +
            std::to_string(index) + ".";
        const std::string id = configuration.getString(prefix + "id", "");
        PermissionSet permissions = parsePermissions(
            configuration.getString(prefix + "permissions", ""));
        if (id.empty() || permissions.empty())
            throw Poco::InvalidArgumentException("management principal is incomplete", prefix);
        auto material = tokenFromSource(configuration, prefix + "tokenEnvironment",
                                        prefix + "tokenFile", "management principal token");
        PrincipalStore::recordSource(store, material.fileBacked,
                                     material.permissionsVerified, material.restricted);
        PrincipalStore::appendEntry(store, id, std::move(material.token),
                                    std::move(permissions));
    }
    if (store._required && store._entries.empty())
        throw Poco::InvalidArgumentException(
            "management authentication requires at least one principal");
    return store;
}

const Principal* PrincipalStore::authenticateBearerToken(const std::string& token) const noexcept
{
    const Principal* matched = nullptr;
    for (const auto& entry : _entries)
        if (constantTimeEquals(token, entry.token)) matched = &entry.principal;
    return matched;
}

const Principal* PrincipalStore::principalById(const std::string& id) const noexcept
{
    for (const auto& entry : _entries)
        if (entry.principal.id() == id) return &entry.principal;
    return nullptr;
}

const Principal* PrincipalStore::authenticateAuthorizationHeader(
    const std::string& header) const noexcept
{
    constexpr const char* prefix = "Bearer ";
    if (header.rfind(prefix, 0) != 0) return nullptr;
    return authenticateBearerToken(header.substr(std::char_traits<char>::length(prefix)));
}

void PrincipalStore::appendEntry(PrincipalStore& store, std::string id, std::string token,
                                 PermissionSet permissions)
{
    for (const auto& entry : store._entries)
    {
        if (entry.principal.id() == id)
            throw Poco::InvalidArgumentException("duplicate management principal ID", id);
        if (constantTimeEquals(entry.token, token))
            throw Poco::InvalidArgumentException("duplicate management bearer token");
    }
    PrincipalStore::Entry entry;
    entry.principal._id = std::move(id);
    entry.principal._permissions = std::move(permissions);
    entry.token = std::move(token);
    store._entries.push_back(std::move(entry));
}

void PrincipalStore::recordSource(PrincipalStore& store, bool fileBacked,
                                  bool permissionsVerified, bool restricted)
{
    if (!fileBacked)
    {
        ++store._environmentBackedCount;
        return;
    }
    ++store._fileBackedCount;
    store._filePermissionChecksComplete =
        store._filePermissionChecksComplete && permissionsVerified;
    if (permissionsVerified && !restricted) ++store._insecureFileCount;
}

PrincipalStoreSnapshot ReloadablePrincipalStore::reload(
    const Poco::Util::AbstractConfiguration& configuration)
{
    auto candidate = std::make_shared<const PrincipalStore>(
        PrincipalStore::fromManagementConfiguration(configuration));
    std::unique_lock lock(_mutex);
    _store = std::move(candidate);
    ++_generation;
    return {_generation, _store->required(), _store->size(), _store->fileBackedCount(),
            _store->environmentBackedCount(), _store->insecureFileCount(),
            _store->filePermissionChecksComplete()};
}

PrincipalStoreSnapshot ReloadablePrincipalStore::snapshot() const noexcept
{
    std::shared_lock lock(_mutex);
    return {_generation, _store->required(), _store->size(), _store->fileBackedCount(),
            _store->environmentBackedCount(), _store->insecureFileCount(),
            _store->filePermissionChecksComplete()};
}

std::optional<AuthenticatedPrincipal> ReloadablePrincipalStore::authenticateBearerToken(
    const std::string& token) const
{
    std::shared_lock lock(_mutex);
    const auto* principal = _store->authenticateBearerToken(token);
    if (!principal) return std::nullopt;
    return copyPrincipal(*principal);
}

std::optional<AuthenticatedPrincipal> ReloadablePrincipalStore::authenticateAuthorizationHeader(
    const std::string& header) const
{
    std::shared_lock lock(_mutex);
    const auto* principal = _store->authenticateAuthorizationHeader(header);
    if (!principal) return std::nullopt;
    return copyPrincipal(*principal);
}

std::optional<AuthenticatedPrincipal> ReloadablePrincipalStore::principalById(
    const std::string& id) const
{
    std::shared_lock lock(_mutex);
    const auto* principal = _store->principalById(id);
    if (!principal) return std::nullopt;
    return copyPrincipal(*principal);
}
}
