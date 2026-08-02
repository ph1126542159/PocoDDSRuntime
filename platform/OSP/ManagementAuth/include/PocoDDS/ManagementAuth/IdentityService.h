#pragma once

#include "PocoDDS/Security/PrincipalStore.h"

#include "Poco/AutoPtr.h"
#include "Poco/OSP/Service.h"

namespace Poco::Util
{
class AbstractConfiguration;
}

namespace PocoDDS::ManagementAuth
{
class IdentityService : public Poco::OSP::Service
{
public:
    using Ptr = Poco::AutoPtr<IdentityService>;

    static constexpr const char* SERVICE_NAME = "pdr.identity.management";

    virtual Security::PrincipalStoreSnapshot snapshot() const = 0;
    virtual Security::PrincipalStoreSnapshot reload(
        const Poco::Util::AbstractConfiguration& configuration) = 0;
    virtual std::optional<Security::AuthenticatedPrincipal> authenticateBearerToken(
        const std::string& token) const = 0;
    virtual std::optional<Security::AuthenticatedPrincipal> authenticateAuthorizationHeader(
        const std::string& authorizationHeader) const = 0;
    virtual std::optional<Security::AuthenticatedPrincipal> principalById(
        const std::string& id) const = 0;

    const std::type_info& type() const override { return typeid(IdentityService); }
    bool isA(const std::type_info& other) const override
    {
        return std::string(other.name()) == typeid(IdentityService).name() ||
               Poco::OSP::Service::isA(other);
    }

protected:
    ~IdentityService() override = default;
};
}
