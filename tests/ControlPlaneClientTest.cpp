#include "PocoDDS/Control/ControlPlaneClient.h"
#include "PocoDDS/Admin/AdminService.h"
#include "PocoDDS/Control/ControlPlaneAgent.h"
#include "PocoDDS/Transport/InMemoryTransport.h"

#include <gtest/gtest.h>

using namespace std::chrono_literals;

TEST(ControlPlaneClientTest, RoutesConfigurationAndLifecycleWithCorrelatedResults)
{
    PocoDDS::Transport::InMemoryTransport transport;
    PocoDDS::Core::Configuration configuration;
    PocoDDS::Control::LifecycleAction received{};
    PocoDDS::Control::ControlPlaneAgent agent(transport, configuration, "worker.one",
                                              [&](const auto& command)
                                              { received = command.action; });
    PocoDDS::Control::ControlPlaneClient client(transport, "admin");

    auto configured =
        client.applyConfiguration("worker.one", {{"quality", "ultra"}}, 0, 100ms,
                                  "00-11111111111111111111111111111111-2222222222222222-01");
    EXPECT_TRUE(configured.success);
    EXPECT_EQ(configured.configurationRevision, 1U);
    EXPECT_EQ(configuration.get("quality"), "ultra");

    auto restarted = client.executeLifecycle(
        "worker.one", PocoDDS::Control::LifecycleAction::Restart, 250ms, 100ms);
    EXPECT_TRUE(restarted.success);
    EXPECT_EQ(received, PocoDDS::Control::LifecycleAction::Restart);
    EXPECT_NE(configured.correlationId, restarted.correlationId);
}

TEST(ControlPlaneClientTest, ReportsRevisionConflictAndTimeout)
{
    PocoDDS::Transport::InMemoryTransport transport;
    PocoDDS::Core::Configuration configuration;
    PocoDDS::Control::ControlPlaneAgent agent(transport, configuration, "worker.one",
                                              [](const auto&) {});
    PocoDDS::Control::ControlPlaneClient client(transport, "admin");

    auto conflict = client.applyConfiguration("worker.one", {{"quality", "low"}}, 99, 100ms);
    EXPECT_FALSE(conflict.success);
    EXPECT_EQ(conflict.error, "configuration revision conflict");
    EXPECT_THROW(
        client.executeLifecycle("missing", PocoDDS::Control::LifecycleAction::Stop, 100ms, 20ms),
        std::runtime_error);
}

TEST(ControlPlaneClientTest, ConnectsAdminCommandsToRemoteControlAgent)
{
    PocoDDS::Transport::InMemoryTransport transport;
    PocoDDS::Core::Configuration remoteConfiguration;
    PocoDDS::Core::Configuration adminConfiguration;
    PocoDDS::Core::ComponentRegistry registry;
    bool stopped = false;
    PocoDDS::Control::ControlPlaneAgent agent(
        transport, remoteConfiguration, "remote.service", [&](const auto& command)
        { stopped = command.action == PocoDDS::Control::LifecycleAction::Stop; });
    PocoDDS::Control::ControlPlaneClient client(transport, "admin.runtime");
    PocoDDS::Admin::AdminService admin(
        registry, adminConfiguration,
        [&](const auto& target, const auto& action)
        {
            const auto mapped = action == "stop" ? PocoDDS::Control::LifecycleAction::Stop
                                                 : PocoDDS::Control::LifecycleAction::Restart;
            const auto result = client.executeLifecycle(target, mapped, 100ms, 100ms);
            return PocoDDS::Admin::LifecycleResult{result.success, result.error};
        });
    admin.routeConfiguration(
        [&](const auto& target, const auto& changes, auto revision)
        {
            const auto result = client.applyConfiguration(target, changes, revision, 100ms);
            return PocoDDS::Admin::ConfigurationResult{result.success, result.error,
                                                       result.configurationRevision};
        });

    auto configured = admin.applyConfiguration("remote.service", {{"mode", "safe"}}, 0);
    EXPECT_TRUE(configured.success);
    EXPECT_EQ(configured.revision, 1U);
    EXPECT_EQ(remoteConfiguration.get("mode"), "safe");
    EXPECT_TRUE(admin.execute("remote.service", "stop").success);
    EXPECT_TRUE(stopped);
}
