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

## 运行时故障事件

SystemMonitoring 将设备和协议的结构化 Failure 状态变化映射为 `runtime.diagnostics` Trace，同时写入结构化日志和最近事件缓冲区。检测与恢复分别使用 `failure.detected`、`failure.resolved`，事件中的 `traceId` 可直接关联 `GET /api/v1/business-traces/{traceId}`。这个桥接位于 SystemMonitoring，因此设备和协议组件不需要反向依赖 Observability。

查询接口为 `GET /api/v1/diagnostic-events`。事件是进程内、最多 500 条的操作视图；需要跨重启审计时，应继续使用日志采集或 OTLP Collector。

告警策略层通过 `GET /api/v1/alerts` 暴露状态和生效配置。越过去抖、升级及恢复阈值时，分别产生 `alert.opened`、`alert.escalated`、`alert.resolved` 日志和 `pdr.alert.transitions` Counter；同一告警的 `runtime.alerts` Trace 使用稳定 traceId 更新，便于从 Web/API 跳转到完整生命周期。

投递扩展实现 `PocoDDS::Reliability::AlertSink` 并以 OSP 服务属性 `pdr.alertSink=true` 注册。Runtime 为每个 Sink 建立独立的有界队列和工作线程；单个慢端点、超时或重试不会阻塞其他 Sink，同时同一 Sink 内仍保持事件顺序。`pdr.alert.delivery` 暴露 success、error 和 dropped。内置 JSONL Sink 同时为 `GET /api/v1/alert-history` 提供跨重启历史；`GET /api/v1/alert-sinks` 可确认当前注册的 Sink，并返回逐 Sink 的成功、失败、丢弃、排队深度、是否正在投递、连续失败、最后成功/失败时间与最近错误，但不会返回 URL、令牌或证书口令。

独立 `pdr.alert.webhook` Bundle 支持 HTTP/HTTPS POST、408/429/5xx 和传输异常重试、稳定 `Idempotency-Key`、严格服务端证书校验及可选 mTLS。鉴权值和私钥口令只从环境变量读取，不写入属性文件。

Webhook 同时支持 `pdr.alerts.webhook.count` indexed 多实例配置，并保留旧单实例配置兼容。每个实例注册为独立 AlertSink，因此一个目标的重试、健康统计和熔断不会与另一个目标混淆。
