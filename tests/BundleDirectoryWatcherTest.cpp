#include "PocoDDS/Core/BundleDirectoryWatcher.h"

#include <gtest/gtest.h>

#include <chrono>
#include <filesystem>
#include <fstream>

namespace
{
class TemporaryDirectory
{
  public:
    TemporaryDirectory()
    {
        const auto nonce = std::chrono::steady_clock::now().time_since_epoch().count();
        path =
            std::filesystem::temp_directory_path() / ("pdr-bundle-watch-" + std::to_string(nonce));
        std::filesystem::create_directories(path);
    }

    ~TemporaryDirectory()
    {
        std::error_code ignored;
        std::filesystem::remove_all(path, ignored);
    }

    std::filesystem::path path;
};
} // namespace

TEST(BundleDirectoryWatcherTest, InstallsReplacesAndRemovesBundleUsingCompleteLifecycle)
{
    TemporaryDirectory temporary;
    const auto source = std::filesystem::path(PDR_TEST_BUNDLE_PATH);
    const auto deployed = temporary.path / ("watched" + source.extension().string());
    std::filesystem::copy_file(source, deployed);

    PocoDDS::Core::ComponentRegistry registry;
    PocoDDS::Core::BundleManager manager(registry);
    PocoDDS::Core::BundleDirectoryWatcher watcher(manager, temporary.path);

    auto installed = watcher.scan();
    ASSERT_EQ(installed.size(), 1U);
    EXPECT_EQ(installed[0].kind, PocoDDS::Core::BundleFileEventKind::Installed);
    EXPECT_EQ(installed[0].bundleName, "test.dynamic.bundle");
    ASSERT_TRUE(registry.find("test.dynamic.bundle"));
    EXPECT_EQ(registry.find("test.dynamic.bundle")->state, PocoDDS::Core::ComponentState::Running);

    {
        std::ofstream invalid(deployed, std::ios::binary | std::ios::trunc);
        invalid << "not a shared library";
        ASSERT_TRUE(invalid.good());
    }
    auto failed = watcher.scan();
    ASSERT_EQ(failed.size(), 1U);
    EXPECT_EQ(failed[0].kind, PocoDDS::Core::BundleFileEventKind::Failed);
    EXPECT_EQ(registry.find("test.dynamic.bundle")->state, PocoDDS::Core::ComponentState::Running);

    std::filesystem::copy_file(source, deployed, std::filesystem::copy_options::overwrite_existing);
    std::filesystem::last_write_time(deployed, std::filesystem::file_time_type::clock::now() +
                                                   std::chrono::seconds(2));
    auto replaced = watcher.scan();
    ASSERT_EQ(replaced.size(), 1U);
    EXPECT_EQ(replaced[0].kind, PocoDDS::Core::BundleFileEventKind::Replaced);

    manager.uninstall("test.dynamic.bundle");
    watcher.suppress("test.dynamic.bundle");
    EXPECT_TRUE(watcher.scan().empty());
    EXPECT_FALSE(registry.find("test.dynamic.bundle"));
    std::filesystem::last_write_time(deployed, std::filesystem::file_time_type::clock::now() +
                                                   std::chrono::seconds(4));
    auto reinstalled = watcher.scan();
    ASSERT_EQ(reinstalled.size(), 1U);
    EXPECT_EQ(reinstalled[0].kind, PocoDDS::Core::BundleFileEventKind::Installed);

    EXPECT_TRUE(std::filesystem::remove(deployed));
    auto removed = watcher.scan();
    ASSERT_EQ(removed.size(), 1U);
    EXPECT_EQ(removed[0].kind, PocoDDS::Core::BundleFileEventKind::Removed);
    EXPECT_FALSE(registry.find("test.dynamic.bundle"));
    EXPECT_TRUE(std::filesystem::is_empty(temporary.path));
}
