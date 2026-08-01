#include "PocoDDS/Configuration/ConfigurationValidator.h"

#include "Poco/AutoPtr.h"
#include "Poco/Exception.h"
#include "Poco/Util/LayeredConfiguration.h"
#include "Poco/Util/PropertyFileConfiguration.h"

#include <filesystem>
#include <iostream>
#include <string>

int main(int argc, char** argv)
{
    if (argc < 2)
    {
        std::cerr << "usage: pdr-config-check CONFIG [OVERRIDE ...]\n";
        return 2;
    }

    try
    {
        Poco::AutoPtr<Poco::Util::LayeredConfiguration> configuration =
            new Poco::Util::LayeredConfiguration;
        for (int index = 1; index < argc; ++index)
        {
            const std::filesystem::path path = std::filesystem::absolute(argv[index]);
            if (!std::filesystem::is_regular_file(path))
            {
                std::cerr << "CONFIG_VALIDATION_ERROR key=<file> message=file not found: "
                          << path.string() << '\n';
                return 2;
            }
            Poco::AutoPtr<Poco::Util::PropertyFileConfiguration> file =
                new Poco::Util::PropertyFileConfiguration(path.string());
            configuration->add(file, -index);
        }

        const auto issues = PocoDDS::Configuration::ConfigurationValidator().validate(*configuration);
        if (!issues.empty())
        {
            for (const auto& issue : issues)
                std::cerr << "CONFIG_VALIDATION_ERROR key=" << issue.key
                          << " message=" << issue.message << '\n';
            std::cerr << "CONFIG_VALIDATION_FAIL files=" << (argc - 1)
                      << " issues=" << issues.size() << '\n';
            return 1;
        }

        std::cout << "CONFIG_VALIDATION_OK files=" << (argc - 1) << '\n';
        return 0;
    }
    catch (const Poco::Exception& exception)
    {
        std::cerr << "CONFIG_VALIDATION_ERROR key=<parse> message="
                  << exception.displayText() << '\n';
    }
    catch (const std::exception& exception)
    {
        std::cerr << "CONFIG_VALIDATION_ERROR key=<parse> message=" << exception.what() << '\n';
    }
    return 2;
}
