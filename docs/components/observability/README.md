# Observability 组件

## 职责

`platform/observability` 记录业务、步骤、耗时、结果和经过清洗的字段，并通过 DDS 汇总追踪快照或导出 OTLP HTTP/JSON。

## 实现过程

`BusinessTracer` 创建业务跨度，`TraceStore` 保存运行中和已完成快照，`TraceSerialization` 负责 JSON，`TraceHttpServer` 提供查询，`OtlpHttpJsonExporter` 对接 Collector。W3C trace context 放入 DDS `Envelope` 实现跨进程传播。

## 用法

配置时启用：

```powershell
cmake -S . -B build -DPDR_ENABLE_OBSERVABILITY=ON
```

代码中使用 `BusinessTracer::startBusiness()`，再为关键环节调用 `startStep()`。不要记录密码、令牌或完整个人信息。完整 API 和字段规则见 [业务追踪说明](../../BUSINESS_TRACING.md)。
