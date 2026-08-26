#include <Poco/AutoPtr.h>
#include <Poco/File.h>
#include <Poco/OSP/PreferencesService.h>
#include <Poco/Path.h>
#include <Poco/TemporaryFile.h>
#include <Poco/Util/MapConfiguration.h>

#include <atomic>
#include <future>
#include <iostream>
#include <map>
#include <string>
#include <vector>

int main()
{
    Poco::Path directory(Poco::TemporaryFile::tempName());
    Poco::File(directory).createDirectories();
    Poco::AutoPtr<Poco::Util::MapConfiguration> initial =
        new Poco::Util::MapConfiguration;
    initial->setString("pair.left", "old");
    initial->setString("pair.right", "old");
    initial->setString("obsolete", "true");
    Poco::OSP::PreferencesService::Ptr preferences =
        new Poco::OSP::PreferencesService(directory, initial);
    auto cached = preferences->configuration();

    preferences->replaceConfiguration(
        {{"pair.left", "new"}, {"pair.right", "new"}});
    if (cached.get() != preferences->configuration().get() ||
        cached->getString("pair.left") != "new" || cached->hasProperty("obsolete")) return 1;

    std::atomic<bool> running{true};
    auto writer = std::async(std::launch::async, [&] {
        for (unsigned int index = 0; index < 1000; ++index)
        {
            const std::string value = index % 2 == 0 ? "blue" : "green";
            preferences->replaceConfiguration(
                {{"pair.left", value}, {"pair.right", value}});
        }
        running = false;
    });
    std::vector<std::future<bool>> readers;
    for (unsigned int index = 0; index < 8; ++index)
        readers.push_back(std::async(std::launch::async, [&] {
            while (running)
            {
                const auto snapshot = preferences->configurationSnapshot();
                const auto left = snapshot.find("pair.left");
                const auto right = snapshot.find("pair.right");
                if (left == snapshot.end() || right == snapshot.end() ||
                    left->second != right->second) return false;
            }
            return true;
        }));
    writer.get();
    for (auto& reader : readers)
        if (!reader.get()) return 2;

    preferences = nullptr;
    try { Poco::File(directory).remove(true); } catch (...) {}
    std::cout << "PDR_PREFERENCES_SNAPSHOT_PASS atomic_replace=true cached_view=true "
                 "concurrent_readers=8\n";
    return 0;
}
