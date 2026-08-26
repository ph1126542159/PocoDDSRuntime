#include "Poco/File.h"
#include "Poco/FileStream.h"
#include "Poco/OSP/BundleContextFactory.h"
#include "Poco/OSP/BundleFactory.h"
#include "Poco/OSP/BundleLoader.h"
#include "Poco/OSP/BundleRepository.h"
#include "Poco/OSP/CodeCache.h"
#include "Poco/OSP/LanguageTag.h"
#include "Poco/OSP/OSPException.h"
#include "Poco/OSP/ServiceRegistry.h"
#include "Poco/OSP/SystemEvents.h"
#include "Poco/Path.h"

#include <iostream>
#include <vector>

namespace
{
struct LoaderFixture
{
    explicit LoaderFixture(const std::string& cachePath)
        : codeCache(cachePath), language("en", "US"), bundleFactory(new Poco::OSP::BundleFactory(language)),
          contextFactory(new Poco::OSP::BundleContextFactory(registry, systemEvents)),
          loader(codeCache, bundleFactory, contextFactory)
    {
    }

    Poco::OSP::CodeCache codeCache;
    Poco::OSP::ServiceRegistry registry;
    Poco::OSP::SystemEvents systemEvents;
    Poco::OSP::LanguageTag language;
    Poco::OSP::BundleFactory::Ptr bundleFactory;
    Poco::OSP::BundleContextFactory::Ptr contextFactory;
    Poco::OSP::BundleLoader loader;
};
} // namespace

int main(int argc, char** argv)
{
    if (argc != 5)
    {
        std::cerr << "usage: BundleRepositoryPreflightSmoke <source-bundle> <cache> <valid-repository> <invalid-repository>\n";
        return 2;
    }

    try
    {
        Poco::File(argv[2]).remove(true);
    }
    catch (...)
    {
    }
    try
    {
        Poco::File(argv[3]).remove(true);
    }
    catch (...)
    {
    }
    try
    {
        Poco::File(argv[4]).remove(true);
    }
    catch (...)
    {
    }

    try
    {
        LoaderFixture fixture(argv[2]);
        Poco::File(argv[3]).createDirectories();
        Poco::Path validBundle(argv[3]);
        validBundle.makeDirectory();
        validBundle.setFileName("sample.bndl");
        Poco::File(argv[1]).copyTo(validBundle.toString());
        Poco::OSP::BundleRepository repository(argv[3], fixture.loader);
        const Poco::OSP::BundleRepository::Bundles candidates = repository.validateBundles();
        if (candidates.empty())
            throw Poco::RuntimeException("strict repository preflight selected no bundles");
        std::vector<Poco::OSP::Bundle::Ptr> loaded;
        fixture.loader.listBundles(loaded);
        if (!loaded.empty())
            throw Poco::RuntimeException("repository preflight mutated the live BundleLoader");

        Poco::File(argv[4]).createDirectories();
        Poco::Path invalid(argv[4]);
        invalid.makeDirectory();
        invalid.setFileName("broken.bndl");
        Poco::FileOutputStream stream(invalid.toString());
        stream << "not a bundle archive";
        stream.close();

        Poco::OSP::BundleRepository invalidRepository(argv[4], fixture.loader);
        bool rejected = false;
        try
        {
            invalidRepository.validateBundles();
        }
        catch (const Poco::OSP::BundleLoadException&)
        {
            rejected = true;
        }
        if (!rejected)
            throw Poco::RuntimeException("malformed bundle candidate was not rejected");
        fixture.loader.listBundles(loaded);
        if (!loaded.empty())
            throw Poco::RuntimeException("failed repository preflight mutated the live BundleLoader");
    }
    catch (const Poco::Exception& exception)
    {
        std::cerr << exception.displayText() << '\n';
        return 1;
    }

    try
    {
        Poco::File(argv[2]).remove(true);
        Poco::File(argv[3]).remove(true);
        Poco::File(argv[4]).remove(true);
    }
    catch (...)
    {
    }
    return 0;
}
