#pragma once

#include "PocoDDS/ServiceClient/Client.h"

#include <Poco/AutoPtr.h>
#include <Poco/OSP/Service.h>

#include <cstdint>
#include <functional>
#include <map>
#include <memory>
#include <string>
#include <typeinfo>
#include <vector>

namespace PocoDDS::ServiceClient
{
struct InvocationInput
{
    std::vector<std::uint8_t> payload;
    std::map<std::string, std::string> metadata;
};

struct ProviderInvocationRequest
{
    std::string invocationId;
    /// Runtime-owned wall-clock deadline shared by every attempt of one
    /// invocation. Providers must still use attempt.remaining as the local
    /// timeout authority because wall clocks can move or differ across hosts.
    std::int64_t deadlineUnixMicroseconds{0};
    AttemptContext attempt;
    std::shared_ptr<const InvocationInput> input;
    std::function<bool()> cancellationRequested;
};

class ServiceInvocationProvider : public Poco::OSP::Service
{
public:
    using Ptr = Poco::AutoPtr<ServiceInvocationProvider>;
    static constexpr const char* PROPERTY_KIND =
        "pdr.serviceInvocation.provider.kind";
    static constexpr const char* PROPERTY_ID =
        "pdr.serviceInvocation.provider.id";
    static constexpr const char* PROPERTY_PROTOCOL =
        "pdr.serviceInvocation.provider.protocol";
    static constexpr const char* KIND = "runtime";

    virtual std::string providerId() const = 0;
    virtual std::string protocol() const = 0;
    virtual AttemptResult invoke(const ProviderInvocationRequest& request) = 0;

    const std::type_info& type() const override
    {
        return typeid(ServiceInvocationProvider);
    }

    bool isA(const std::type_info& other) const override
    {
        return std::string(other.name()) ==
                   typeid(ServiceInvocationProvider).name() ||
               Poco::OSP::Service::isA(other);
    }

protected:
    ~ServiceInvocationProvider() override = default;
};
} // namespace PocoDDS::ServiceClient
