#include "PocoDDS/Security/PrincipalStore.h"

#include "Poco/AutoPtr.h"
#include "Poco/Environment.h"
#include "Poco/Exception.h"
#include "Poco/TemporaryFile.h"
#include "Poco/Util/MapConfiguration.h"

#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>

namespace
{
void require(bool condition, const char* message)
{
    if (!condition) throw std::runtime_error(message);
}
}

int main()
{
    try
    {
        Poco::Environment::set("PDR_IDENTITY_TEST_LEGACY", "legacy-secret");
        Poco::Environment::set("PDR_IDENTITY_TEST_OPERATOR", "operator-secret");
        Poco::AutoPtr<Poco::Util::MapConfiguration> configuration =
            new Poco::Util::MapConfiguration;
        configuration->setBool("pdr.management.authentication.required", true);
        configuration->setString("pdr.management.authentication.tokenEnvironment",
                                 "PDR_IDENTITY_TEST_LEGACY");
        configuration->setInt("pdr.management.authentication.principals.count", 1);
        configuration->setString("pdr.management.authentication.principals.0.id", "operator");
        configuration->setString(
            "pdr.management.authentication.principals.0.tokenEnvironment",
            "PDR_IDENTITY_TEST_OPERATOR");
        configuration->setString(
            "pdr.management.authentication.principals.0.permissions",
            " protocol.manage, task.read ");

        auto store = PocoDDS::Security::PrincipalStore::fromManagementConfiguration(
            *configuration);
        require(store.required(), "required flag was not preserved");
        require(store.size() == 2, "principal count mismatch");
        const auto* legacy = store.authenticateAuthorizationHeader("Bearer legacy-secret");
        require(legacy && legacy->id() == "legacy-admin", "legacy principal did not authenticate");
        require(legacy->permissions() == PocoDDS::Security::managementPermissions(),
                "legacy principal did not receive all management permissions");
        const auto* operatorPrincipal = store.authenticateBearerToken("operator-secret");
        require(operatorPrincipal && operatorPrincipal->id() == "operator",
                "indexed principal did not authenticate");
        require(store.principalById("operator") == operatorPrincipal,
                "principal lookup did not return the authenticated identity");
        require(store.principalById("missing") == nullptr,
                "missing principal lookup succeeded");
        require(operatorPrincipal->authorized("protocol.manage"),
                "configured permission missing");
        require(!operatorPrincipal->authorized("bundle.manage"),
                "unconfigured permission was granted");
        require(store.authenticateBearerToken("wrong-secret") == nullptr,
                "wrong token authenticated");
        require(store.authenticateAuthorizationHeader("Basic operator-secret") == nullptr,
                "non-Bearer scheme authenticated");
        require(store.authenticateAuthorizationHeader("bearer operator-secret") == nullptr,
                "case-changed Bearer scheme authenticated");

        Poco::Environment::set("PDR_IDENTITY_TEST_DUPLICATE", "legacy-secret");
        configuration->setInt("pdr.management.authentication.principals.count", 2);
        configuration->setString("pdr.management.authentication.principals.1.id", "duplicate");
        configuration->setString(
            "pdr.management.authentication.principals.1.tokenEnvironment",
            "PDR_IDENTITY_TEST_DUPLICATE");
        configuration->setString(
            "pdr.management.authentication.principals.1.permissions", "task.read");
        bool duplicateRejected = false;
        try
        {
            PocoDDS::Security::PrincipalStore::fromManagementConfiguration(*configuration);
        }
        catch (const Poco::InvalidArgumentException& error)
        {
            duplicateRejected = true;
            require(error.displayText().find("legacy-secret") == std::string::npos,
                    "duplicate-token error leaked the token");
        }
        require(duplicateRejected, "duplicate bearer token was not rejected");

        configuration->setString(
            "pdr.management.authentication.principals.1.tokenEnvironment",
            "PDR_IDENTITY_TEST_MISSING");
        bool missingRejected = false;
        try
        {
            PocoDDS::Security::PrincipalStore::fromManagementConfiguration(*configuration);
        }
        catch (const Poco::NotFoundException&)
        {
            missingRejected = true;
        }
        require(missingRejected, "missing token environment was not rejected");

        Poco::TemporaryFile tokenFile;
        auto writeToken = [&](const std::string& token) {
            std::ofstream stream(tokenFile.path(), std::ios::binary | std::ios::trunc);
            stream << token << '\n';
            stream.close();
            require(stream.good(), "failed to write test token file");
        };
        Poco::AutoPtr<Poco::Util::MapConfiguration> fileConfiguration =
            new Poco::Util::MapConfiguration;
        fileConfiguration->setBool("pdr.management.authentication.required", true);
        fileConfiguration->setInt("pdr.management.authentication.principals.count", 1);
        fileConfiguration->setString(
            "pdr.management.authentication.principals.0.id", "file-operator");
        fileConfiguration->setString(
            "pdr.management.authentication.principals.0.tokenFile", tokenFile.path());
        fileConfiguration->setString(
            "pdr.management.authentication.principals.0.permissions", "identity.manage");
        writeToken("file-token-v1");
        PocoDDS::Security::ReloadablePrincipalStore reloadable;
        const auto first = reloadable.reload(*fileConfiguration);
        require(first.generation == 1 && first.required && first.principalCount == 1,
                "initial file-backed identity snapshot mismatch");
        require(first.fileBackedPrincipalCount == 1 &&
                    first.environmentBackedPrincipalCount == 0,
                "file-backed identity source diagnostics mismatch");
        require(first.filePermissionChecksComplete,
                "token file permission inspection did not complete");
        require(reloadable.authenticateBearerToken("file-token-v1").has_value(),
                "initial file token did not authenticate");
        writeToken("file-token-v2");
        const auto second = reloadable.reload(*fileConfiguration);
        require(second.generation == 2, "successful reload did not advance generation");
        require(!reloadable.authenticateBearerToken("file-token-v1").has_value(),
                "old file token remained valid after reload");
        const auto rotated = reloadable.authenticateBearerToken("file-token-v2");
        require(rotated && rotated->id == "file-operator" &&
                    rotated->authorized("identity.manage"),
                "rotated file token did not preserve identity and permissions");
        writeToken("");
        bool emptyFileRejected = false;
        try
        {
            reloadable.reload(*fileConfiguration);
        }
        catch (const Poco::InvalidArgumentException&)
        {
            emptyFileRejected = true;
        }
        require(emptyFileRejected, "empty token file reload was accepted");
        require(reloadable.snapshot().generation == 2,
                "failed reload advanced identity generation");
        require(reloadable.authenticateBearerToken("file-token-v2").has_value(),
                "failed reload replaced the last valid identity snapshot");
        return 0;
    }
    catch (const std::exception& error)
    {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
