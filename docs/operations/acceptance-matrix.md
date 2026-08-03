# 稳定性与设备验收矩阵

本页定义从“仓库测试通过”到“可以用于现场”的证据边界。未取得对应环境的报告时，状态必须保持 `未验证`，不能用 Windows 主机结果代替板端或真实设备结果。

| 层级 | 环境 | 最低时长/轮次 | 必须通过 | 证据 |
| --- | --- | ---: | --- | --- |
| L0 | CI/开发机 | 每次提交 | 构建、CTest、隔离安装、自包含启动 | CTest XML、`runtime-package-smoke.json` |
| L1 | Windows Edge/Test | 24 h | readiness 全程通过、完整进程树 RSS/句柄增长在阈值内、Qt3D 1/1 | `runtime-soak-24h.json`（`resourceScope=tree`）、Runtime/Qt3D 日志、Profile 清单 |
| L2 | Linux Server | 24 h | readiness 全程通过、完整进程树资源受控、数据持久化、重启恢复 | Soak 报告（`resourceScope=tree`）、SQLite/日志、重启前后哈希 |
| L3 | PetaLinux Embedded | 24 h 后 72 h | 设备启动、网络恢复、磁盘空间、FD/RSS、看门狗恢复 | 板端 Soak、`journalctl`、`df -h`、`df -ih`、Profile 清单 |
| L4 | 真实协议/HIL | 每协议至少 1000 轮及断连注入 | 实际串口/CAN/Modbus/XBee/GNSS 读写、断线重连、错误边界 | 仪器/设备日志、请求响应计数、注入时间线 |
| L5 | 升级/回滚 | 每目标平台至少 20 轮 | 正常升级、坏包拒绝、健康失败自动回滚、断电恢复 | 升级审计 JSONL、版本/哈希、启动日志 |

仓库级 `runtime-upgrade-acceptance-integration` 使用真实安装树执行清单生成、事务替换、
隔离 Runtime 启动、健康探测、优雅退出和人工回滚。通过条件还包括：运行期可变状态跨
升级及回滚保持最新、旧 `codeCache` 未迁移、审计包含 `preflight_passed`、
`staging_verified`、`activated`、`health_passed`、`backup_retention_applied` 和
`manual_rollback`，并且验收报告必须是 `signatureVerified=true`、算法为 `Ed25519`、记录实际
`keyId` 和固定的公钥 SHA-256，且验收工作区不得残留发布私钥。
2026-08-01 的 Windows 主机验收使用同一真实安装树连续执行 20 轮，报告
`build/reports/runtime-upgrade-acceptance-20-cycles.json` 记录 20/20 轮通过、20 次
Runtime 优雅退出、上述六类审计事件各 20 条、80 次目录切换及零事务残留。该结果只证明
Windows 主机的正常升级和人工回滚闭环；健康失败自动回滚、进程中断恢复仍由仓库测试覆盖，
目标 Linux/PetaLinux、真实设备和断电注入必须分别取得对应平台证据后才能完成正式 L5。

WebEvent 安全验收由 `runtime-webevent-auth-integration` 启动五次真实 Runtime：同一启用
AuthService 的配置下，匿名、错误 Basic 凭据及错误 Bearer 访问 `/webevent` 必须返回 401；
使用仅存在于进程环境中的同一临时管理 Principal，正确 Basic 与 Bearer 都必须越过 dispatcher
并进入 WebSocket 握手校验。报告必须记录五次优雅退出且
`credentialsLeaked=false`。HTTP 400 在该测试中表示认证已通过但普通 GET 缺少 WebSocket
升级头，不代表握手失败被当作成功；跨主机 WSS、会话续期和生产身份系统仍需现场验收。

L4 的统一采集入口是安装包中的 `bin/device_acceptance.py`。测试期间由协议测试程序或人工工装持续产生真实读写流量，采集器负责从 `/api/v1/devices` 保存状态和诊断计数，并强制成功增量、失败上限、重连增量、连续失败上限与最终状态。

```powershell
python bin/device_acceptance.py `
  --url http://127.0.0.1:9080/api/v1/devices `
  --device-id cabinet-a --duration 3600 --interval 1 `
  --minimum-success-delta 1000 --minimum-reconnect-delta 1 `
  --maximum-failed-delta 2 --maximum-consecutive-failures 1 `
  --report reports/cabinet-a-hil.json
```

`minimumReconnectDelta=1` 适用于明确安排过断线注入的轮次；未注入断线的基线轮次设为 0。报告只有 `passed=true` 才能作为该轮证据，且仍需同时保存设备/总线侧日志来证明请求确实到达物理端。

MQTT、ROS Bridge 和 UDP 的统一采集入口是安装包中的 `bin/protocol_acceptance.py`。它从 `/api/v1/protocols` 选择一个实例，检查协议类型、最终 `open/desiredOpen`、连续关闭样本、探测错误，以及成功、失败、重连、消息、字节、超时和回调异常增量。以下示例要求测试流量双向传输，并在测试期间安排至少一次断连恢复：

```powershell
$env:PDR_ACCEPTANCE_AUTHORIZATION = "Bearer <现场短期令牌>"
python bin/protocol_acceptance.py `
  --url https://edge.example.com/api/v1/protocols `
  --protocol-id factory-broker --protocol-type mqtt `
  --duration 3600 --interval 1 `
  --authorization-environment PDR_ACCEPTANCE_AUTHORIZATION `
  --ca-file certificates/site-ca.pem `
  --client-certificate certificates/acceptance-client.pem `
  --private-key certificates/acceptance-client.key `
  --minimum-success-delta 1000 --minimum-reconnect-delta 1 `
  --minimum-sent-message-delta 1000 --minimum-received-message-delta 1000 `
  --minimum-sent-byte-delta 8000 --minimum-received-byte-delta 8000 `
  --maximum-failed-delta 2 --maximum-timeout-delta 2 `
  --maximum-consecutive-closed-samples 2 `
  --report reports/factory-broker-acceptance.json
```

Authorization 和私钥口令只能通过环境变量传入；报告仅记录变量名和 TLS 使用状态，不记录秘密。报告的 `passed=true` 仍必须与服务端/broker/抓包日志配套，才能证明数据确实跨主机到达目标系统。

CAN 的 L4 验收还必须覆盖标准帧与扩展帧过滤、经典 CAN 与 CAN FD、总线静默导致的 stale、error frame、bus-off 以及接口恢复。Linux 侧至少同时保存以下证据；接口名、bitrate 和恢复策略必须替换为产品实际值：

```sh
ip -details -statistics link show can0
candump -L -e can0
# 在隔离测试总线上执行受控 bus-off/断连注入
ip -details -statistics link show can0
curl -fsS http://127.0.0.1:9080/api/v1/devices
```

仓库的 `can-device-recovery` 和 `runtime-can-reference-smoke` 只验证软件状态机及 Bundle/API 闭环；Windows loopback 不证明 Linux 内核错误计数、物理收发器或终端电阻。

GNSS 的 `nmea-gnss-device-recovery` 覆盖 checksum、回调隔离、断线重连和定位陈旧；`runtime-gnss-reference-smoke` 覆盖 loopback Bundle/API/诊断闭环。两者都不替代真实模块、天线、卫星环境、首次定位时间和长时间漂移的目标机 HIL。

XBee 的 `xbee-smoke` 覆盖分片保留、转义长度和连续多帧，`xbee-sensor-recovery` 覆盖地址过滤、checksum、回调隔离、重连和陈旧样本，`runtime-xbee-reference-smoke` 覆盖 Bundle/API/诊断闭环。这些软件证据不替代真实串口、AP 模式、射频链路、远端采样周期和长期丢包 HIL。

GPIO/LED 的 `linux-sysfs-recovery` 覆盖临时节点消失与恢复、GPIO export 所有权和回调隔离；`runtime-linux-sysfs-reference-smoke` 覆盖可移植的 Bundle/API/诊断闭环。它不证明目标 Linux 内核启用了旧 sysfs ABI，也不证明权限、pinmux、电平或物理 LED。

MQTT 的 `mqtt-smoke` 使用本地最小 broker 覆盖 QoS 1 发布、消息回调异常隔离、显式重连和订阅恢复。`mqtt-tls-integration` 动态生成临时 CA、服务端和客户端证书，证明正确 CA 与主机名可通过、错误 CA 和主机名不匹配会被拒绝；同一证书随后通过 ProtocolGateway 配置进入完整 Runtime，测试服务端必须验证 Runtime 提交的 mTLS 客户端证书，`/api/v1/protocols` 必须显示必需 TLS 实例在线，环境变量提供的密码标记不得出现在报告或日志。测试还会移除一个已配置的密码环境变量，要求 Runtime fail-fast 且错误明确指出缺失的变量名而不打印秘密。真实 broker 账号策略、证书轮换、持久会话、离线队列、集群切换和长时间网络抖动仍属于集成与 soak 验收。

UDP 的 `udp-smoke` 使用两个本地 Socket 覆盖二进制数据报、发送端身份、超时与关闭边界；跨主机防火墙、路径 MTU、组播、突发丢包和长期吞吐仍需网络环境验收。

ROS 的 `ros-bridge-integration` 使用本机真实 WebSocket 覆盖订阅、文本分片、交错 Ping/Pong、回调异常隔离、取消订阅和关闭。`ros-tls-integration` 动态生成临时 CA、服务端和客户端证书，验证 wss/mTLS、Authorization 环境变量注入、错误 CA 与主机名不匹配拒绝；同一安全配置进入完整 Runtime 后，测试服务端必须确认客户端证书和 Authorization，API 必须显示实例在线，秘密不得出现在报告或日志。外部 rosbridge_server、ROS graph、真实 Topic 类型/QoS、生产认证策略与证书轮换、断网恢复和长稳仍需集成环境验收。

`runtime-protocol-gateway-integration` 将上述协议库证据提升到完整 Runtime 层：它启动两个本机 MQTT TCP 服务端和一个 rosbridge WebSocket 服务端，配置两个 `required=true` 实例以及一个用于热重载故障注入的可选 MQTT 实例。主 MQTT 服务端在首次 CONNACK 后主动断开，Runtime 必须写出自动恢复日志；随后两个必需实例在同一个 Runtime 进程内各执行五次在线 `restart`。主 Webhook 的首次响应被刻意延迟，并用 503 证明同一幂等键重试；审计 Webhook 必须在该慢响应完成之前收到同一 opened 事件，从时间顺序上证明逐 Sink 工作线程隔离。主 Webhook 随后用不可重试 400 触发逐 Sink 熔断；MQTT 恢复产生的 resolved 告警必须在冷却后作为半开探测成功送达。测试随后通过 `/api/v1/bundle-lifecycle` 在线重启 allowlist 放行的 `pdr.alert.webhook`，日志必须证明两个 Sink 服务完成注销和二次注册；同一接口尝试重启始终受保护的 `pdr.platform.systemMonitoring` 必须返回 403，且 Runtime 保持可用。`/api/v1/process-detail` 必须分别把这两个 Bundle 标为 `manageable=true/false`。配置事务还必须依次证明合法日志级别返回 200 且 `validated/persisted/applied=true`、非法日志级别返回 400 且未写盘，以及设备 Bundle 被管理策略禁止重启时返回 409、`rolledBack=true` 且 `pdr.modbus.port` 保持旧值 502。可选 MQTT 探针在重启后断线，新注册的主 Webhook 和审计 Webhook 都必须收到新的 opened、escalated，最终均为 healthy、零失败、零排队。`/api/v1/alert-sinks` 必须分别暴露本地历史、主 Webhook 和审计 Webhook 三个 Sink。报告必须记录主 MQTT 至少七次、ROS 至少六次连接且两个必需实例最终均为 `open=true`，服务端无协议阶段错误；同时采集资源样本，并限制 RSS 增长不超过 32 MiB、句柄增长不超过 16。测试会单独记录预期断线、空闲超时和进程树清理产生的传输关闭，不把它们误报成报文错误。`protocol-service-smoke` 另外用阻塞连接模拟器证明恢复线程占用操作锁时，健康状态和诊断快照仍能在 50 ms 内返回。子进程 readiness 只由 `required=true` 的进程决定，可选协议和 Qt3D 架构演示进程的故障会保留在健康详情中，但不会误阻断协议网关验收。该测试仍是本机可控服务端，不证明生产实现、认证/TLS、跨主机网络或 24 小时长稳。

`alert-webhook-tls-integration` 为 Webhook 单独生成临时 CA、服务端和客户端证书，并启动要求客户端证书的本机 HTTPS 接收端。验收要求 Runtime 校验正确 CA 和 `localhost` 主机名、提交 mTLS 客户端证书、携带环境变量注入的 Authorization，并成功发送 opened/escalated；错误 CA 必须导致该 Sink 熔断、后续转换被延迟到半开窗口，但 Runtime 的 live/ready、本地历史和管理 API 继续可用；`/api/v1/alert-sinks` 必须显示 `circuit-open`、连续失败和熔断延迟次数；配置引用的鉴权环境变量缺失时必须在 HTTP 启动前 fail-fast；秘密值不得进入日志或 JSON 报告。这是本机密码学、熔断和失败隔离证据，不替代生产证书轮换、跨主机防火墙/代理、接收端去重与长时间故障恢复验收。

WebTunnel 的 `webtunnel-protocol-smoke` 覆盖线程安全的模拟状态、指标、回调异常隔离和非法 TLS 配置拒绝。`webtunnel-local-forwarder-integration` 启动真实本地 TCP 客户端、带 Authorization 和目标端口白名单的 WebSocket 隧道端及远端 TCP Echo，验证二进制数据双向穿透和幂等启停。`webtunnel-tls-integration` 动态生成临时证书，验证 wss/mTLS/Authorization，要求错误 CA、主机名不匹配和缺失客户端证书全部拒绝，秘密不得进入输出。生产代理策略、证书轮换、并发压力、公网链路、断线恢复和长稳仍需平台级验收。

Home WebUI 从 `/api/v1/protocols` 获取 MQTT、ROS Bridge、UDP 的实例身份、开关状态和最后错误，并从 `/api/v1/metrics` 聚合操作、错误和字节统计；静态资源使用内容哈希。`runtime-web-protocol-diagnostics` 同时验证 `/health/live`、`/health/ready`、`/home/` 的哈希脚本引用，跟随运行时 HTML 加载同源 JS/CSS，并启动一个必需的本机 UDP 实例和一个故意连接失败的可选 ROS 实例，确认 Runtime 保持 ready 且两种状态均可见。测试还通过 POST 依次关闭、重新打开 UDP，证明在线生命周期入口可恢复最终就绪状态。这仍不代表外部 broker、ROS graph 或跨主机 UDP 已验收。

## 通用通过条件

- `/health/live` 和 `/health/ready` 在稳定窗口及长稳采样中均为 HTTP 200。
- `/health/detail` 中所有必须组件为 `UP`；配置为启用的子进程必须全部运行。
- 所有 `required=true` 的设备必须为 `ready`；可选设备应显式配置 `required=false`，不能为了让发布门禁变绿而临时降低真实必需设备的等级。
- 所有 `required=true` 的协议实例必须打开；可选协议失败可以不阻断 readiness，但必须通过 `/api/v1/protocols` 暴露关闭状态和错误原因。
- 进程不得提前退出，测试结束后不得残留 Runtime 或子进程。
- RSS、句柄/文件描述符增长不超过项目为该平台批准的阈值；阈值、初值、峰值和末值必须同时记录。
- 日志中不得出现未解释的 crash、fatal、重复重启或持续连接失败。
- 交付包必须在不引用源码构建目录、开发机 Qt SDK或依赖缓存的环境中启动；SHA-256 清单必须针对隔离安装树生成，并严格拒绝缺失、变更或清单外注入的文件。

## 建议执行顺序

1. 保存 `pdr-profile.json`、版本号、提交 ID、配置文件哈希和机器信息。
2. 执行 `runtime-package-smoke`，确认干净安装包可启动。
3. 执行 30 分钟预长稳，调整仅与目标平台资源容量有关的阈值。
4. 执行 24 小时长稳；失败必须从头重跑，不能只从失败点续计。
5. 对 Embedded 和 Server 候选版本执行 72 小时长稳。
6. 在长稳期间注入网络断开、设备断开和受控子进程崩溃，记录恢复时间。
7. 完成升级/回滚轮次后，将报告、日志、清单和审计记录归档到同一版本目录。

## PetaLinux 现场命令基线

先确认目标安装路径和服务名，再执行；不要把下面的占位名直接用于生产设备。

```sh
cat share/PocoDDSRuntime/pdr-profile.json
df -h
df -ih
ulimit -n
systemctl status pdr-runtime
journalctl -u pdr-runtime --since "24 hours ago" --no-pager
curl -fsS http://127.0.0.1:9080/health/detail
```

板端运行长稳时使用安装包中的 `bin/soak_runner.py`，并设置 `--health-url`。如果目标镜像没有 Python，应由外部测试机定时探测健康接口，同时在板端通过 systemd/cgroup 采集资源；两份时间线必须使用同步时钟。

## 配置事务补充门禁

- 成功更新必须返回 `audited=true`，拒绝与自动回退也必须进入 JSONL 审计。
- 使用最新 committed 事务 ID 执行人工 rollback，必须返回 200、`action=rollback` 并恢复前一值。
- 回退后重新提交初始值，保证测试不污染下一次 Runtime 启动。
- `GET /api/v1/process-config` 必须暴露匹配的回退元数据和最近审计事务，但不得返回回退文件中的新旧值。
- 启用管理认证后，无令牌和错误令牌访问写接口必须分别返回 401；正确令牌才进入原有
  allowlist/参数校验。测试报告、响应和 Runtime 日志不得包含正确或错误令牌值。
- `GET /api/v1/process-config` 必须返回 `managementAuthenticationRequired=true`，Web
  必须把该后端事实展示为“管理写操作已认证”。
- 发布前 `pdr identity check` 必须返回 0，并证明至少一个文件型身份、权限检查完整且
  `insecureFileCount=0`；检查输出、日志和报告不得包含 Principal ID、Secret 路径或令牌值。
- 生产配置必须要求 `X-PDR-Request-Id`。缺失 ID 返回 428；同 ID、同请求重试返回 200、
  `idempotentReplay=true` 且不再次执行；同 ID 改变请求内容返回 409。Web 和 Runtime
  Smoke 客户端必须自动生成请求 ID，报告必须给出独立的幂等验收结果。
- 完成一次管理操作并重启 Runtime 后，同 ID、同请求必须从持久化账本返回
  `idempotentReplay=true`，目标不存在时也不得再次执行；同 ID 改变请求仍返回 409。账本不得
  出现原始请求体、配置值或任何测试令牌。崩溃时的执行中记录必须恢复为 `interrupted`，只允许
  人工核对状态后使用新 ID 重试；健康详情和 Web 必须暴露账本健康及待核对数量。
- 分别注入损坏的任务快照和幂等账本后，SystemMonitoring Bundle 与只读管理诊断 API 必须
  保持在线，`/health/ready` 必须降级为 503 并给出对应持久化故障码，API/Web 必须显示
  `recoveryRequired=true`。损坏账本时管理写操作、损坏任务快照时异步提交必须返回 503，且
  Runtime 不得静默覆盖损坏文件。
- v2 任务快照和幂等账本必须包含覆盖完整记录数组的 `contentSha256`；对保持 JSON 合法的
  内容进行篡改后，Runtime 必须检测摘要不匹配并进入故障隔离。无摘要 v1 文件必须能够读取
  并原子迁移为 v2，API/Web 必须显示 Schema 版本和完整性算法。
- 第二次及后续持久化前必须把已校验的当前版本原子保存为 `.previous`；API/Web 仅在该文件
  通过结构和摘要校验时返回 `previousAvailable=true`。损坏当前文件时不得自动加载上一版，
  且不得覆盖当前损坏证据；v1→v2 迁移后 `.previous` 必须保留原始 v1 文件。
- 离线恢复工具必须验证当前和 `.previous` 的 Schema、记录数组及 SHA-256；恢复必须要求显式
  停机确认和检查阶段的两个文件摘要。健康当前文件、失效上一版、摘要变化或恢复准备期间的
  并发变化必须拒绝替换。成功时须保留原件、原子替换、回读验证并追加 JSONL 审计记录。
- 一致性恢复点必须在 Runtime 停止时同时收集配置、任务快照、幂等账本、当前管理审计及存在
  的轮换审计。暂存集合通过逐文件摘要、持久化内容摘要和清单摘要验证后才能原子发布；独立
  复验必须拒绝篡改、缺失、多余、重复或越界路径，且安装包必须包含创建和复验命令。
- 整套恢复必须绑定经审批的清单摘要，要求显式停机确认，并在修改前原子发布所有目标的恢复前
  证据归档。所有来源须先暂存校验，目标在准备期间发生变化必须拒绝；替换或回读任一点失败须
  恢复全部目标并逐文件验证。不存在于恢复点的轮换审计须归档后移除，操作结果写入目标之外的
  JSONL 审计，且安装包必须包含还原命令。
- 启动后恢复验收必须关联成功的 restore 报告及 started/finished 外部审计，轮询 live、ready、
  detail 和管理任务接口，并要求任务及幂等持久化为 v2/SHA-256 健康状态。任何 Runtime 降级、
  证据不一致或未处置 interrupted 项必须输出 `DENIED`；逐项处置完整时才可输出 `APPROVED`。
  集成验收必须覆盖 v1 恢复点还原、真实 Runtime 迁移、批准判定及退出码 0 的完整优雅停机。
- 普通 Runtime smoke 必须先请求优雅停止并要求退出码 0，报告停止模式、耗时和退出码；超时
  强杀默认使测试失败。只有明确验证崩溃恢复、interrupted 转换或损坏原件保留的用例可使用
  `--force-shutdown`，报告必须标记 `forced-requested/expected=true`，其后续恢复 Runtime 仍须
  优雅退出。所有 Bundle Activator 禁止用 `Poco::SharedPtr` 管理 OSP 引用计数 Service。
- 配置一个仅含 `protocol.manage` 的 Principal：协议 restart 必须返回 200，使用同一令牌
  修改配置必须返回 403；报告必须给出独立的最小权限验收结果。正确、错误及受限令牌值
  均不得出现在 Runtime 日志、响应或测试报告中。
- 所有四类管理写操作必须产生统一 JSONL 审计，并覆盖 `succeeded`、`denied`、`failed`、
  `replayed`。事件必须包含 Principal、请求 ID、HTTP 状态和非负耗时；仅有
  `protocol.manage` 的 Principal 查询审计必须返回 403，具备 `audit.read` 的管理员查询
  必须返回 200。审计文件、报告和 Runtime 日志不得包含任何测试令牌值。
- 生命周期 API 的异步模式必须返回 202 和 `queued` 任务。验收须真实证明一个任务进入
  `succeeded`、一个因未在截止时间前启动进入 `timed-out`，以及一个延迟排队任务被取消
  后进入 `cancelled`；取消运行中或终态任务不得报告成功。任务列表须保留请求 ID、
  Principal、目标、时间戳和最终结果，并受 `task.read`/`task.cancel` 权限保护。
- 强制结束仍有延迟 `queued` 任务的 Runtime 后，第二个 Runtime 必须从同一原子快照加载
  该任务并转换为 `interrupted`，保留 `interruptedFromState=queued` 且声明
  `recoveryPolicy=verify-before-retry`；持久化健康状态必须为 true，禁止自动执行遗留任务。
- 运行中任务的取消请求必须返回 HTTP 202，并暴露 `cancellationRequested=true`、
  `phase=cancellation-requested` 和 `cancellationMode=cooperative`；执行器在下一个安全检查点
  必须进入 `cancelled`。执行期限超出时必须进入 `timed-out`，不得宣称已强制终止仍在执行的
  第三方调用。
- 两个 worker 同时收到相同 `operation:target` 的任务时，第二个任务必须进入
  `phase=waiting-resource`，暴露占用者 `blockingTaskId`，且不得在第一个任务释放前进入底层
  操作。锁等待必须计入执行期限并响应协作取消；不同资源不得被该互斥规则全局串行化。
- 队首存在未来 `notBeforeMilliseconds` 任务时，后提交的即时任务必须在它之前完成；调度器
  清单须报告 worker、queue、resource wait、capacity 和最长等待。队列饱和、任务快照失败或
  等待超过配置阈值时，`/health/detail` 必须出现 `management-tasks` 降级组件和稳定错误码。

## 尚不能由本机替代的验收

真实 PetaLinux 镜像、板卡电源循环、物理协议设备、生产证书/OIDC、现场网络和 24/72 小时持续时间均需要外部环境。仓库中的自动测试只提供统一入口和判定格式，不构成这些项目已经通过的声明。
这些结果统一使用 `pdr release external-template/external-approve/external-verify` 生成候选绑定证据；
固定类型为 `petalinux-target`、`physical-protocols`、`production-identity`、`site-network`、
`soak-24h` 和 `soak-72h`。每份批准报告必须连同工具归档的附件目录进入 release qualification。
正式资格还必须携带 Ed25519 分离签名，并通过固定 SHA-256 的批准者信任策略完成身份、授权范围、
有效期和吊销检查；内容摘要只能证明完整性，不能替代签名身份验证。
