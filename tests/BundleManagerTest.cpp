#include "PocoDDS/Core/BundleManager.h"
#include <gtest/gtest.h>

#include <chrono>
#include <filesystem>

namespace
{
class TestBundle final : public PocoDDS::Core::Bundle
{
  public:
    std::string name() const override { return "test.bundle"; }
    void start(PocoDDS::Core::BundleContext&) override { started = true; }
    void stop(PocoDDS::Core::BundleContext&) override { started = false; }
    bool started{false};
};
} // namespace

TEST(BundleManagerTest, RunsCompleteLifecycle)
{
    PocoDDS::Core::ComponentRegistry registry;
    PocoDDS::Core::BundleManager manager(registry);
    manager.install(std::make_unique<TestBundle>());
    EXPECT_NO_THROW(manager.start("test.bundle"));
    EXPECT_NO_THROW(manager.stop("test.bundle"));
    EXPECT_NO_THROW(manager.uninstall("test.bundle"));
}

TEST(BundleManagerTest, LoadsStartsReplacesAndUnloadsSharedLibrary)
{
    const auto unique = std::chrono::steady_clock::now().time_since_epoch().count();
    const auto source = std::filesystem::path(PDR_TEST_BUNDLE_PATH);
    const auto copy = std::filesystem::temp_directory_path() /
                      ("pdr-test-bundle-" + std::to_string(unique) + source.extension().string());
    std::filesystem::copy_file(source, copy);

    PocoDDS::Core::ComponentRegistry registry;
    PocoDDS::Core::BundleManager manager(registry);
    EXPECT_EQ(manager.installLibrary(copy), "test.dynamic.bundle");
    EXPECT_NO_THROW(manager.start("test.dynamic.bundle"));
    EXPECT_NO_THROW(manager.replaceLibrary("test.dynamic.bundle", copy));
    EXPECT_NO_THROW(manager.uninstall("test.dynamic.bundle"));
    EXPECT_TRUE(std::filesystem::remove(copy));
}
