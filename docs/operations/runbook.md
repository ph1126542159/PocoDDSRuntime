# 运行手册

1. 启动前先离线校验实际配置；该命令不会加载 Bundle、启动协议、绑定端口或创建子进程：

```powershell
build/install/bin/pdr.ps1 validate-config `
  build/install/bin/pdr-runtime.properties `
  site/production.properties `
  --prefix build/install `
  --report build/reports/production-config-validation.json
```

配置文件按命令行顺序分层，后面的文件覆盖前面的值，语义与 Runtime 的基础配置加现场覆盖一致。
成功输出 `CONFIG_VALIDATION_OK`；失败逐项输出 `key`、原因并返回非零状态。JSON 报告适合作为
发布证据，但不记录配置文件内容或秘密值。

编辑器、配置生成器和外部管理工具应使用 `contracts/schemas/runtime-config.schema.json`。
该 Schema 发布设备及 MQTT/ROS/UDP 索引配置的类型与范围；仓库中的
`configuration-contract` 会阻止必填项、全局数值范围和索引族与 C++ Validator 静默漂移。

发布包在 `bin/` 中同时携带开发者 CLI、配置检查、发布/升级、Runtime smoke、长稳、
设备验收、协议验收和安全配置检查工具。安装后的 CLI 会自动
把自身上级目录识别为默认 `--prefix`；现场验收不需要保留 PocoDDSRuntime 源码树。

升级统一从 `pdr upgrade` 进入。`apply` 的审计文件必须放在安装目录外；正常生产升级
不得使用 `--skip-health-check`、`--allow-development-release` 或
`--allow-unsigned-release`。Ed25519 私钥路径及可选口令只在受控发布主机通过环境变量注入；
目标端只部署公钥，并以审批记录中的 `keyId` 和公钥 SHA-256 执行 `preflight`。公钥摘要、
签名不匹配或 `keyId` 已吊销时不得停机升级。
Windows 可能在 Runtime 已退出后短暂保留文件句柄。升级器对权限/共享冲突的目录重命名采用
默认 5 秒的有界重试，并把每项操作的尝试次数和耗时写入审计 `renameEvidence`；超时后仍
失败关闭并保留恢复证据。`--rename-timeout` 只用于按现场存储特性调整这个窗口，不能用来
掩盖持续占用安装目录的进程；遇到重复重试应先定位持有句柄的进程。
进程异常退出后若存在
`.pdr-upgrade-transaction.json`/`.pdr-upgrade.lock`，不要删除目录或锁，先停止 Runtime，
再执行 `pdr upgrade recover --target <安装目录>`。恢复器只接受哈希一致的旧版本，
证据不一致时保留所有现场文件并返回失败，交由人工处置。

正式发布构建必须从干净 Git 工作区执行 `cmake --preset release`、
`cmake --build --preset release` 和 `ctest --preset release`。普通开发构建中的
`release-artifacts` 只验证安装包与 Manifest 流程，不等同于正式发布批准；以 Manifest 的
`cleanRequired` 和 `dirty` 字段区分两者。

完整 CTest 结束后，用统一资格命令绑定测试日志、关键报告和安装树清单：

```powershell
python E:/PocoDDSRuntime/tools/pdr.py release qualify `
  --source E:/PocoDDSRuntime --build E:/PocoDDSRuntime/build/full `
  --version 0.1.0 --config Release --expected-tests 96 `
  --ctest-log E:/PocoDDSRuntime/build/full/Testing/Temporary/LastTest.log `
  --artifact-manifest E:/PocoDDSRuntime/build/full/reports/release-smoke/SHA256SUMS.json `
  --artifacts E:/PocoDDSRuntime/build/full/release-smoke-install `
  --evidence package=E:/PocoDDSRuntime/build/full/reports/runtime-package-smoke.json `
  --evidence upgrade=E:/PocoDDSRuntime/build/full/reports/runtime-upgrade-acceptance-integration.json `
  --required-external petalinux-target --required-external physical-protocols `
  --required-external production-identity --required-external soak-24h `
  --report E:/PocoDDSRuntime/build/full/reports/release-qualification.json
```

`LOCAL_VALIDATION_PASSED` 只表示本机自动化证据完整。只有 Release 配置、干净 Git 提交、制品清单、
全部本机报告和每项 `--required-external` 对应的已批准 JSON 均齐全时，才输出
`RELEASE_CANDIDATE_APPROVED`。正式流水线增加 `--require-release-approval`，资格不完整时返回 2；
测试失败、未运行、数量不符、日志不完整/过期或本机报告失败时输出 `DENIED` 并返回 1。
报告遵循 `contracts/schemas/release-qualification.schema.json`，包含输入文件 SHA-256、Git 提交、
平台信息、拒绝原因和不可由本机替代的边界。
默认必需本机证据名为 `package`、`upgrade`、`identity`、`persistence`、`protocol`；缺少任何一项
都会拒绝。定制产品可以显式列出一个或多个 `--required-evidence` 替换默认集合，但每个名字仍须
存在对应的 `--evidence NAME=PATH` 且报告给出通过结论。

外部验收不能手写一个 `APPROVED` JSON。先为同一候选生成固定检查表：

```powershell
python tools/pdr.py release external-template `
  --type petalinux-target --version 0.1.0 --git-commit <commit> `
  --artifact-manifest build/full/reports/release-smoke/SHA256SUMS.json `
  --output field/petalinux-target.template.json
```

现场完成全部检查后，为每个检查 ID 提供至少一份附件，并显式确认：

```powershell
python tools/pdr.py release external-approve `
  --template field/petalinux-target.template.json `
  --evidence image-identity=field/image.txt `
  --evidence boot-cycle=field/boot-cycle.log `
  --evidence runtime-health=field/health.json `
  --evidence resource-boundary=field/cgroup.txt `
  --evidence upgrade-rollback=field/upgrade.json `
  --approver-id qa-team --approval-record CHANGE-42 `
  --confirm-all-checks-passed --output field/petalinux-target.json `
  --signature-output field/petalinux-target.sig.json --key-id qa-2026 `
  --private-key-path-environment PDR_EXTERNAL_APPROVAL_PRIVATE_KEY
```

批准命令拒绝缺项、未知检查和重复覆盖，并把附件复制到同名 `.evidence/` 归档后记录大小及
SHA-256。`external-verify` 会重算报告内容摘要、候选身份和全部附件；qualification 对
`--external-evidence NAME=PATH` 自动执行同样复验。报告、`.evidence/` 目录和资格文件必须一起
归档，任一附件被移动、删除或修改都会使发布资格 fail-closed。

批准私钥只能通过环境变量间接提供，可选口令同样使用
`--private-key-passphrase-environment`。发布主机保存固定摘要的信任策略，例如：

```json
{
  "schemaVersion": 1,
  "product": "PocoDDSRuntimeExternalAcceptance",
  "policyId": "production-qa-2026",
  "allowedApprovers": [{
    "approverId": "qa-team",
    "keyId": "qa-2026",
    "algorithm": "Ed25519",
    "publicKeyPath": "qa-2026-public.pem",
    "publicKeySha256": "<64-hex>",
    "acceptanceTypes": ["petalinux-target", "physical-protocols", "soak-24h"],
    "notBefore": "2026-01-01T00:00:00Z",
    "notAfter": "2027-01-01T00:00:00Z"
  }],
  "revokedKeys": []
}
```

Qualification 对每份外部报告同时要求同名 `--external-signature NAME=PATH`，以及
`--external-trust-policy`、`--expected-external-trust-policy-id`、
`--expected-external-trust-policy-sha256` 和位于可信安装目录的
`--signature-check-executable`。它核对批准者、keyId、允许验收类型、批准时间、密钥有效期、
吊销列表、公钥摘要和 Ed25519 签名。仅在策略文件本身摘要匹配时才信任其中的公钥路径。

资格生成后可一条命令归档并签署全部证据；正式交付增加 `--include-artifacts`，把 Manifest 对应
的完整安装树一并封装：

```powershell
python tools/pdr.py release bundle-create `
  --qualification build/full/reports/release-qualification.json `
  --include-artifacts --output dist/pdr-0.1.0-evidence.zip `
  --signature-output dist/pdr-0.1.0-evidence.sig.json `
  --key-id release-evidence-2026 `
  --private-key-path-environment PDR_EVIDENCE_BUNDLE_PRIVATE_KEY
```

隔离机器只需证据 ZIP、分离签名、可信公钥及安装包内的验签器：

```powershell
python bin/pdr.py release bundle-verify `
  --bundle pdr-0.1.0-evidence.zip --signature pdr-0.1.0-evidence.sig.json `
  --public-key release-evidence-2026-public.pem `
  --expected-key-id release-evidence-2026 `
  --expected-public-key-sha256 <64-hex> `
  --signature-check-executable bin/pdr-signature-check.exe
```

离线复验先验证整个 ZIP 的 Ed25519 签名，再拒绝越界/重复路径、缺失或多余文件、大小或摘要变化；
若包含制品，继续对照内层 `SHA256SUMS.json` 逐文件复验；若包含外部批准，继续复验其内容摘要、
附件、信任策略、公钥和外部签名。`evidence-bundle.schema.json` 定义内部清单契约。

## 一键发行编排与恢复

复制安装包 `share/PocoDDSRuntime/examples/release-pipeline.example.json`，修改源码根、构建根、工具路径、
版本、当前 CTest 数量和候选输出路径。计划中的 `command` 是参数数组，执行器不经过 shell，也不接受
计划内明文环境变量；签名密码等继续从启动进程环境继承。

```powershell
python tools/pdr.py release pipeline-run `
  --plan site/release-pipeline.json `
  --state build/full/reports/release-pipeline-state.json `
  --confirm-run
```

每阶段执行前验证 `requiredInputs`，成功后记录 `requiredOutputs` 的大小及 SHA-256，并把 stdout/stderr
分别保存在状态文件旁的 `.logs/` 目录。状态绑定计划 SHA-256、Git commit 和 dirty 工作树 SHA-256；
并发运行由 PID 锁拒绝，异常退出遗留的锁只在原 PID 已不存在时回收。

失败或机器重启后使用同一计划和状态恢复：

```powershell
python tools/pdr.py release pipeline-status `
  --state build/full/reports/release-pipeline-state.json
python tools/pdr.py release pipeline-resume `
  --plan site/release-pipeline.json `
  --state build/full/reports/release-pipeline-state.json `
  --confirm-run
```

恢复只跳过摘要仍一致的已通过阶段。计划、源码或任何已完成输出变化都会拒绝续跑，必须重新选择新的
状态路径从头执行。阶段超时上限为 24 小时；单阶段退出非零或超时都会持久化失败状态和日志。
计划契约为 `contracts/schemas/release-pipeline.schema.json`。

2. 从安装目录 `bin/` 启动 `pdr-runtime`。启动时仍会执行同一个 C++ `ConfigurationValidator`，
   防止绕过离线检查。
3. 访问 `/health/live` 确认进程存活。
4. 访问 `/health/ready` 确认可接收业务；HTTP 503 表示降级或未就绪。
5. 访问 `/health/detail` 查看 Bundle、子进程、必需协议和必需设备明细。响应契约版本为 2；
   非健康组件提供稳定 `code`、受影响实例 `affected` 和处置建议 `remediation`，可直接用于
   告警路由与现场故障单。完整 SystemMonitoring Profile 同时发布
   `pdr.health.component.samples` 计数器，按 `component`、`status` 和可选 `code` 分组；告警系统
   应对 `DEGRADED`/`DOWN` 样本持续增长设置窗口阈值，避免单次探测抖动直接触发升级。
   定位到实例后，`/api/v1/devices` 和 `/api/v1/protocols` 的 `diagnostics.failure` 给出稳定
   错误码、类别、可重试属性、当前/已恢复状态及微秒时间戳。自动恢复只能处理
   `retryable=true`，配置、硬件和安全类别仍需进入对应人工处置队列。
   完整监控 Profile 还发布 `pdr.diagnostics.failure.samples`，属性包含 `domain`、`instance`、
   `code`、`category` 和 `active`，使指标告警与 API/Web 使用同一错误码。
   Home WebUI 首页会聚合显示 LIVE、READY、组件明细和平台能力；黄色表示降级，需要展开健康详情定位。
6. 查看 `logs/pdr-runtime.log`，使用 traceId/requestId 关联业务记录。

## 安装包启动验收

发布前必须从一个新的安装前缀启动，不能只运行构建目录中的程序：

```powershell
python bin/runtime_smoke.py `
  --executable C:/deploy/PocoDDSRuntime/bin/pdr-runtime.exe `
  --working-directory C:/deploy/PocoDDSRuntime/bin `
  --path C:/deploy/PocoDDSRuntime/bin `
  --timeout 30 `
  --stability-window 2 `
  --endpoint /health/detail `
  --report build/reports/runtime-package-smoke.json
```

工具使用未占用的本机端口，依次要求 `/health/live` 和 `/health/ready` 返回 HTTP 200，并在成功或失败后终止 Runtime 及其子进程。JSON 报告和同名 `.log` 文件应作为发布证据保存。

交付验收时不得把构建目录、Qt SDK 或开发机依赖目录加入 `PATH`；否则无法证明包是自包含的。Edge/Test 安装规则会连同 Qt DLL、平台插件、渲染器和场景插件一起安装 Qt3D 子进程。

7. 停止时使用正常终止信号，等待子进程按配置超时退出。
# 长稳测试

长稳工具启动目标进程、定期采集 RSS 和句柄/文件描述符数量，并生成 JSON 趋势报告。
默认采集范围是 Runtime 及其全部后代进程，因此 Qt3D、渲染器和受管工具的资源增长也会计入阈值；
报告中的 `resourceScope=tree`、`processCount` 和 `peakProcessCount` 用于证明采样没有只覆盖父进程。
只有在明确诊断单个进程时才使用 `--resource-scope process`，这种报告不能替代发布长稳证据。
例如执行 24 小时 Runtime 长稳：

```powershell
python bin/soak_runner.py `
  --duration 86400 `
  --interval 30 `
  --warmup 10 `
  --max-rss-growth-mib 128 `
  --max-handle-growth 32 `
  --health-url http://127.0.0.1:9080/health/ready `
  --health-timeout 2 `
  --max-consecutive-health-failures 0 `
  --output build/reports/runtime-soak-24h.json `
  --cwd build/bin `
  -- ./pdr-runtime.exe
```

72 小时测试将 `--duration` 改为 `259200`。报告中的 `passed`、违规原因、首末资源差、
峰值和全部采样点必须与对应版本、配置及测试环境一起保存。主机长稳通过不能替代
PetaLinux 板端、真实设备和 HIL 长稳。

长稳工具在每个采样点（包括停止前最后一个样本）同时记录 HTTP 健康状态；任何连续健康失败超过阈值都会使报告失败。结束或异常时会清理整个进程树，避免 Runtime 的 Qt3D 等子进程污染后续轮次。

## 协议网关 24/72 小时恢复长稳

普通 `soak_runner.py` 证明 Runtime 持续存活和资源趋势；协议网关还应在同一进程内持续制造 MQTT/ROS 生命周期变化。以下命令运行约 24 小时：首次 MQTT 连接由测试 Broker 主动断开一次，此后 MQTT 和 ROS 每 5 分钟交替执行一次在线重启，共各 144 次。

```powershell
python tools/runtime_protocol_gateway_integration.py `
  --runtime-smoke tools/runtime_smoke.py `
  --executable build-verify/bin/pdr-runtime.exe `
  --working-directory build-verify/bin `
  --config config/pdr-runtime.properties `
  --install-bin build/install/bin `
  --cycles 144 `
  --cycle-action-delay 300 `
  --health-sample-interval 30 `
  --stability-window 30 `
  --max-rss-growth-mib 128 `
  --max-handle-growth 32 `
  --report build-verify/reports/runtime-protocol-gateway-soak-24h.json
```

工具会根据周期、动作间隔和最终观察窗口自动计算总超时；若显式传入 `--timeout`，小于所需时间会直接拒绝启动。72 小时将 `--cycles` 改为 `432`。通过条件包括：Runtime 全程可就绪、每次 POST 均成功、最终两个必需协议均为 `open=true`、MQTT 至少 `cycles + 2` 次连接、ROS 至少 `cycles + 1` 次连接、测试服务端无协议错误，以及 RSS/句柄增长不超过阈值。报告、Runtime 日志、版本号和测试机环境信息必须一起归档。

资源增长基线取 MQTT 和 ROS 各完成第一次受控重启之后，排除 HTTP/协议线程首次使用时的一次性惰性初始化；报告仍保留启动以来的全部样本，并用 `resourceBaselineStage` 明示实际判定起点。后续所有循环和最终稳定窗口都参与增长判定，不能通过提高阈值掩盖持续泄漏。

## 外部协议实例验收

连接真实 broker、rosbridge 或跨主机 UDP 对端后，使用安装包中的 `bin/protocol_acceptance.py` 对每个必需实例分别采样。不要只检查最终在线；必须让业务工装持续制造双向流量，并按验收计划注入断连。工具会拒绝计数倒退、超限错误/超时、持续关闭、最终关闭或 `desiredOpen=false`。

生产 API 使用 HTTPS 时可配置 `--ca-file`；需要 mTLS 时再配置 `--client-certificate` 和 `--private-key`。Authorization 通过 `--authorization-environment` 指定环境变量名，受口令保护的私钥通过 `--private-key-password-environment` 指定环境变量名。命令行和报告都不应出现秘密值。完整命令见[验收矩阵](acceptance-matrix.md)。

## 结构化故障事件闭环

SystemMonitoring 每 200 ms 在后台观察设备和协议的结构化 `Failure`，不依赖 Web 页面或 API 请求触发。状态首次变为活动故障时生成 `failure.detected`，已知活动故障恢复时生成 `failure.resolved`；相同 code、状态和发生时间不会重复生成事件。最近 500 条事件可通过以下接口查询：

```text
GET /api/v1/diagnostic-events
```

每条事件包含 `traceId`、domain、instance、稳定错误码、category、retryable 和时间戳。用同一 `traceId` 请求 `GET /api/v1/business-traces/{traceId}`，可查看合成的 `runtime.diagnostics` 业务 Trace。日志同时输出可检索键值：

```text
diagnostic.event=failure.detected domain=protocol instance=runtime-mqtt error.code=PDR-PROTOCOL-MQTT-OPERATION_FAILED ... traceId=...
diagnostic.event=failure.resolved domain=protocol instance=runtime-mqtt error.code=PDR-PROTOCOL-MQTT-OPERATION_FAILED ... traceId=...
```

事件缓冲区当前是进程内最近记录，不替代外部日志或 Trace Collector 的长期保存；重启前应由采集系统归档。

### 告警策略

诊断事件之上还有独立的告警状态机。查询 `GET /api/v1/alerts` 可同时获得生效策略以及 `pending`、`firing`、`silenced`、`resolved` 状态。配置项如下：

```properties
pdr.alerts.debounceMilliseconds = 1000
pdr.alerts.escalationMilliseconds = 300000
pdr.alerts.retention = 500
pdr.alerts.silencedCodes = PDR-PROTOCOL-TEST_*,PDR-DEVICE-MAINTENANCE
```

- 故障持续时间短于 debounce 时只处于 pending，恢复后不发送 opened/resolved 告警；
- 持续故障越过 debounce 后进入 firing；越过 escalation 后从 warning 升为 critical；
- 静默规则支持完整错误码或末尾 `*` 前缀，状态为 silenced，但仍保留日志、指标和 Trace 审计；
- 恢复后的告警保留为 resolved。每次转换累加 `pdr.alert.transitions`，并生成可由 traceId 查询的 `runtime.alerts` Trace。

告警转换由有界异步队列投递给所有注册为 `pdr.alertSink=true` 的 OSP 服务，适配器实现公共 `PocoDDS::Reliability::AlertSink` SPI。慢速或失败的 Sink 不阻塞设备/协议监视线程；成功、失败和队列丢弃分别记录到 `pdr.alert.delivery`。静默告警默认不投递给外部 Sink，只有声明 `pdr.alertSink.receiveSilenced=true` 的审计 Sink 才接收。

内置 `local-history` Sink 默认把转换追加到 `${application.dir}data/alerts/alerts.jsonl`，达到 10 MiB 时轮转为 `.1`。`GET /api/v1/alert-history?limit=100` 可跨 Runtime 重启读取最近记录。相关配置：

```properties
pdr.alerts.deliveryQueueCapacity = 1000
pdr.alerts.deliveryFailureThreshold = 5
pdr.alerts.deliveryCircuitOpenMilliseconds = 30000
pdr.alerts.history.enabled = true
pdr.alerts.history.path = ${application.dir}data/alerts/alerts.jsonl
pdr.alerts.history.maximumBytes = 10485760
```

Dispatcher 为每个 Sink 建立容量为 `deliveryQueueCapacity` 的独立队列和工作线程，因此一个端点的超时、退避和重试不会阻塞其他端点；同一 Sink 内按入队顺序串行投递。队列满时只丢弃该 Sink 的新事件，并记录 `pdr.alert.delivery{result="dropped",sink="..."}`。Dispatcher 还对每个 Sink 独立统计连续失败；达到 `deliveryFailureThreshold` 后，仅对该 Sink 熔断 `deliveryCircuitOpenMilliseconds`，其他 Sink 继续投递。熔断期间已经排队的事件不会丢失，而是延迟到冷却结束后作为半开探测；成功会清零连续失败，失败则重新熔断。被熔断延迟的次数记录为 `pdr.alert.delivery{result="circuit_open"}`；为兼容既有 API，该累计字段仍名为 `circuitOpenSkips`。逐 Sink 的队列深度、投递中状态、丢弃和熔断状态均在 `/api/v1/alert-sinks` 暴露。卸载或替换 Sink 时会停止其通道并清理待投递队列，当前网络调用结束后释放服务引用。

内置 Webhook 是独立 AlertSink Bundle，默认关闭。生产环境使用 HTTPS；证书校验默认严格，`insecureSkipVerify=true` 会被生产配置校验拒绝。接收方必须按 `Idempotency-Key` 去重，因为可重试响应可能造成至少一次投递。配置示例：

```properties
pdr.alerts.webhook.enabled = true
pdr.alerts.webhook.url = https://alerts.example.com/pdr
pdr.alerts.webhook.timeoutMilliseconds = 3000
pdr.alerts.webhook.maximumAttempts = 3
pdr.alerts.webhook.initialBackoffMilliseconds = 200
pdr.alerts.webhook.maximumBackoffMilliseconds = 2000
pdr.alerts.webhook.authorizationEnvironment = PDR_ALERT_WEBHOOK_AUTHORIZATION
pdr.alerts.webhook.caCertificate = certificates/alert-ca.pem
pdr.alerts.webhook.clientCertificate = certificates/runtime-client.pem
pdr.alerts.webhook.privateKey = certificates/runtime-client.key
pdr.alerts.webhook.privateKeyPasswordEnvironment = PDR_ALERT_WEBHOOK_KEY_PASSWORD
pdr.alerts.webhook.insecureSkipVerify = false
```

启动 Runtime 前在服务账户环境中设置 `PDR_ALERT_WEBHOOK_AUTHORIZATION`（例如完整的 `Bearer ...` 值）和可选的 `PDR_ALERT_WEBHOOK_KEY_PASSWORD`。配置了环境变量名但变量缺失或为空时，配置校验会拒绝启动。通过 `GET /api/v1/alert-sinks` 检查 `webhook` 和 `local-history` 是否注册，通过 `pdr.alert.delivery{sink="webhook"}` 判断投递结果。邮件、短信、IM 或工单继续作为独立 AlertSink Bundle 接入，Runtime 主 Bundle 不保存第三方密钥。

需要同时投递多个平台时使用 indexed 配置；一旦存在 `count`，它就是权威配置，旧的单实例键会被忽略。每个 id 会形成独立 OSP 服务、指标标签、健康状态和熔断状态：

```properties
pdr.alerts.webhook.count = 2
pdr.alerts.webhook.0.id = operations
pdr.alerts.webhook.0.url = https://ops.example.com/pdr
pdr.alerts.webhook.0.authorizationEnvironment = PDR_OPS_WEBHOOK_AUTHORIZATION
pdr.alerts.webhook.1.id = customer-audit
pdr.alerts.webhook.1.url = https://audit.customer.example/events
pdr.alerts.webhook.1.authorizationEnvironment = PDR_AUDIT_WEBHOOK_AUTHORIZATION
```

未配置 `count` 时继续兼容原有 `pdr.alerts.webhook.enabled/url/...` 单实例配置。

可在线管理的 Bundle 由 `pdr.management.manageableBundles` allowlist 控制，条目可以是精确 symbolic name，也可以是仅在末尾使用 `*` 的前缀模式；默认值为 `pdr.service.*,pdr.device.*,pdr.alert.*,pdr.plugin.*`。单独的全局 `*`、非法模式和重复条目会被配置校验拒绝。无论 allowlist 如何设置，`osp.*`、`com.appinf.osp.*`、`poco.*`、`pdr.platform.*` 和 `pdr.webui.*` 核心范围始终保持只读。可管理扩展可通过 Web 控制台或 `POST /api/v1/bundle-lifecycle` 执行在线启动、停止和重启。进程详情为每个 Bundle 返回 `compatible`、`governanceStatus` 和逐项 `dependencies`；启动或重启会先执行同一套版本范围预检，不兼容时返回 HTTP 409。插件治理页只展示 `pdr.plugin.*`，便于在操作前确认依赖与受管状态。AlertDispatcher 监听 OSP 服务注册变化，Webhook Bundle 重启时会停止并释放旧 Sink 通道，为重新注册的每个 Sink 建立新队列和线程。生产操作前仍应确认接收端支持幂等键，并在重启后检查 `/api/v1/alert-sinks` 已恢复为预期数量。

### 管理写操作认证

生产环境必须配置：

```properties
pdr.management.authentication.required = true
pdr.management.authentication.tokenEnvironment = PDR_MANAGEMENT_BEARER_TOKEN
pdr.management.idempotency.requireRequestId = true
pdr.management.idempotency.persistence.enabled = true
pdr.management.idempotency.persistence.path = ${application.dir}management-idempotency.json
pdr.management.idempotency.retention = 1000
pdr.management.idempotency.ttlMilliseconds = 86400000
```

在启动 Runtime 的服务账户环境中设置 `PDR_MANAGEMENT_BEARER_TOKEN`，客户端通过
`Authorization: Bearer <token>` 调用 `/api/v1/protocols` 的 POST、进程/Bundle 生命周期
和配置提交/回退。环境变量缺失、为空或名称非法会在 HTTP 服务启动前被配置门禁拒绝；
缺失或错误令牌返回 401，正确令牌仍须继续通过目标 allowlist 和参数校验。令牌必须通过
HTTPS 传输，轮换后受控重启 Runtime，并确认 Web 配置卡显示“管理写操作已认证”。
所有管理 POST 同时携带全局唯一的 `X-PDR-Request-Id`。网络超时后使用原 ID 和原请求体
重试；不要生成新 ID，否则服务端会把它视为新操作。成功响应通过
`idempotentReplay=false/true` 区分首次执行与重放；复用 ID 提交不同内容返回 409，缺失
必需 ID 返回 428。服务端以原子 JSON 快照持久化最近 1000 条、最长 24 小时的请求账本；
落盘只含请求 ID、SHA-256 请求指纹和非敏感操作摘要，不保存原始请求体、配置值或令牌。
Runtime 重启后，已完成请求仍可安全重放；重启前尚未确认完成的请求恢复为 `interrupted`，
同 ID 重试返回 409，必须先核对目标真实状态，再用新的请求 ID 提交。`GET
/api/v1/management-tasks` 的 `idempotency` 字段和 `/health/detail` 用于检查账本健康。

若任务快照或幂等账本 JSON 损坏，Runtime 不再因此丢失整组 SystemMonitoring API：Bundle
继续启动，`/health/detail` 降级并返回 `PDR-HEALTH-MANAGEMENT-TASK-PERSISTENCE_FAILED` 或
`PDR-HEALTH-MANAGEMENT-IDEMPOTENCY-PERSISTENCE_FAILED`，管理任务清单中的对应状态会显示
`recoveryRequired=true`。为避免未知请求被重复执行，损坏幂等账本时所有带请求 ID 的管理写
操作返回 503；损坏任务快照时新的异步任务返回 503，同步操作仍受健康幂等账本保护。

恢复时先停止 Runtime，保留损坏文件副本并核对设备、进程和 Bundle 的真实状态；确认不再
需要从该文件取证后，移走损坏文件，再启动 Runtime。不得在 Runtime 运行中用空文件覆盖，
也不得仅为恢复 200 状态而跳过目标状态核对。重启后确认 `healthy=true`、
`recoveryRequired=false`，再恢复管理写流量。

任务快照和幂等账本当前写入 Schema v2，并通过 `contentSha256` 对完整记录数组执行 SHA-256
完整性校验。Runtime 仍可读取无摘要的 v1 文件，并在成功加载后原子迁移为 v2；不支持的
Schema、摘要缺失或摘要不匹配均进入同一故障隔离流程。API 和 Web 会显示当前
`schemaVersion=2`、`integrityAlgorithm=SHA-256`，用于确认迁移已完成。

每次成功替换当前快照前，Runtime 会先校验当前文件，再通过 `.previous.new` 原子更新
`<snapshot>.previous`。`previousAvailable=true` 表示上一版本存在且已通过 Schema/摘要校验。
该文件是离线恢复材料，不会被 Runtime 自动加载：尤其幂等账本若自动回退到较旧版本，可能
遗漏最近完成的请求并造成重复执行。恢复时必须停机、核对真实目标状态，人工验证并复制所需
版本；保留损坏当前文件用于取证。

优先使用 `pdr persistence` 完成离线检查和恢复，不要直接覆盖 JSON。检查命令只读，并输出
当前文件和 `.previous` 的文件 SHA-256、Schema、记录数和内容摘要验证结果：

```powershell
python tools/pdr.py persistence inspect build/full/bin/management-idempotency.json `
  --kind idempotency --report build/full/reports/idempotency-inspect.json
python tools/pdr.py persistence inspect build/full/bin/management-tasks.json `
  --kind tasks --report build/full/reports/tasks-inspect.json
```

只有当前文件损坏且 `recoveryCandidateAvailable=true` 时才进入恢复。先停止 Runtime，核对设备、
进程、协议和 Bundle 的真实状态，并从检查报告复制两个 `fileSha256`。恢复命令以这些摘要作为
乐观并发保护；文件在检查后或准备恢复期间发生变化都会拒绝替换：

```powershell
python tools/pdr.py persistence recover build/full/bin/management-idempotency.json `
  --kind idempotency --operator operator-name --confirm-runtime-stopped `
  --expected-current-sha256 <current.fileSha256> `
  --expected-previous-sha256 <previous.fileSha256> `
  --report build/full/reports/idempotency-recover.json
```

成功恢复会把故障当前文件保留为
`<snapshot>.recovery-<UTC timestamp>.original`，通过 `.recovery.new` 校验后原子替换当前文件，
再执行一次文件和内容摘要验证。每次成功或拒绝均追加到
`<snapshot>.recovery-audit.jsonl`。默认拒绝用旧版覆盖健康当前文件；`--allow-healthy-current`
只用于经过变更审批的明确回滚。恢复后重新启动 Runtime，确认健康 API 和管理任务 API 中
`healthy=true`、`recoveryRequired=false`，并逐项核对真实目标状态后才恢复写流量。

### 一致性恢复点与异地备份

单个 `.previous` 只解决单文件上一版取证，不能证明配置、任务、幂等请求与管理审计处于同一
停机时点。计划升级、迁移或灾难恢复演练前，先停止 Runtime，再创建完整恢复点：

```powershell
python tools/pdr.py persistence backup `
  --tasks build/full/bin/management-tasks.json `
  --idempotency build/full/bin/management-idempotency.json `
  --configuration build/full/bin/pdr-runtime.properties `
  --management-audit build/full/bin/management-audit.jsonl `
  --output D:/PocoDDSRuntime-recovery-points `
  --operator operator-name --confirm-runtime-stopped `
  --report build/full/reports/recovery-point-create.json
```

命令会自动纳入存在的 `management-audit.jsonl.1`，在输出目录内建立隐藏暂存目录，复制并核对
每个文件，生成 `recovery-manifest.json` 和 `recovery-manifest.sha256`，完整复验后再把目录
原子发布为 UTC 时间戳和 UUID 命名的恢复点。输入快照损坏、必需文件缺失或未确认停机时，
不会发布半成品。

复制到另一磁盘、备份服务器或离线介质后必须在目标端独立复验：

```powershell
python tools/pdr.py persistence verify-recovery-point `
  D:/PocoDDSRuntime-recovery-points/<recovery-point> `
  --report build/full/reports/recovery-point-verify.json
```

复验会拒绝清单或文件摘要不匹配、缺失/多余文件、重复角色和路径越界。SHA-256 用于传输与
介质完整性，不等同于防恶意篡改的数字签名；生产环境应把清单摘要写入独立的只追加审计系统，
或对恢复点使用组织的签名/不可变存储。至少保留最近一次已复验恢复点、升级前恢复点和一份
异地副本；删除旧恢复点前先完成新恢复点的目标端复验。当前 CLI 不自动清理历史恢复点，避免
保留策略配置错误导致不可恢复删除。

完成目标端复验并取得变更审批后，可在隔离演练目录或已停止的 Runtime 数据目录执行整套还原：

```powershell
python tools/pdr.py persistence restore-recovery-point `
  D:/PocoDDSRuntime-recovery-points/<recovery-point> `
  --tasks D:/PocoDDSRuntime/bin/management-tasks.json `
  --idempotency D:/PocoDDSRuntime/bin/management-idempotency.json `
  --configuration D:/PocoDDSRuntime/bin/pdr-runtime.properties `
  --management-audit D:/PocoDDSRuntime/bin/management-audit.jsonl `
  --archive-output D:/PocoDDSRuntime/pre-restore-evidence `
  --operation-audit D:/PocoDDSRuntime/restore-operations.jsonl `
  --operator operator-name --confirm-runtime-stopped `
  --expected-manifest-sha256 <approved-manifest-sha256> `
  --report D:/PocoDDSRuntime/restore-report.json
```

`--operation-audit` 必须位于被还原目标之外。命令先把目标当前状态和缺失状态发布为独立的
`pre-restore-evidence` 目录，再把全部来源复制到各目标旁的暂存文件并验证。正式替换前会再次
核对恢复点清单摘要和所有目标当前摘要；准备期间有任何变化都会拒绝。替换采用
`staged-replace-with-rollback`：任一文件替换、摘要或快照内容回读失败时，从恢复前归档恢复
所有目标并逐一验证。恢复点没有 `.1` 审计时，目标的陈旧 `.1` 会先归档再移除。退出码 0
表示整套还原及外部审计完成，2 表示未修改或已成功回滚，3 表示回滚或最终审计不完整，必须
停止后续启动并人工处理。

还原成功不等于业务状态已经闭环。启动 Runtime 后依次检查 `/health/live`、`/health/ready`、
`/health/detail` 和 `/api/v1/management-tasks`；对所有 `interrupted` 请求核对协议、进程、
Bundle 和设备真实状态。只有健康门禁通过且未知操作完成逐项处置后，才恢复管理写流量。

使用恢复验收器生成最终门禁报告。管理接口启用认证时，令牌只从环境变量读取：

```powershell
$env:PDR_RECOVERY_VALIDATOR_TOKEN = '<secret-from-secure-store>'
python tools/pdr.py persistence validate-restored-runtime `
  --base-url https://runtime.example.com `
  --restore-report D:/PocoDDSRuntime/restore-report.json `
  --operation-audit D:/PocoDDSRuntime/restore-operations.jsonl `
  --expected-restore-id <restore-id> --operator validator-name `
  --authorization-environment PDR_RECOVERY_VALIDATOR_TOKEN `
  --timeout 60 --report D:/PocoDDSRuntime/restore-acceptance.json
```

验收器先确认 restore 报告为成功事务，且外部审计中同一 restore ID 恰有一条 started 和一条
成功 finished；证据不完整时不会访问 Runtime。随后轮询四个接口，要求 live/ready/detail
全部为 UP，并要求任务快照和幂等账本均为 Schema v2、SHA-256、`healthy=true`、
`recoveryRequired=false`。非回环 HTTP URL 会被拒绝，远程目标必须使用 HTTPS。报告不会保存
Bearer Token，也不会保存完整的 1000 条任务响应。

存在 interrupted 项时首次执行会输出 `DENIED`，并列出任务 ID 和幂等 interrupted 数量。
逐项核对真实状态后创建处置文件：

```json
{
  "schemaVersion": 1,
  "restoreId": "<restore-id>",
  "approvedBy": "reviewer-name",
  "approvedAt": "2026-08-01T18:00:00Z",
  "items": [
    {
      "type": "management-task",
      "id": "<task-id>",
      "decision": "no-retry",
      "verifiedState": "bundle already active",
      "evidence": "incident-or-change-ticket"
    },
    {
      "type": "idempotency-ledger",
      "id": "aggregate",
      "count": 1,
      "decision": "retry-with-new-request-id",
      "verifiedState": "target remained stopped",
      "evidence": "device-and-audit-check"
    }
  ]
}
```

`decision` 只能是 `no-retry` 或 `retry-with-new-request-id`；幂等聚合项的 count 必须精确匹配
API。再次执行时增加 `--dispositions <file>`。只有事务证据、Runtime、持久化和全部处置同时
通过，报告才返回 `verdict=APPROVED` 与 `approvedForManagementWrites=true`。该结论是恢复写
流量的门禁证据，不会自动重放操作，也不会直接修改防火墙、负载均衡或 Runtime 配置。

### Runtime 停机验收

`runtime_smoke.py` 默认向独立进程组发送优雅停止信号，等待
`--shutdown-timeout`（默认 10 秒），并把 `shutdown.mode`、`exitCode`、`clean` 和耗时写入报告。
正常 smoke 只有 `mode=graceful`、`exitCode=0`、`clean=true` 才通过；超时后会清理进程树，但
测试结果为失败。`--allow-forced-shutdown` 只适用于外部环境暂时无法支持优雅信号、且不作为
发布证据的诊断运行。

`--force-shutdown` 是崩溃注入，不是加速测试的选项。仅在验证 queued/running→interrupted、
损坏文件不被正常关闭流程覆盖或类似故障恢复语义时使用；报告会标记
`mode=forced-requested` 和 `expected=true`。同一验收链的恢复启动必须重新通过优雅退出门禁。
若 Windows 返回 `0xC0000374`，按堆损坏处理，检查 Bundle stop 中 OSP Service 是否被
`AutoPtr` 与 `SharedPtr` 双重管理，以及跨线程停止标志是否存在非原子数据竞争，禁止把该
退出码加入允许列表。

建议生产部署用最小权限 Principal 替代单个全权限令牌：

```properties
pdr.management.authentication.tokenEnvironment =
pdr.management.authentication.principals.count = 2
pdr.management.authentication.principals.0.id = operator
pdr.management.authentication.principals.0.tokenEnvironment = PDR_OPERATOR_TOKEN
pdr.management.authentication.principals.0.permissions = protocol.manage,process.manage,bundle.manage
pdr.management.authentication.principals.1.id = configurator
pdr.management.authentication.principals.1.tokenEnvironment = PDR_CONFIGURATOR_TOKEN
pdr.management.authentication.principals.1.permissions = configuration.manage,audit.read
```

Principal ID 必须唯一，令牌环境变量也不能复用。权限不足返回 403；通过
`GET /api/v1/process-config` 的 `managementSession` 核对当前令牌对应身份和权限。环境变量
只在重载时从当前进程环境读取，外部不能修改已运行进程的环境；需要不停机轮换时改用文件：

```properties
pdr.management.authentication.principals.0.tokenEnvironment =
pdr.management.authentication.principals.0.tokenFile = D:/PocoDDSRuntime/secrets/operator.token
pdr.management.authentication.principals.0.permissions = protocol.manage,process.manage,bundle.manage,identity.manage
```

先把新令牌写入同目录临时文件，设置与旧文件相同的最小 ACL，再用原子 rename/replace 覆盖
`operator.token`。随后用旧令牌和唯一 `X-PDR-Request-Id` 调用 `POST /api/v1/identity`；成功
响应的 `generation` 必须比 `generationBefore` 大 1。下一次请求起旧令牌应返回 401，新令牌应
成功。若返回 400，检查 Secret 文件但不要反复覆盖：服务保证旧 `generation` 和旧令牌继续
有效。`GET /api/v1/identity` 只返回代次、身份数和强制认证标志，不暴露 ID 或令牌。

部署前先以实际基础配置和站点覆盖配置执行同一门禁；示例覆盖文件位于
`config/pdr-production-identity.properties.example`，必须复制后替换路径，不能直接部署：

```powershell
python tools/pdr.py identity inspect config/pdr-runtime.properties config/site.properties `
  --prefix build/install --report build/reports/identity-inspect.json
python tools/pdr.py identity check config/pdr-runtime.properties config/site.properties `
  --prefix build/install --report build/reports/identity-check.json
```

`check` 只有在强制认证已启用、至少一个身份来自文件、所有权限检查完成且
`insecureFileCount=0` 时返回 0。Windows 检查 Everyone、Authenticated Users、Builtin
Users、Guests 的有效 ACL；Unix 要求 group/other 权限位为零。报告仅包含统计和拒绝原因，
可直接作为 CI/发布证据，不能把 Secret 文件内容附在问题单中。

### 管理操作审计

```properties
pdr.management.audit.enabled = true
pdr.management.audit.path = ${application.dir}management-audit.jsonl
pdr.management.audit.maximumBytes = 4194304
```

协议、进程、Bundle 和配置管理操作统一写入 JSONL，包括成功、拒绝、失败和幂等重放。
使用具有 `audit.read` 权限的令牌调用
`GET /api/v1/management-audit?limit=100&operation=protocol-lifecycle&status=denied`；还可按
`principal` 精确过滤。接口最多返回 1000 条且按新到旧排列。文件达到上限时轮换为 `.1`，
不会在本机无限增长；正式环境仍应把它采集到只追加的集中审计存储，并对本地文件启用
最小 ACL、备份和篡改检测。

### 异步管理任务

```properties
pdr.management.tasks.workerCount = 2
pdr.management.tasks.capacity = 100
pdr.management.tasks.retention = 1000
pdr.management.tasks.health.degradedWaitMilliseconds = 30000
pdr.management.tasks.persistence.enabled = true
pdr.management.tasks.persistence.path = ${application.dir}management-tasks.json
```

协议、进程和 Bundle 生命周期请求增加 `"async":true` 后返回 HTTP 202 和任务 ID；同步
请求保持原行为。`startTimeoutMilliseconds` 是任务必须开始执行的排队截止时间，
`notBeforeMilliseconds` 可用于延迟调度且必须小于该截止时间；
`executionTimeoutMilliseconds` 是任务开始后的执行期限。通过
`GET /api/v1/management-tasks` 或 `/api/v1/management-tasks/{id}` 查询 `queued`、
`running`、`succeeded`、`failed`、`cancelled`、`timed-out` 状态。具有 `task.cancel`
权限的客户端可向 `/api/v1/management-tasks` 提交
`{"id":"...","action":"cancel"}`。排队任务立即进入 `cancelled`；运行中任务返回 HTTP
202、设置 `cancellationRequested=true` 和 `phase=cancellation-requested`，并在进入底层
调用前或底层调用返回后的协作检查点进入 `cancelled`。已经终止的任务返回 409。当前取消
模式为 `cancellationMode=cooperative`：无法安全强杀第三方阻塞调用，因此执行线程可能要等
底层调用返回才能释放；执行期限同样在检查点判定，超期后进入 `timed-out`，不会伪称已经
中断尚未返回的底层操作。
协议异步生命周期还支持 `stabilityWindowMilliseconds`：操作完成后，协议的开关状态必须
连续保持目标值达到该窗口才算成功。稳定窗口每 25 ms 检查取消令牌和执行期限，适合在发布
或远程维护时避免把瞬时连通误判成稳定恢复；该值必须小于执行期限。
任务管理器按 `operation:target` 生成 `resourceKey`，同一资源上的生命周期操作使用公平等待
队列严格串行执行，不同资源仍可由多个 worker 并行处理。等待期间任务保持 `running`，阶段为
`waiting-resource`，并暴露 `blockingTaskId`、`resourceWaitStartedMicroseconds`、
`resourceAcquiredMicroseconds` 和 `resourceWaitMicroseconds`。资源等待计入执行期限，等待任务可
随时协作取消；因此不要仅凭 `running` 判断底层操作已经开始，应同时检查 `phase`。
延迟任务不会阻塞队列中后续已就绪的任务；调度器在保持已就绪任务提交顺序的同时，跳过
`notBeforeMicroseconds` 尚未到达的项目。任务清单的 `scheduler` 对象暴露 worker、排队、
执行、等锁、资源占用、容量使用和最长等待。`/health/detail` 的 `management-tasks` 组件在
队列达到 capacity、持久化失败，或排队/等锁超过
`pdr.management.tasks.health.degradedWaitMilliseconds` 时进入 `DEGRADED`，并返回稳定错误码和
修复建议。
任务按有界 `retention` 数量原子写入快照。正常终态跨重启可继续查询；强制终止遗留的
`queued` 或 `running` 任务在下次启动时转换为 `interrupted`，保留
`interruptedFromState`，并设置 `recoveryPolicy=verify-before-retry`。Runtime 绝不自动
重放，因为崩溃前操作可能已经部分或全部生效。操作员必须先读取协议、进程、Bundle 或
设备的真实状态，再使用新的请求 ID 人工重提。任务列表中的 `persistence.healthy=false`
必须作为运维故障处理，不能继续宣称任务状态具备跨重启证据。

### 在线配置事务

`POST /api/v1/process-config` 只接受后端 `editableConfiguration()` 放行且已存在于
`pdr-runtime.properties` 的键。请求示例：

```json
{"key":"logging.loggers.root.level","value":"debug"}
```

后端按“全量配置预校验 → `.new` 暂存并回读 → `.rollback` 备份 → 正式文件替换 →
Preferences 应用 → 所属 Bundle 重启”的顺序串行执行。成功响应中的 `validated`、
`persisted`、`applied` 均为 `true`。预校验失败返回 400，不改变文件；写盘后的应用或
重启失败返回 409，并在恢复文件、内存配置和 Bundle 状态后返回 `rolledBack=true`。
`.rollback` 是最近一次提交前的恢复证据，不应当作配置版本库；生产配置仍需纳入
发布包、GitOps 或设备配置管理系统。敏感键永不进入 Web 编辑白名单。

成功事务会同时生成 `.rollback.meta.json`，其中保存事务 ID、键及回退所需的新旧值；
该文件不得对非 Runtime 服务账户开放。人工回退必须先从
`GET /api/v1/process-config` 读取当前 `rollback.transactionId`，然后提交：

```json
{"action":"rollback","transactionId":"1785591394627432"}
```

服务端会比较事务 ID 以及正式文件当前值；事务过期或文件被外部修改时返回 409，绝不
盲目覆盖。每次提交、拒绝和自动回退都会追加到
`pdr-runtime.properties.audit.jsonl`，记录事务 ID、时间、动作、键、结果、所属 Bundle
及请求来源，但不记录配置值。审计文件达到 4 MiB 时轮换为 `.audit.jsonl.1`，最多保留
当前文件和一个归档。人工回退本身也是一个新事务，因此仍可对它执行一次受控撤销。

## 外部插件隔离处置

插件显示“已隔离”时，先查看 `quarantineLastError`，修复或替换插件，再执行“解除隔离”。该操作
清除失败预算并允许再次启动，不会自动证明插件已健康。若同时显示持久化异常，先备份隔离文件；
只有接受重建快照及未知旧记录可能丢失后，才提交 `confirmPersistenceRecovery=true`。不要删除文件
绕过审计，也不要将此能力当作原生崩溃沙箱；进程退出或卡死应由服务管理器在进程边界处置。
