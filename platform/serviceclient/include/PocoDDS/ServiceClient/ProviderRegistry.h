#pragma once

#include "PocoDDS/ServiceClient/Export.h"
#include "PocoDDS/ServiceClient/ServiceInvocationProvider.h"

#include <cstddef>
#include <cstdint>
#include <memory>
#include <string>
#include <vector>

namespace PocoDDS::ServiceClient
{
enum class ProviderAttachStatus
{
    attached,
    invalid,
    duplicateProvider,
    protocolConflict,
    capacityExceeded,
    closing
};

enum class ProviderDispatchStatus
{
    invoked,
    invalid,
    noProvider,
    providerFailure,
    closing
};

PDR_SERVICE_CLIENT_OSP_API const char* toString(
    ProviderAttachStatus value) noexcept;
PDR_SERVICE_CLIENT_OSP_API const char* toString(
    ProviderDispatchStatus value) noexcept;

struct ProviderAttachResult
{
    ProviderAttachStatus status{ProviderAttachStatus::invalid};
    std::string providerId;
    std::string protocol;
    std::string detail;

    explicit operator bool() const noexcept
    {
        return status == ProviderAttachStatus::attached;
    }
};

struct ProviderDispatchResult
{
    ProviderDispatchStatus status{ProviderDispatchStatus::invalid};
    AttemptResult result;
    std::string providerId;
    std::string detail;

    explicit operator bool() const noexcept
    {
        return status == ProviderDispatchStatus::invoked;
    }
};

struct ProviderSnapshot
{
    std::string providerId;
    std::string protocol;
    bool accepting{false};
    std::size_t active{0};
    std::uint64_t dispatched{0};
    std::uint64_t failed{0};
};

struct ProviderRegistrySnapshot
{
    bool closing{false};
    std::size_t maximumProviders{0};
    std::uint64_t generation{0};
    std::uint64_t noProvider{0};
    std::vector<ProviderSnapshot> providers;
};

class PDR_SERVICE_CLIENT_OSP_API ProviderRegistry
{
public:
    explicit ProviderRegistry(std::size_t maximumProviders = 256);
    ~ProviderRegistry();

    ProviderRegistry(const ProviderRegistry&) = delete;
    ProviderRegistry& operator=(const ProviderRegistry&) = delete;

    ProviderAttachResult attach(ServiceInvocationProvider::Ptr provider);
    bool detach(const std::string& providerId);
    ProviderDispatchResult dispatch(const ProviderInvocationRequest& request);
    [[nodiscard]] ProviderRegistrySnapshot snapshot() const;
    void closeAndWait();

private:
    class Impl;
    std::unique_ptr<Impl> _impl;
};
} // namespace PocoDDS::ServiceClient
