# OpenTelemetry 业务追踪

PocoDDSRuntime 将一次业务执行建模为一条 OpenTelemetry Trace，将业务中的每一步建模为
父子 Span。运行时 WebUI 的“业务追踪”页面会根据 `traceId`、`spanId` 和
`parentSpanId` 画出流程图，并显示每个节点的输入、输出、状态、耗时、错误和关联日志。

## 业务代码接入

```cpp
#include "PocoDDS/Observability/BusinessTracer.h"

using namespace PocoDDS::Observability;

BusinessTracerOptions options;
options.bundleName = "order.bundle";
options.otlpHttpEndpoint = "http://127.0.0.1:4318/v1/traces"; // 可选
BusinessTracer tracer("order.service", options);

auto business = tracer.startBusiness(
    "处理订单",
    {{"orderId", orderId}},
    orderId); // 不传实例 ID 时自动生成 UUID

try
{
    auto validate = business.startStep("参数校验", {{"request", requestJson}});
    validate.log("参数格式正确");
    validate.success({{"normalizedOrderId", orderId}});

    auto persist = business.startStep("保存订单", {{"orderId", orderId}});
    const auto result = repository.save(orderId);
    persist.success({{"recordId", result.recordId}});

    business.success({{"result", "accepted"}});
}
catch (const std::exception& exception)
{
    business.failure("ORDER_FAILED", exception.what());
    throw;
}
```

`BusinessSpan` 使用 RAII。如果离开作用域时没有调用 `success()`、`failure()` 或
`cancel()`，节点会自动结束为 `cancelled`，不会永久停留在运行中。

## 跨进程和跨服务传播

DDS Envelope 已包含：

- `traceParent`
- `traceState`
- `businessName`
- `businessInstanceId`

调用另一个服务时，应当为调用动作创建步骤，并把上下文附到请求上：

```cpp
#include "TracePropagation.h"

auto call = business.startStep("调用库存服务");
PocoDDS::FastDDS::Envelope request;
request.operation = "reserve";
request.payload = payload;
PocoDDS::FastDDS::attachTrace(request, call, "处理订单");
runtime.publish("inventory.request", request);
```

`ServiceEndpoint` 会自动提取 W3C `traceparent`，创建服务端子 Span，并在响应中继续
携带追踪上下文。服务产生的 Span 快照发布到 `pdr.observability.span` DDS Topic，
由运行时聚合后提供给 WebUI。因此同一 DDS Domain 内的其他进程和其他机器也能汇入
同一张业务流程图。

## 参数安全策略

默认行为：

- 单字段最多 4096 字节；
- 每组输入或输出最多 64 个字段；
- 键名包含 `password`、`passwd`、`secret`、`token`、`authorization`、
  `cookie` 或 `privatekey` 时保存为 `[REDACTED]`；
- 超长值截断并追加 `[TRUNCATED]`。

可以通过 `BusinessTracerOptions::dataPolicy` 调整。二进制、图片和大型文档应记录
长度、摘要、哈希或对象 ID，不应放入 Span 属性。

## 运行配置

```properties
webui.enabled = true
webui.bindAddress = 127.0.0.1
webui.port = 9080
webui.bearerToken =

# 留空时仍保留运行时内存追踪和 WebUI。
observability.otlpHttpEndpoint =
# Collector 示例：
# observability.otlpHttpEndpoint = http://127.0.0.1:4318/v1/traces
```

WebUI 地址为 `http://127.0.0.1:9080/`。非回环地址必须配置至少 16 字符的
Bearer Token。

## API

- `GET /api/v1/business-traces`：最近业务实例和整体状态；
- `GET /api/v1/business-traces/{traceId}`：完整流程节点、参数和日志。

内存存储用于实时页面和开发验收；长期留存、检索、采样、重试和告警应由
OpenTelemetry Collector 及其后端承担。
