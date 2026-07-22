#include "PocoDDS/Transport/InMemoryTransport.h"
#include <gtest/gtest.h>

TEST(InMemoryTransportTest, DeliversByTopicAndPropagatesTraceContext)
{
    PocoDDS::Transport::InMemoryTransport transport;
    std::string traceParent;
    auto subscription = transport.subscribe("render.command", [&](const auto& message)
                                            { traceParent = message.traceParent; });
    transport.publish({"render.command", "RenderCommand", {}, "00-trace-span-01"});
    EXPECT_EQ(traceParent, "00-trace-span-01");
}
