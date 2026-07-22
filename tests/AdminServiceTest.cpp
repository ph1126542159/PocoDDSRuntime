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
