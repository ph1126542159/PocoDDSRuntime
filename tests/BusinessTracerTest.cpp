#include "PocoDDS/Observability/BusinessTracer.h"

#include <gtest/gtest.h>

using PocoDDS::Observability::BusinessTracer;

TEST(BusinessTracerTest, PreservesW3CParentAcrossServiceBoundary)
{
    BusinessTracer caller("desktop.main");
    BusinessTracer worker("render.worker");

    auto parent = caller.start("open-model", {{"model", "engine.glb"}});
    const auto traceParent = parent.traceParent();
    ASSERT_EQ(traceParent.size(), 55U);

    auto child = worker.start("render-frame", {{"frame", "42"}}, traceParent);
    child.addLog("GPU upload complete");
    child.finish("success", {{"triangles", "1024"}});
    parent.finish("success");

    auto parentSpans = caller.drain();
    auto childSpans = worker.drain();
    ASSERT_EQ(parentSpans.size(), 1U);
    ASSERT_EQ(childSpans.size(), 1U);
    EXPECT_EQ(parentSpans[0].traceId, childSpans[0].traceId);
    EXPECT_EQ(parentSpans[0].spanId, childSpans[0].parentSpanId);
    EXPECT_EQ(childSpans[0].status, "success");
    EXPECT_GT(childSpans[0].durationNanoseconds, 0);
}

TEST(BusinessTracerTest, EndsAbandonedSpanAsCancelled)
{
    BusinessTracer tracer("background.service");
    {
        auto span = tracer.start("unfinished-job");
    }
    auto spans = tracer.drain();
    ASSERT_EQ(spans.size(), 1U);
    EXPECT_EQ(spans[0].status, "cancelled");
}
