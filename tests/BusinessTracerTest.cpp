#include "PocoDDS/Observability/BusinessTracer.h"

#include "PocoDDS/Admin/AdminService.h"

#include <gtest/gtest.h>

#include <optional>
#include <utility>

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

TEST(BusinessTracerTest, PublishesCompleteBusinessDataWithoutChangingTheOperation)
{
    std::optional<PocoDDS::Observability::CompletedSpan> observed;
    PocoDDS::Observability::BusinessTracerOptions options;
    options.onCompleted = [&](const auto& span) { observed = span; };
    PocoDDS::Observability::BusinessTracer tracer("order-service", std::move(options));

    auto span = tracer.start("submit-order", {{"orderId", "A-42"}});
    span.addLog("inventory reserved");
    span.finish("success", {{"confirmation", "C-9"}});

    ASSERT_TRUE(observed.has_value());
    EXPECT_EQ(observed->serviceName, "order-service");
    EXPECT_EQ(observed->name, "submit-order");
    EXPECT_EQ(observed->status, "success");
    EXPECT_EQ(observed->inputs.at("orderId"), "A-42");
    EXPECT_EQ(observed->outputs.at("confirmation"), "C-9");
    ASSERT_EQ(observed->logs.size(), 1U);
    EXPECT_EQ(observed->logs.front(), "inventory reserved");
    EXPECT_FALSE(observed->traceId.empty());
    EXPECT_FALSE(observed->spanId.empty());
    EXPECT_GT(observed->durationNanoseconds, 0);
}

TEST(BusinessTracerTest, FeedsTheAdministrationTraceAndLogViewsDirectly)
{
    PocoDDS::Core::ComponentRegistry registry;
    PocoDDS::Core::Configuration configuration;
    PocoDDS::Admin::AdminService admin(registry, configuration, [](const auto&, const auto&)
                                       { return PocoDDS::Admin::LifecycleResult{true, {}}; });
    PocoDDS::Observability::BusinessTracerOptions options;
    options.onCompleted = [&](const auto& completed) { admin.appendTrace(completed); };
    PocoDDS::Observability::BusinessTracer tracer("billing.worker", std::move(options));

    auto span = tracer.start("charge", {{"invoice", "I-7"}});
    span.addLog("provider accepted request");
    span.finish("success", {{"transaction", "T-8"}});

    const auto traceIds = admin.recentTraceIds();
    ASSERT_EQ(traceIds.size(), 1U);
    const auto nodes = admin.trace(traceIds.front());
    ASSERT_EQ(nodes.size(), 1U);
    EXPECT_EQ(nodes.front().componentId, "billing.worker");
    EXPECT_EQ(nodes.front().inputs.at("invoice"), "I-7");
    EXPECT_EQ(nodes.front().outputs.at("transaction"), "T-8");
    ASSERT_EQ(nodes.front().logs.size(), 1U);
    const auto logs = admin.logs("billing.worker", traceIds.front());
    ASSERT_EQ(logs.size(), 1U);
    EXPECT_EQ(logs.front().message, "provider accepted request");
}
