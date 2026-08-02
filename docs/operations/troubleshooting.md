# 故障排查

- 配置错误：依据启动错误中的 key 修复，端口范围为 1–65535，DDS Domain 为 0–232。
- `/health/live` 失败：确认进程和 Web Bundle 是否运行、9080 是否监听。
- `/health/ready` 返回 503：读取 `/health/detail`，优先按非 `UP` 组件的稳定 `code`、
  `affected` 实例列表和 `remediation` 处置；不要只依赖可能变化的 `detail` 文本。
- `PDR-HEALTH-SUBPROCESS-REQUIRED_NOT_RUNNING`：打开受影响子进程日志，修复启动条件后从进程管理页重启。
- `PDR-HEALTH-SUBPROCESS-MANAGER_UNAVAILABLE`：检查 ProcessManagement Bundle 与 Runtime 启动配置。
- `PDR-HEALTH-PROTOCOL-REQUIRED_CLOSED`：查看协议实例最后错误和端点连通性，再执行实例重启。
- `PDR-HEALTH-DEVICE-REQUIRED_NOT_READY`：查看设备最后错误，并核查供电、接线和底层传输。
- `PDR-HEALTH-BUNDLE-NONE_ACTIVE`：检查 Bundle 启动日志、依赖版本和运行级别。
- 进入具体设备或协议后，使用 `diagnostics.failure.code` 做自动分流，使用 `category` 决定责任域，
  仅在 `retryable=true` 时自动重试；`active=false` 表示已经恢复，仍可依据时间戳追查历史原因。
- `PDR-DEVICE-UNCLASSIFIED` 或 `PDR-PROTOCOL-UNCLASSIFIED`：旧适配器仍只提供自由文本；运行不受
  影响，但应在下一次适配器升级时实现对应 Failure 诊断接口，不能长期依赖文本匹配告警。
- 故障时间线：查询 `GET /api/v1/diagnostic-events`，用 `domain + instance + code` 区分故障，
  并确认是否已经出现配对的 `failure.resolved`。复制事件的 `traceId` 查询
  `GET /api/v1/business-traces/{traceId}`，再用同一 traceId 检索日志；不要把“当前已恢复”误判为“从未故障”。
- 没有诊断事件：先确认适配器实现 `FailureDiagnosticDevice` 或 `FailureDiagnosticProtocol`，再确认
  SystemMonitoring Bundle 处于 active。事件观察由后台线程完成，不需要先打开 Web 页面。
- 有诊断事件但没有 firing 告警：查询 `GET /api/v1/alerts` 的生效策略和对应记录；`pending` 表示
  尚未越过去抖时间，`silenced` 表示错误码命中静默规则。不要通过缩短去抖来掩盖适配器抖动。
- 告警未升级：比较 `firstSeenMicroseconds` 与当前时间，并检查
  `pdr.alerts.escalationMilliseconds`。告警转换日志使用 `alert.event=alert.opened|alert.escalated|alert.resolved`。
- 告警投递失败：在 `/api/v1/metrics` 检查 `pdr.alert.delivery` 的 `result=error|dropped`，并按
  `sink` 标签定位适配器。Sink 在独立有界队列执行，单个 Sink 失败不会停止其他 Sink 或诊断监视。
- Webhook 未投递：先查询 `GET /api/v1/alert-sinks`；没有 `webhook` 时检查 enabled、URL 和所引用的
  环境变量。存在 Sink 但持续 error 时，核查 DNS、服务端证书/CA、mTLS 证书对、超时和 HTTP 状态。
  只有 408、429、5xx 与传输异常会重试；其他 4xx 视为永久请求错误。不要在日志或配置中打印鉴权值。
- Sink 状态为 `circuit-open`：最近连续失败已达到阈值，Dispatcher 正在冷却并跳过该 Sink；本地历史和
  其他 Sink 不受影响。先修复 `lastError` 指向的根因，等待 `circuitOpenUntilMicroseconds` 后的自动探测；
  不要通过盲目增大失败阈值掩盖证书、鉴权或网络故障。
- 重启后找不到历史：查询 `GET /api/v1/alert-history` 的 `enabled` 和 `path`，确认运行账户对目录
  有读写权限，并检查同目录 `.1` 轮转文件。当前 API 返回活动文件，归档文件用于离线审计。
- DDS 无数据：确认 Domain ID 一致、Topic 与 `contracts/asyncapi/runtime.yaml` 一致。
- 子进程未启动：检查 `pdr-subprocesses.properties`、可执行文件路径和进程日志。
- Trace 缺失：检查 Observability 构建开关、历史目录权限和 OTLP endpoint。
- 插件启动返回 409：查询 `governanceStatus`。`incompatible` 表示先修复依赖/API/ABI；
  `quarantined` 表示失败预算耗尽，处理 `quarantineLastError` 后再执行 `reset-quarantine`。
- 所有外部插件重启后都未自动启动：检查 `quarantinePersistenceHealthy` 和
  `quarantineRecoveryRequired`。快照损坏会默认阻断；保留现场后使用显式恢复确认，不要直接关闭隔离。
