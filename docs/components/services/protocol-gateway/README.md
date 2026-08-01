# ProtocolGateway 服务

ProtocolGateway 是 MQTT、ROS Bridge 和 UDP 的可选 Runtime 托管层。协议库仍可独立使用；只有配置了实例时，Bundle 才创建连接、执行统一 `open()`/`close()` 生命周期并注册 `pdr.protocol.<id>` OSP 服务。

## 配置

各协议族支持 `count` 加从零开始的编号项，实例 ID 在三个协议族之间必须全局唯一：

```properties
pdr.mqtt.count = 1
pdr.mqtt.0.id = factory-broker
pdr.mqtt.0.serverUri = tcp://127.0.0.1:1883
pdr.mqtt.0.clientId = pdr-runtime
pdr.mqtt.0.keepAliveSeconds = 30
pdr.mqtt.0.connectTimeoutSeconds = 10
pdr.mqtt.0.cleanSession = true
pdr.mqtt.0.usernameEnvironment = PDR_MQTT_USERNAME
pdr.mqtt.0.passwordEnvironment = PDR_MQTT_PASSWORD
# ssl:// 或 wss:// 时可配置以下 TLS 项
# pdr.mqtt.0.trustStore = certificates/ca.pem
# pdr.mqtt.0.keyStore = certificates/client.crt
# pdr.mqtt.0.privateKey = certificates/client.key
# pdr.mqtt.0.privateKeyPasswordEnvironment = PDR_MQTT_KEY_PASSWORD
# pdr.mqtt.0.enabledCipherSuites = HIGH:!aNULL:!MD5
pdr.mqtt.0.verifyServerCertificate = true
pdr.mqtt.0.verifyHostname = true
pdr.mqtt.0.required = false
pdr.mqtt.0.autoReconnect = true
pdr.mqtt.0.reconnectDelayMilliseconds = 1000
pdr.mqtt.0.reconnectMaximumDelayMilliseconds = 30000

pdr.ros.count = 1
pdr.ros.0.id = robot-bridge
pdr.ros.0.uri = ws://127.0.0.1:9090
pdr.ros.0.connectTimeoutSeconds = 10
pdr.ros.0.maximumMessageSize = 1048576
# wss:// 时可配置以下认证/TLS 项
# pdr.ros.0.authorizationEnvironment = PDR_ROS_AUTHORIZATION
# pdr.ros.0.trustStore = certificates/ca.pem
# pdr.ros.0.clientCertificate = certificates/client.crt
# pdr.ros.0.privateKey = certificates/client.key
pdr.ros.0.verifyServerCertificate = true
pdr.ros.0.verifyHostname = true
pdr.ros.0.required = false
pdr.ros.0.autoReconnect = true
pdr.ros.0.reconnectDelayMilliseconds = 1000
pdr.ros.0.reconnectMaximumDelayMilliseconds = 30000

pdr.udp.count = 1
pdr.udp.0.id = telemetry-datagram
pdr.udp.0.localHost = 0.0.0.0
pdr.udp.0.localPort = 9000
pdr.udp.0.remoteHost = 192.168.10.20
pdr.udp.0.remotePort = 9000
pdr.udp.0.required = true
pdr.udp.0.autoReconnect = true
pdr.udp.0.reconnectDelayMilliseconds = 1000
pdr.udp.0.reconnectMaximumDelayMilliseconds = 30000
```

默认配置的三个 `count` 均为零，不会主动连接外部系统。配置校验会在 Runtime 启动前拒绝重复 ID、空地址、非法端口、越界超时、明文 URI 携带 TLS 材料以及不完整的 mTLS 配置。生产安全 Profile 还会拒绝关闭证书链或主机名验证。

MQTT 的 `username`、`password`、`privateKeyPassword` 均可改用对应的环境变量配置；ROS 的 `authorization` 可改用 `authorizationEnvironment`。值是操作系统环境变量名，不是 `${...}` 属性表达式；直接值和环境变量来源不能同时配置。环境变量未设置或值为空时 Runtime 会在启动连接前 fail-fast，错误只包含配置键和变量名，不包含秘密内容。

## 必需与可选实例

- `required=true`：打开失败会撤销已经注册的协议并使 Bundle 启动失败；运行期间关闭也会使 `/health/ready` 返回非就绪。
- `required=false`：打开失败会记录警告并注册关闭实例，Runtime 继续启动，便于从诊断页面处理外部系统暂时不可用。

`autoReconnect=true` 时，网关会恢复“期望保持打开”但实际已断开的实例。失败后从 `reconnectDelayMilliseconds` 开始指数退避，最大不超过 `reconnectMaximumDelayMilliseconds`；成功后恢复初始延迟。人工执行 `close` 会把 `desiredOpen` 设为 false，因此后台不会马上重新打开；`open` 和 `restart` 会重新启用期望连接状态。

停止 Bundle 时按注册逆序注销服务，再关闭协议对象，避免 Registry 中留下悬空引用。

## 诊断入口

- `GET /api/v1/protocols`：每个实例的 ID、类型、Bundle、required、open、desiredOpen、autoReconnect、收发计数、错误计数与最后错误。
- `POST /api/v1/protocols`：提交 `{ "id": "实例 ID", "action": "open|close|restart" }`，在线执行串行化的协议生命周期操作；响应同时返回操作后的 `open` 和诊断快照。
- `GET /api/v1/metrics`：`pdr.protocol.operations`、`pdr.protocol.messages`、`pdr.protocol.bytes` 等聚合指标。
- `GET /health/detail`：`protocols` 组件显示总打开数与必需实例打开数。
- `/home/`：现场协议运行诊断卡片、实例表和重新连接操作。

生命周期操作由 `ProtocolService` 串行化，避免 Web 操作和 Bundle 停止同时访问同一协议对象。健康状态与诊断使用非阻塞快照：即使后台连接尝试正在等待网络超时，`/health/ready` 和读取 API 也不会排队等待该连接操作。对必需实例执行 `close` 会使 readiness 变为非就绪；一般运维应优先使用 `restart`。

本机 Runtime 自动测试分两层：`runtime-web-protocol-diagnostics` 覆盖必需 UDP 正常打开以及可选 ROS 连接失败；`runtime-protocol-gateway-integration` 启动真实 TCP MQTT 测试 Broker 和 WebSocket rosbridge 测试服务端。Broker 会在首次连接后主动断开，Runtime 必须自动恢复 MQTT，随后 MQTT 和 ROS 在同一 Runtime 进程内分别通过管理 API 重启五次；报告要求 MQTT 至少七次、ROS 至少六次连接且无服务端协议错误，并验证 RSS 与句柄增长阈值。`mqtt-tls-integration` 与 `ros-tls-integration` 分别覆盖完整 Runtime 的 TLS/mTLS、秘密环境变量、错误 CA 和主机名拒绝。生产 broker/rosbridge、证书轮换、完整 ROS graph、跨主机 UDP、防火墙和 24 小时长稳仍需对应环境验收。

连接外部环境后使用 `tools/protocol_acceptance.py` 对每个实例形成独立 JSON 报告。工具可强制协议类型、最终打开状态、双向消息/字节增量、断连重试增量、失败/超时上限和最大连续关闭样本；访问生产 API 时支持 HTTPS、自定义 CA、mTLS 和环境变量 Authorization。该报告需与外部服务端日志一起归档，不能单独替代对端证据。
