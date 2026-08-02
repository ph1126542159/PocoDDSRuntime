# MQTT 协议组件

## 实现过程

`MqttClient` 基于 Eclipse Paho MQTT C，封装连接参数、QoS、消息、发布、订阅和回调，并以统一 `Protocol` 生命周期管理连接。连接、关闭、发布和订阅操作会串行化，避免与并发关闭竞争。

## 用法

构造 `MqttClient::Options`，填写 broker、客户端标识和认证信息，再连接、订阅或发布。QoS 必须按业务的丢失、重复和延迟容忍度选择。

Paho 依赖由依赖 superbuild 安装；Runtime 部署应通过 ProtocolGateway 的 `usernameEnvironment`、`passwordEnvironment`、`privateKeyPasswordEnvironment` 从进程环境读取凭据，不应写入源码、properties 文件或日志。直接使用协议库时，调用方负责从自身安全存储读取后填入 Options。

## Options 与调用

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| `serverUri` | 无 | 必填，如 `tcp://127.0.0.1:1883` |
| `clientId` | 无 | 必填，Broker 内应唯一 |
| `username/password` | 空 | Broker 认证 |
| `trustStore` | 空 | PEM CA 文件；空值使用系统默认信任库 |
| `keyStore` | 空 | mTLS 客户端证书链 PEM 文件 |
| `privateKey/privateKeyPassword` | 空 | mTLS 私钥及可选口令 |
| `enabledCipherSuites` | 空 | 可选 OpenSSL cipher list |
| `verifyServerCertificate` | `true` | 验证服务端证书链 |
| `verifyHostname` | `true` | 验证证书主机名 |
| `keepAliveSeconds` | `30` | Keep Alive |
| `cleanSession` | `true` | 清洁会话 |
| `connectTimeoutSeconds` | `10` | 建连超时 |

```cpp
using namespace PocoDDS::Protocols::MQTT;
MqttClient::Options o{"tcp://127.0.0.1:1883", "pdr-demo"};
MqttClient mqtt(o);
mqtt.setMessageHandler([](const Message& msg) { /* 入业务队列 */ });
mqtt.open();
mqtt.subscribe("factory/device/+/state", QoS::atLeastOnce);
mqtt.publish("factory/device/1/cmd", R"({"on":true})");
mqtt.close();
```

TLS 使用 `ssl://broker.example.com:8883`（WebSocket TLS 使用 `wss://`）。只做服务端认证时配置 `trustStore`；双向 TLS 再配置 `keyStore` 和 `privateKey`。TLS 材料不能与明文 URI 混用，私钥必须配套客户端证书。在 `security.profile=production` 下，服务端证书和主机名验证都不能关闭。用户名、密码和私钥口令不会进入协议服务属性、诊断响应或日志。

Paho 回调线程调用 Handler，Handler 内不要长时间阻塞。用户 Handler 抛出的异常会被隔离，不会跨越 Paho C 回调边界；消息和 topic 内存仍会正常释放。`diagnostics()` 返回公共 `ProtocolDiagnostics`，可读取成功/失败操作数、重连次数、收发消息与字节、超时、回调失败数和最近错误。

成功订阅会保存在客户端内。连接关闭或丢失后，调用方再次执行 `open()` 会重新连接并恢复这些订阅；明确 `unsubscribe()` 的 topic 不再恢复。这里提供的是确定性的显式恢复，不在后台无限自动重试，重试节奏应由上层生命周期/退避策略控制。

`mqtt-smoke` 使用本地最小 broker 验证 QoS 1 发布、回调异常隔离、关闭后重新连接、自动恢复订阅和第二次消息接收。`mqtt-tls-integration` 使用本机临时 CA、服务端和客户端证书验证 TLS/mTLS、错误 CA 拒绝、主机名拒绝及完整 Runtime 配置闭环。它们不替代真实 broker 的账号策略、证书轮换、持久会话、离线队列、集群切换和长时间网络抖动测试。

协议库可直接构造使用；Runtime 的 ProtocolGateway 同时支持 `pdr.mqtt.*` 多实例自动配置。
