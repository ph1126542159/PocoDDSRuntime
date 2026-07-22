#include "PocoDDS/Core/BundleManager.h"
#include <gtest/gtest.h>

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
