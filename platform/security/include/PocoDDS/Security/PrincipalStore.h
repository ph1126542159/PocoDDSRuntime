#pragma once

#include "Poco/Util/AbstractConfiguration.h"

#include <cstddef>
#include <cstdint>
#include <memory>
#include <optional>
#include <shared_mutex>
#include <string>
#include <unordered_set>
#include <vector>

namespace PocoDDS::Security
{
using PermissionSet = std::unordered_set<std::string>;

const PermissionSet& managementPermissions();

class Principal
{
public:
    const std::string& id() const noexcept { return _id; }
    const PermissionSet& permissions() const noexcept { return _permissions; }
    bool authorized(const std::string& permission) const noexcept;

private:
    friend class PrincipalStore;
    std::string _id;
    PermissionSet _permissions;
};

class PrincipalStore
{
public:
    static PrincipalStore fromManagementConfiguration(
        const Poco::Util::AbstractConfiguration& configuration);

    bool required() const noexcept { return _required; }
    std::size_t size() const noexcept { return _entries.size(); }
    std::size_t fileBackedCount() const noexcept { return _fileBackedCount; }
    std::size_t environmentBackedCount() const noexcept { return _environmentBackedCount; }
    std::size_t insecureFileCount() const noexcept { return _insecureFileCount; }
    bool filePermissionChecksComplete() const noexcept { return _filePermissionChecksComplete; }
    const Principal* principalById(const std::string& id) const noexcept;
    const Principal* authenticateBearerToken(const std::string& token) const noexcept;
    const Principal* authenticateAuthorizationHeader(const std::string& header) const noexcept;

private:
    struct Entry
    {
        Principal principal;
        std::string token;
    };

    static void appendEntry(PrincipalStore& store, std::string id, std::string token,
                            PermissionSet permissions);
    static void recordSource(PrincipalStore& store, bool fileBacked,
                             bool permissionsVerified, bool restricted);
    bool _required{false};
    std::size_t _fileBackedCount{0};
    std::size_t _environmentBackedCount{0};
    std::size_t _insecureFileCount{0};
    bool _filePermissionChecksComplete{true};
    std::vector<Entry> _entries;
};

struct AuthenticatedPrincipal
{
    std::string id;
    PermissionSet permissions;

    bool authorized(const std::string& permission) const noexcept
    {
        return permissions.count(permission) != 0;
    }
};

struct PrincipalStoreSnapshot
{
    std::uint64_t generation{0};
    bool required{false};
    std::size_t principalCount{0};
    std::size_t fileBackedPrincipalCount{0};
    std::size_t environmentBackedPrincipalCount{0};
    std::size_t insecureFileCount{0};
    bool filePermissionChecksComplete{true};
};

class ReloadablePrincipalStore
{
public:
    PrincipalStoreSnapshot reload(
        const Poco::Util::AbstractConfiguration& configuration);
    PrincipalStoreSnapshot snapshot() const noexcept;
    std::optional<AuthenticatedPrincipal> authenticateBearerToken(
        const std::string& token) const;
    std::optional<AuthenticatedPrincipal> authenticateAuthorizationHeader(
        const std::string& header) const;
    std::optional<AuthenticatedPrincipal> principalById(const std::string& id) const;

private:
    mutable std::shared_mutex _mutex;
    std::shared_ptr<const PrincipalStore> _store{std::make_shared<const PrincipalStore>()};
    std::uint64_t _generation{0};
};
}
