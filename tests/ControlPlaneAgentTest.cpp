#include "PocoDDS/Control/ControlPlaneAgent.h"
#include "PocoDDS/Control/ContractCodec.h"
#include "PocoDDS/Transport/InMemoryTransport.h"
#include <gtest/gtest.h>

TEST(ControlPlaneAgentTest, AppliesConfigurationImmediatelyAndReportsRevision)
{
    PocoDDS::Transport::InMemoryTransport transport;
    PocoDDS::Core::Configuration configuration;
    configuration.addValidator(
        [](const auto& values) -> std::optional<std::string>
        {
            const auto it = values.find("fps");
            if (it != values.end() && it->second == "0")
                return "fps must be positive";
            return std::nullopt;
        });
    PocoDDS::Control::ControlPlaneAgent agent(transport, configuration, "renderer",
                                              [](const auto&) {});
    std::vector<PocoDDS::Control::CommandResult> results;
    std::string receivedTrace;
    auto subscription = transport.subscribe(
        PocoDDS::Control::ResultTopic,
        [&](const auto& message)
        {
            results.push_back(PocoDDS::Control::decodeCommandResult(message.payload));
            receivedTrace = message.traceParent;
        });
    PocoDDS::Control::ConfigurationTransaction transaction{
        1, "config-1", "renderer", 0, {{"fps", "60"}}};
    transport.publish({PocoDDS::Control::ConfigurationTopic, "PocoDDS.ConfigurationTransaction.v1",
                       PocoDDS::Control::encode(transaction), "trace-1"});
    ASSERT_EQ(results.size(), 1U);
    EXPECT_TRUE(results[0].success);
    EXPECT_EQ(results[0].configurationRevision, 1U);
    EXPECT_EQ(configuration.get("fps"), "60");
    EXPECT_EQ(receivedTrace, "trace-1");
}

TEST(ControlPlaneAgentTest, RejectsStaleRevisionWithoutPartialApply)
{
    PocoDDS::Transport::InMemoryTransport transport;
    PocoDDS::Core::Configuration configuration;
    PocoDDS::Control::ControlPlaneAgent agent(transport, configuration, "worker",
                                              [](const auto&) {});
    std::vector<PocoDDS::Control::CommandResult> results;
    auto subscription = transport.subscribe(
        PocoDDS::Control::ResultTopic, [&](const auto& message)
        { results.push_back(PocoDDS::Control::decodeCommandResult(message.payload)); });
    PocoDDS::Control::ConfigurationTransaction transaction{
        1, "stale", "worker", 9, {{"mode", "unsafe"}}};
    transport.publish({PocoDDS::Control::ConfigurationTopic,
                       "PocoDDS.ConfigurationTransaction.v1",
                       PocoDDS::Control::encode(transaction),
                       {}});
    ASSERT_EQ(results.size(), 1U);
    EXPECT_FALSE(results[0].success);
    EXPECT_EQ(results[0].configurationRevision, 0U);
    EXPECT_FALSE(configuration.get("mode").has_value());
}

TEST(ControlPlaneAgentTest, ExecutesLifecycleCommandAndReportsFailure)
{
    PocoDDS::Transport::InMemoryTransport transport;
    PocoDDS::Core::Configuration configuration;
    PocoDDS::Control::LifecycleAction observed = PocoDDS::Control::LifecycleAction::Start;
    PocoDDS::Control::ControlPlaneAgent agent(
        transport, configuration, "bundle-a",
        [&](const auto& command)
        {
            observed = command.action;
            if (command.action == PocoDDS::Control::LifecycleAction::Uninstall)
                throw std::runtime_error("bundle is required");
        });
    std::vector<PocoDDS::Control::CommandResult> results;
    auto subscription = transport.subscribe(
        PocoDDS::Control::ResultTopic, [&](const auto& message)
        { results.push_back(PocoDDS::Control::decodeCommandResult(message.payload)); });
    PocoDDS::Control::LifecycleCommand command{1, "life-1", "bundle-a",
                                               PocoDDS::Control::LifecycleAction::Uninstall, 1000};
    transport.publish({PocoDDS::Control::LifecycleTopic,
                       "PocoDDS.LifecycleCommand.v1",
                       PocoDDS::Control::encode(command),
                       {}});
    ASSERT_EQ(results.size(), 1U);
    EXPECT_EQ(observed, PocoDDS::Control::LifecycleAction::Uninstall);
    EXPECT_FALSE(results[0].success);
    EXPECT_EQ(results[0].error, "bundle is required");
}
