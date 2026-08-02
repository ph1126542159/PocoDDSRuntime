# OpenTelemetry Metrics 与业务指标

PocoDDSRuntime 在启用 `PDR_ENABLE_OBSERVABILITY` 时维护进程内指标注册表，并把同一批计数器和直方图写入 OpenTelemetry Metrics SDK。指标可由 Web 管理界面读取，也可按 OTLP/HTTP JSON 协议推送到 Collector。

## 配置

```properties
observability.metrics.serviceName = pdr-runtime
observability.metrics.serviceInstanceId =
observability.metrics.otlpHttpEndpoint = http://127.0.0.1:4318
observability.metrics.exportIntervalMilliseconds = 10000
observability.metrics.exportTimeoutMilliseconds = 5000
observability.metrics.maximumSeries = 2000
```

端点不含路径时自动使用 `/v1/metrics`。留空表示不远程导出，但本地 API 和 WebUI 仍然可用。Exporter 使用 OpenTelemetry C++ 官方 OTLP/HTTP 实现，支持 HTTPS、CA 校验和 mTLS 客户端证书。

```properties
observability.metrics.otlpCaCertificatePath = deploy/observability/certificates/ca.crt
observability.metrics.otlpClientCertificatePath = deploy/observability/certificates/client.crt
observability.metrics.otlpClientKeyPath = deploy/observability/certificates/client.key
observability.metrics.otlpInsecureSkipVerify = false
observability.metrics.offlineCachePath = data/metrics/otlp-cache
observability.metrics.offlineCacheMaximumFiles = 1000
```

导出失败时，当前 OTLP payload 会写入有上限的离线目录；恢复后按时间顺序重放并删除。官方 Exporter 同时执行带指数退避的请求重试。

`maximumSeries` 是进程级基数保护。超过限制的新标签组合会被拒绝，并累计到 `pdr.metrics.series.dropped`。设备标识等标签应使用受控值，不应把请求 ID、日志正文或任意用户输入作为标签。

## 指标范围

| 范围 | 主要指标 |
| --- | --- |
| Runtime | `pdr.runtime.starts`、`pdr.runtime.shutdowns`、子进程数量 |
| DDS | 收发消息、发布错误与耗时、服务请求结果/耗时、队列深度、缓存命中 |
| 设备 | 在线和启动状态、命令类型/操作/结果、命令耗时 |
| 工作流 | 执行结果、执行耗时、补偿结果 |
| 协议 | Modbus、Serial、UDP、XBee、MQTT、ROS、SocketCAN、Bluetooth LE、WebTunnel 的操作、I/O 字节、错误和耗时 |
| 告警 | `pdr.alert.transitions` 统计 opened、escalated、resolved；`pdr.alert.delivery` 按 Sink 统计 success、error、dropped |
| 管理任务 | `pdr.management.tasks.queue.depth`、`workers.active`、`resource.waiting`、`queue.utilization` 和 `wait.max` |
| 系统 | CPU、内存、磁盘、网络、线程和子进程 |
| HTTP | 请求/响应数量和请求耗时，按方法、规范化路由及状态类别聚合 |

项目不使用 Gauge。事件使用单调递增 Counter；瞬时状态、队列深度、资源采样和耗时统一使用 Histogram 的最新值与分布。直方图同时提供 `count`、`sum`、`min`、`max`、`explicitBounds` 和 `bucketCounts`。

## 查询与展示

```text
GET /api/v1/metrics
```

返回 `serviceName`、`serviceInstanceId` 和指标序列。首页“业务指标”区域定时读取此接口，展示 DDS 流量、设备命令、工作流结果和延迟摘要。该接口用于本机诊断；生产环境仍建议由 Collector 接收 OTLP 并交给 Prometheus、Grafana 或其他后端。

## 代码接入

```cpp
auto& metrics = PocoDDS::Observability::Metrics::global();
metrics.addCounter("pdr.order.executions", 1, {{"result", "success"}});
metrics.recordHistogram("pdr.order.queue.depth", queueDepth,
                        {{"queue", "main"}}, "Queue depth", "{item}");
metrics.recordHistogram("pdr.order.duration", elapsedMs,
                        {{"operation", "submit"}}, "Order duration", "ms");
```

短作用域耗时可使用 `ScopedMetricTimer`。指标对象由 Runtime 统一初始化和关闭，业务组件不应自行替换全局 MeterProvider。

## 验证

```powershell
C:\Qt\Tools\CMake_64\bin\ctest.exe --test-dir build -C Release -R '^metrics$' --output-on-failure
Invoke-RestMethod http://127.0.0.1:9080/api/v1/metrics
```

`metrics` 测试会启动本地 HTTP 接收器，验证 `/v1/metrics`、资源属性、指标正文和直方图桶，而不只验证内存快照。

首页侧栏的“指标中心”提供 Runtime、DDS、设备、工作流、协议汇总、MQTT、ROS Bridge、UDP、Bluetooth LE、WebTunnel、HTTP、系统以及导出缓存十三个子页面。运行总览还直接显示 MQTT、ROS Bridge、UDP 的操作数、错误数和收发字节。生产监控栈位于 `deploy/observability`，包含 mTLS Collector、Prometheus、Grafana Dashboard 和告警规则。
