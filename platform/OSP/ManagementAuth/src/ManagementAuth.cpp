#include "PocoDDS/ManagementAuth/IdentityService.h"

#include "Poco/AutoPtr.h"
#include "Poco/ClassLibrary.h"
#include "Poco/OSP/Auth/AuthService.h"
#include "Poco/OSP/BundleActivator.h"
#include "Poco/OSP/BundleContext.h"
#include "Poco/OSP/PreferencesService.h"
#include "Poco/OSP/Properties.h"
#include "Poco/OSP/ServiceFinder.h"
#include "Poco/OSP/ServiceRef.h"
#include "Poco/OSP/Web/TokenValidator.h"

#include <string>

namespace PocoDDS::ManagementAuth
{
constexpr const char* AUTH_SERVICE_NAME = "pdr.auth.management";
constexpr const char* TOKEN_VALIDATOR_NAME = "pdr.auth.management.tokens";

class IdentityServiceImpl final : public IdentityService
{
public:
    Security::PrincipalStoreSnapshot snapshot() const override { return _store.snapshot(); }
    Security::PrincipalStoreSnapshot reload(
        const Poco::Util::AbstractConfiguration& configuration) override
    {
        return _store.reload(configuration);
    }
    std::optional<Security::AuthenticatedPrincipal> authenticateBearerToken(
        const std::string& token) const override
    {
        return _store.authenticateBearerToken(token);
    }
    std::optional<Security::AuthenticatedPrincipal> authenticateAuthorizationHeader(
        const std::string& authorizationHeader) const override
    {
        return _store.authenticateAuthorizationHeader(authorizationHeader);
    }
    std::optional<Security::AuthenticatedPrincipal> principalById(
        const std::string& id) const override
    {
        return _store.principalById(id);
    }

private:
    Security::ReloadablePrincipalStore _store;
};

class ManagementAuthService final : public Poco::OSP::Auth::AuthService
{
public:
    explicit ManagementAuthService(IdentityService::Ptr identity):
        _identity(std::move(identity))
    {
    }

    bool authenticate(const std::string& userName,
                      const std::string& credentials) const override
    {
        const auto principal = _identity->authenticateBearerToken(credentials);
        return principal && principal->id == userName;
    }

    bool authorize(const std::string& userName,
                   const std::string& permission) const override
    {
        const auto principal = _identity->principalById(userName);
        return principal && principal->authorized(permission);
    }

    bool userExists(const std::string& userName) const override
    {
        return _identity->principalById(userName).has_value();
    }

private:
    IdentityService::Ptr _identity;
};

class ManagementTokenValidator final : public Poco::OSP::Web::TokenValidator
{
public:
    explicit ManagementTokenValidator(IdentityService::Ptr identity):
        _identity(std::move(identity))
    {
    }

    bool validateToken(const std::string& token, std::string& username) override
    {
        const auto principal = _identity->authenticateBearerToken(token);
        if (!principal) return false;
        username = principal->id;
        return true;
    }

private:
    IdentityService::Ptr _identity;
};

class BundleActivator final : public Poco::OSP::BundleActivator
{
public:
    void start(Poco::OSP::BundleContext::Ptr context) override
    {
        auto preferences = Poco::OSP::ServiceFinder::find<Poco::OSP::PreferencesService>(context);
        IdentityService::Ptr identity = new IdentityServiceImpl;
        identity->reload(*preferences->configuration());
        Poco::OSP::Properties properties;
        _identityService = context->registry().registerService(
            IdentityService::SERVICE_NAME, identity, properties);
        try
        {
            _authService = context->registry().registerService(
                AUTH_SERVICE_NAME, new ManagementAuthService(identity), properties);
            try
            {
                _tokenValidator = context->registry().registerService(
                    TOKEN_VALIDATOR_NAME, new ManagementTokenValidator(identity), properties);
            }
            catch (...)
            {
                context->registry().unregisterService(_authService);
                _authService.reset();
                throw;
            }
        }
        catch (...)
        {
            context->registry().unregisterService(_identityService);
            _identityService.reset();
            throw;
        }
    }

    void stop(Poco::OSP::BundleContext::Ptr context) override
    {
        if (_tokenValidator)
        {
            context->registry().unregisterService(_tokenValidator);
            _tokenValidator.reset();
        }
        if (_authService)
        {
            context->registry().unregisterService(_authService);
            _authService.reset();
        }
        if (_identityService)
        {
            context->registry().unregisterService(_identityService);
            _identityService.reset();
        }
    }

private:
    Poco::OSP::ServiceRef::Ptr _authService;
    Poco::OSP::ServiceRef::Ptr _tokenValidator;
    Poco::OSP::ServiceRef::Ptr _identityService;
};
}

POCO_BEGIN_MANIFEST(Poco::OSP::BundleActivator)
    POCO_EXPORT_CLASS(PocoDDS::ManagementAuth::BundleActivator)
POCO_END_MANIFEST
