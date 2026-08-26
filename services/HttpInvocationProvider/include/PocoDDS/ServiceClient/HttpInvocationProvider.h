#pragma once

#include <PocoDDS/ServiceClient/ServiceInvocationProvider.h>

#include <chrono>
#include <cstddef>
#include <cstdint>
#include <memory>
#include <string>
#include <vector>

namespace PocoDDS::ServiceClient
{
struct HttpAuthorizationRule
{
    std::string service;
    std::string operation;
    std::string host;
    std::uint16_t port{0};
    std::string authorization;
    std::string authorizationFile;
};

struct HttpCredentialSnapshot
{
    std::uint64_t generation{0};
    std::size_t fileBackedRules{0};
    std::uint64_t reloads{0};
    std::uint64_t reloadFailures{0};
    bool healthy{true};
    bool permissionChecksComplete{true};
    std::size_t insecureFiles{0};
    std::string lastError;
};

struct HttpInvocationOptions
{
    std::string providerId;
    std::string protocol;
    std::vector<std::string> allowedHosts;
    std::vector<std::uint16_t> allowedPorts;
    bool allowLoopback{false};
    bool allowPrivateNetworks{false};
    bool allowLinkLocal{false};
    std::size_t maximumRequestBytes{1024 * 1024};
    std::size_t maximumResponseBytes{1024 * 1024};
    std::chrono::milliseconds maximumTimeout{5000};
    std::string caCertificate;
    // Legacy single-target compatibility. Prefer authorizationRules.
    std::string authorization;
    std::vector<HttpAuthorizationRule> authorizationRules;
    bool requireAuthorizationMatch{false};
    bool requireRestrictedCredentialFiles{true};
    std::chrono::milliseconds credentialReloadInterval{1000};
};

class HttpInvocationProvider final : public ServiceInvocationProvider
{
public:
    explicit HttpInvocationProvider(HttpInvocationOptions options);

    std::string providerId() const override;
    std::string protocol() const override;
    AttemptResult invoke(const ProviderInvocationRequest& request) override;
    [[nodiscard]] HttpCredentialSnapshot credentialSnapshot() const;

protected:
    ~HttpInvocationProvider() override;

private:
    class Impl;
    std::unique_ptr<Impl> _impl;
};
} // namespace PocoDDS::ServiceClient
