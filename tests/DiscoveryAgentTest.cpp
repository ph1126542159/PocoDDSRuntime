#include "PocoDDS/Control/DiscoveryAgent.h"
#include "PocoDDS/Transport/InMemoryTransport.h"
#include <gtest/gtest.h>

#include <thread>

TEST(DiscoveryAgentTest, DiscoversAndRefreshesRemoteComponent)
{
    PocoDDS::Transport::InMemoryTransport transport;
    PocoDDS::Core::ComponentRegistry registryA;
    PocoDDS::Core::ComponentRegistry registryB;
    PocoDDS::Control::DiscoveryAgent nodeA(transport, registryA, "node-a",
                                           std::chrono::milliseconds(5),
                                           std::chrono::milliseconds(50));
    PocoDDS::Control::DiscoveryAgent nodeB(transport, registryB, "node-b",
                                           std::chrono::milliseconds(5),
                                           std::chrono::milliseconds(50));
    nodeA.registerLocal({"renderer",
                         "Renderer",
                         "host-a",
                         101,
                         PocoDDS::Core::ComponentKind::Process,
                         PocoDDS::Core::ComponentState::Running,
                         {}});
    nodeA.publishNow();
    const auto discovered = registryB.find("renderer");
    ASSERT_TRUE(discovered.has_value());
    EXPECT_EQ(discovered->processId, 101);
    EXPECT_EQ(discovered->state, PocoDDS::Core::ComponentState::Running);
}

TEST(DiscoveryAgentTest, RemovesRemoteComponentAfterLeaseExpires)
{
    PocoDDS::Transport::InMemoryTransport transport;
    PocoDDS::Core::ComponentRegistry registryA;
    PocoDDS::Core::ComponentRegistry registryB;
    PocoDDS::Control::DiscoveryAgent nodeA(
        transport, registryA, "node-a", std::chrono::milliseconds(1), std::chrono::milliseconds(5));
    PocoDDS::Control::DiscoveryAgent nodeB(
        transport, registryB, "node-b", std::chrono::milliseconds(1), std::chrono::milliseconds(5));
    nodeA.registerLocal({"worker",
                         "Worker",
                         "host-a",
                         102,
                         PocoDDS::Core::ComponentKind::Service,
                         PocoDDS::Core::ComponentState::Running,
                         {}});
    nodeA.publishNow();
    ASSERT_TRUE(registryB.find("worker").has_value());
    std::this_thread::sleep_for(std::chrono::milliseconds(8));
    nodeB.sweepExpired();
    EXPECT_FALSE(registryB.find("worker").has_value());
}
