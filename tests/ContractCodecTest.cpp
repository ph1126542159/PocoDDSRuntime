#include "PocoDDS/Control/ContractCodec.h"
#include <gtest/gtest.h>

TEST(ContractCodecTest, RoundTripsComponentManifest)
{
    PocoDDS::Control::ComponentManifest source;
    source.nodeId = "node-a";
    source.component = {"renderer",
                        "3D Renderer",
                        "workstation",
                        42,
                        PocoDDS::Core::ComponentKind::Service,
                        PocoDDS::Core::ComponentState::Running,
                        {{"bundle", "demo.renderer"}}};
    source.heartbeatUnixMilliseconds = 123456;
    source.leaseMilliseconds = 4000;
    const auto decoded =
        PocoDDS::Control::decodeComponentManifest(PocoDDS::Control::encode(source));
    EXPECT_EQ(decoded.nodeId, source.nodeId);
    EXPECT_EQ(decoded.component.id, source.component.id);
    EXPECT_EQ(decoded.component.metadata, source.component.metadata);
    EXPECT_EQ(decoded.heartbeatUnixMilliseconds, source.heartbeatUnixMilliseconds);
}

TEST(ContractCodecTest, RoundTripsConfigurationAndLifecycleContracts)
{
    PocoDDS::Control::ConfigurationTransaction configuration{
        1, "config-7", "renderer", 9, {{"quality", "high"}, {"fps", "60"}}};
    const auto decodedConfiguration =
        PocoDDS::Control::decodeConfigurationTransaction(PocoDDS::Control::encode(configuration));
    EXPECT_EQ(decodedConfiguration.correlationId, "config-7");
    EXPECT_EQ(decodedConfiguration.expectedRevision, 9U);
    EXPECT_EQ(decodedConfiguration.changes.at("fps"), "60");

    PocoDDS::Control::LifecycleCommand lifecycle{1, "life-2", "renderer",
                                                 PocoDDS::Control::LifecycleAction::Restart, 2500};
    const auto decodedLifecycle =
        PocoDDS::Control::decodeLifecycleCommand(PocoDDS::Control::encode(lifecycle));
    EXPECT_EQ(decodedLifecycle.action, PocoDDS::Control::LifecycleAction::Restart);
    EXPECT_EQ(decodedLifecycle.gracefulTimeoutMilliseconds, 2500U);
}

TEST(ContractCodecTest, RejectsTruncatedOrUnsupportedContracts)
{
    PocoDDS::Control::LifecycleCommand command{1, "life-3", "worker",
                                               PocoDDS::Control::LifecycleAction::Stop, 1000};
    auto encoded = PocoDDS::Control::encode(command);
    encoded.pop_back();
    EXPECT_THROW(PocoDDS::Control::decodeLifecycleCommand(encoded), std::invalid_argument);

    auto valid = PocoDDS::Control::encode(command);
    valid[5] = std::byte{2};
    EXPECT_THROW(PocoDDS::Control::decodeLifecycleCommand(valid), std::invalid_argument);
}
