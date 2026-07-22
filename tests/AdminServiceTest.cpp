#include "PocoDDS/Admin/AdminService.h"

#include <gtest/gtest.h>

using PocoDDS::Admin::AdminService;

TEST(AdminServiceTest, ExposesTopologyAndAppliesConfigurationImmediately)
{
    PocoDDS::Core::ComponentRegistry registry;
    PocoDDS::Core::Configuration configuration;
    registry.upsert({"worker",
                     "Worker",
                     "localhost",
                     42,
                     PocoDDS::Core::ComponentKind::Process,
                     PocoDDS::Core::ComponentState::Running,
                     {}});
    AdminService admin(registry, configuration, [](const auto&, const auto&)
                       { return PocoDDS::Admin::LifecycleResult{true, {}}; });

    ASSERT_EQ(admin.topology().size(), 1U);
    admin.applyConfiguration({{"render.quality", "high"}});
    EXPECT_EQ(admin.configuration().at("render.quality"), "high");
    EXPECT_EQ(admin.configurationRevision(), 1U);
    auto conflict = admin.applyConfiguration({}, {{"render.quality", "low"}}, 0);
    EXPECT_FALSE(conflict.success);
    EXPECT_EQ(conflict.revision, 1U);
}

TEST(AdminServiceTest, FiltersLogsAndBuildsTraceData)
{
    PocoDDS::Core::ComponentRegistry registry;
    PocoDDS::Core::Configuration configuration;
    AdminService admin(
        registry, configuration,
        [](const auto&, const auto&) { return PocoDDS::Admin::LifecycleResult{true, {}}; }, 2, 2);

    admin.appendLog({{}, "one", "info", "first", "trace-a", "span-a"});
    admin.appendLog({{}, "two", "error", "second", "trace-b", "span-b"});
    admin.appendLog({{}, "one", "info", "third", "trace-a", "span-c"});
    ASSERT_EQ(admin.logs().size(), 2U);
    EXPECT_EQ(admin.logs("one", "trace-a").at(0).message, "third");

    admin.appendTrace({"trace-a", "root", {}, "request", "one", "success", 10, {}, {}, {}});
    admin.appendTrace({"trace-a", "child", "root", "render", "two", "success", 5, {}, {}, {}});
    auto nodes = admin.trace("trace-a");
    ASSERT_EQ(nodes.size(), 2U);
    EXPECT_EQ(nodes[1].parentSpanId, "root");
    EXPECT_EQ(admin.recentTraceIds().at(0), "trace-a");
}

TEST(AdminServiceTest, ValidatesLifecycleCommands)
{
    PocoDDS::Core::ComponentRegistry registry;
    PocoDDS::Core::Configuration configuration;
    std::string received;
    AdminService admin(registry, configuration,
                       [&](const auto& target, const auto& action)
                       {
                           received = target + ":" + action;
                           return PocoDDS::Admin::LifecycleResult{true, "applied"};
                       });

    EXPECT_TRUE(admin.execute("worker", "restart").success);
    EXPECT_EQ(received, "worker:restart");
    EXPECT_FALSE(admin.execute("worker", "destroy").success);
}

TEST(AdminServiceTest, RoutesTargetedConfigurationAndReturnsRemoteRevision)
{
    PocoDDS::Core::ComponentRegistry registry;
    PocoDDS::Core::Configuration configuration;
    AdminService admin(registry, configuration, [](const auto&, const auto&)
                       { return PocoDDS::Admin::LifecycleResult{true, {}}; });
    std::string receivedTarget;
    admin.routeConfiguration(
        [&](const auto& target, const auto& changes, auto revision)
        {
            receivedTarget = target;
            EXPECT_EQ(changes.at("fps"), "60");
            EXPECT_EQ(revision, 4U);
            return PocoDDS::Admin::ConfigurationResult{true, {}, 5};
        });

    auto result = admin.applyConfiguration("render.worker", {{"fps", "60"}}, 4);
    EXPECT_TRUE(result.success);
    EXPECT_EQ(result.revision, 5U);
    EXPECT_EQ(receivedTarget, "render.worker");
}
