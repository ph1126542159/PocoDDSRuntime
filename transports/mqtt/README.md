# MQTT Transport Adapter

`PocoDDS::MQTTTransport` 把稳定的 `RuntimeCore::IMessageTransport` 契约映射到 MQTT，业务
Module/Service 不需要包含 Paho MQTT 或协议层头文件。Adapter 使用统一的 `PDRM/1` 二进制帧，
完整携带 Topic、消息类型、Schema、Header、Payload、Trace/因果上下文和剩余 Deadline。

## 适用的软件模型

- **桌面单体 / `desktop-lite`**：默认使用 `inproc`；只有需要接入远程设备、云端 Broker 或跨主机
  消息时才启用 MQTT，不应仅为模块解耦引入 Broker。
- **桌面多进程 / `desktop-distributed`**：同机高频控制走 `ipc`，MQTT 用于跨主机遥测、配置和
  非实时命令；不要用 MQTT 代替本机进程生命周期管理。
- **边缘网关、后台服务和大型分布式应用**：适合设备上云、站点间事件和弱连接场景；强一致事务
  仍应使用数据库/事务消息方案，低延迟大吞吐数据面应评估 Fast DDS 等专用传输。
- **机器人 / 混合模型**：MQTT 只用于管理面、遥测或云连接。机器人内部强类型 Topic、发现和
  实时 QoS 应使用 ROS 2/Fast DDS Adapter；WebUI 不应直接依赖任一中间件。

## CMake 使用

安装运行时后按组件查找：

```cmake
find_package(PocoDDSRuntime CONFIG REQUIRED COMPONENTS MQTTTransport)
target_link_libraries(my_service PRIVATE PocoDDS::MQTTTransport)
```

直接构造：

```cpp
PocoDDS::MqttTransport::MqttTransportOptions options;
options.serverUri = "ssl://broker.example.com:8883";
options.clientId = "station-a-runtime";
options.trustStore = "certs/ca.pem";
options.topicPrefix = "factory/station-a/";

PocoDDS::MqttTransport::MqttTransport transport(std::move(options));
auto started = transport.start();
```

也可通过 `registerMqttTransport()` 注册到 `TransportRegistry`。工厂配置键包括：

| 配置键 | 说明 |
|---|---|
| `serverUri`, `clientId` | 必填；Broker URI 和稳定且唯一的客户端 ID |
| `topicPrefix` | 物理 Topic 前缀，默认 `pdr/` |
| `username`, `password` | Broker 凭据；生产环境应由 Secret Provider 注入 |
| `trustStore`, `keyStore`, `privateKey`, `privateKeyPassword` | TLS/mTLS 文件配置 |
| `enabledCipherSuites` | TLS 密码套件约束 |
| `verifyServerCertificate`, `verifyHostname` | 默认 `true`，只接受 `true/false/1/0` |
| `cleanSession` | 默认 `true`；是否创建干净 MQTT Session |
| `keepAliveSeconds`, `connectTimeoutSeconds` | 连接存活与超时 |
| `maximumFrameBytes` | `PDRM/1` 最大帧尺寸，默认 16 MiB |

## 语义边界

- `Delivery::reliable` 映射 MQTT QoS 1，`bestEffort` 映射 QoS 0；QoS 1 表示至少一次，消费者必须
  处理重复消息。
- `TopicSpec::durable=true` 映射 MQTT retained，只保存每个 Topic 的最后一条值，不等价于历史
  消息持久化、事务日志或端到端 exactly-once。
- 发布会先投递给本进程订阅者，再发往 Broker；Adapter 写入内部 origin Header 并抑制 Broker
  回环，业务 Handler 看不到该内部 Header。
- Broker 收到的帧必须通过 `PDRM/1` 尺寸、版本、类型、Schema 和 Topic 一致性检查，否则丢弃。
- 当前 Adapter 负责连接和显式启停；生产项目还应在 Host 层增加退避重连、健康状态、凭据轮换与
  断线队列策略，不能把无限重试藏在业务调用内。

## Paho 依赖安全契约

MQTT Adapter 依赖受治理的 Eclipse Paho MQTT C 构建。Paho 1.3.15 的同步客户端在消息回调尚未
完成内部队列清理时并发执行 `disconnect`，可能让 `cleanSession` 与回调重复释放同一消息。依赖
Superbuild 会通过
`cmake/patches/paho-mqtt-c-v1.3.15-message-callback-teardown.patch` 在回调前转移队列项所有权，
并在安装头文件中写入 `PDR_PAHO_MQTTCLIENT_CALLBACK_TEARDOWN_SAFE` 能力标记。

主工程配置会拒绝没有该能力标记的外部 Paho 包，避免开发机、CI 和发布机静默链接到行为不同的
系统库。升级 Paho 时必须重新审查补丁、更新能力标记，并通过 `mqtt-transport-peer-recovery` 的
`callbackTeardown=1` 断言及重复压力测试后，才能替换受治理版本。

## 验收

`mqtt-transport-smoke` 会启动真实 TCP Mini Broker，验证 CONNECT、SUBSCRIBE、客户端发布、QoS 1
PUBACK、Broker 主动下发 `PDRM/1`、UNSUBSCRIBE、DISCONNECT，并执行 7 项 Transport Conformance
检查。`mqtt-transport-peer-recovery` 会在 Broker 异常断开后恢复订阅与完整消息，并主动让
`stop()` 与仍在执行的消息回调重叠，验证回调销毁边界。TLS 证书校验由协议层
`mqtt-tls-integration` 单独覆盖。
