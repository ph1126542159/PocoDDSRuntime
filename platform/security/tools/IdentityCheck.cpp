#include "PocoDDS/Security/PrincipalStore.h"

#include "Poco/AutoPtr.h"
#include "Poco/Exception.h"
#include "Poco/JSON/Array.h"
#include "Poco/JSON/Object.h"
#include "Poco/Util/LayeredConfiguration.h"
#include "Poco/Util/PropertyFileConfiguration.h"

#include <filesystem>
#include <iostream>
#include <string>

namespace
{
void emitError(const std::string& message)
{
    Poco::JSON::Object result;
    result.set("schemaVersion", 1);
    result.set("passed", false);
    result.set("error", message);
    result.stringify(std::cout, 2);
    std::cout << '\n';
}
}

int main(int argc, char** argv)
{
    bool strict = false;
    int firstConfiguration = 1;
    if (argc > 1 && std::string(argv[1]) == "--strict")
    {
        strict = true;
        firstConfiguration = 2;
    }
    if (argc <= firstConfiguration)
    {
        emitError("usage: pdr-identity-check [--strict] CONFIG [OVERRIDE ...]");
        return 2;
    }

    try
    {
        Poco::AutoPtr<Poco::Util::LayeredConfiguration> configuration =
            new Poco::Util::LayeredConfiguration;
        for (int index = firstConfiguration; index < argc; ++index)
        {
            const auto path = std::filesystem::absolute(argv[index]);
            if (!std::filesystem::is_regular_file(path))
                throw Poco::NotFoundException("configuration file", path.string());
            Poco::AutoPtr<Poco::Util::PropertyFileConfiguration> file =
                new Poco::Util::PropertyFileConfiguration(path.string());
            configuration->add(file, firstConfiguration - index);
        }

        const auto store =
            PocoDDS::Security::PrincipalStore::fromManagementConfiguration(*configuration);
        const bool passed = !strict ||
            (store.required() && store.size() > 0 && store.fileBackedCount() > 0 &&
             store.filePermissionChecksComplete() && store.insecureFileCount() == 0);
        Poco::JSON::Object result;
        result.set("schemaVersion", 1);
        result.set("passed", passed);
        result.set("strict", strict);
        result.set("authenticationRequired", store.required());
        result.set("principalCount", static_cast<Poco::UInt64>(store.size()));
        result.set("fileBackedPrincipalCount",
                   static_cast<Poco::UInt64>(store.fileBackedCount()));
        result.set("environmentBackedPrincipalCount",
                   static_cast<Poco::UInt64>(store.environmentBackedCount()));
        result.set("insecureFileCount", static_cast<Poco::UInt64>(store.insecureFileCount()));
        result.set("filePermissionChecksComplete", store.filePermissionChecksComplete());
        Poco::JSON::Array::Ptr denialReasons = new Poco::JSON::Array;
        if (strict)
        {
            if (!store.required()) denialReasons->add("AUTHENTICATION_NOT_REQUIRED");
            if (store.size() == 0) denialReasons->add("NO_MANAGEMENT_PRINCIPALS");
            if (store.fileBackedCount() == 0) denialReasons->add("NO_FILE_BACKED_PRINCIPALS");
            if (!store.filePermissionChecksComplete())
                denialReasons->add("FILE_PERMISSION_CHECK_INCOMPLETE");
            if (store.insecureFileCount() > 0) denialReasons->add("TOKEN_FILE_ACCESS_TOO_BROAD");
        }
        result.set("denialReasons", denialReasons);
        result.stringify(std::cout, 2);
        std::cout << '\n';
        return passed ? 0 : 1;
    }
    catch (const Poco::Exception& exception)
    {
        emitError(exception.displayText());
    }
    catch (const std::exception& exception)
    {
        emitError(exception.what());
    }
    return 2;
}
