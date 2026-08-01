# Observability 组件

## 职责

`platform/observability` 记录业务追踪以及 Runtime、DDS、设备、协议、工作流和系统指标，并通过 DDS 汇总追踪快照或通过 OTLP HTTP/JSON 导出遥测数据。

## 实现过程

`BusinessTracer` 创建业务跨度，`TraceStore` 保存运行中和已完成快照，`TraceSerialization` 负责 JSON，`TraceHttpServer` 提供查询，`OtlpHttpJsonExporter` 对接 Collector。W3C trace context 放入 DDS `Envelope` 实现跨进程传播。

## 用法

配置时启用：

```powershell
cmake -S . -B build -DPDR_ENABLE_OBSERVABILITY=ON
```

代码中使用 `BusinessTracer::startBusiness()`，再为关键环节调用 `startStep()`。不要记录密码、令牌或完整个人信息。完整 API 和字段规则见 [业务追踪说明](../../BUSINESS_TRACING.md)。

## 运行链路

```text
BusinessTracer
  └─ BusinessSpan
      ├─ StepSpan
      ├─ TraceStore（本地快照）
      ├─ pdr.observability.span（DDS 聚合）
      └─ OtlpHttpJsonExporter（可选）
```

运行中跨度和已完成跨度都能被 WebUI 查询。跨进程请求时 DDS `Envelope` 携带 traceparent/tracestate，接收方从该上下文继续创建子跨度。

## 构建和配置

```powershell
cmake -S . -B build -DPDR_ENABLE_OBSERVABILITY=ON
cmake --build build --config Release
```

```properties
# 空值：本地 TraceStore 和 WebUI 可用，不向 Collector 导出
observability.otlpHttpEndpoint =

# OTLP/HTTP JSON 接收端
observability.otlpHttpEndpoint = http://127.0.0.1:4318/v1/traces
```

## 代码示例

```cpp
auto business = tracer.startBusiness("device-command");
business.setInput("deviceId", deviceId); // 只放允许记录的字段
auto step = business.startStep("dds-request");
try {
    sendRequest();
    step.succeed();
    business.succeed();
} catch (const std::exception& exc) {
    step.fail(exc.what());
    business.fail(exc.what());
    throw;
}
```

字段白名单、跨进程传播及 WebUI 查询接口以 [BUSINESS_TRACING.md](../../BUSINESS_TRACING.md) 为准。

Metrics 的配置、指标目录、基数约束、查询接口和 Collector 验证见 [METRICS.md](../../METRICS.md)。
