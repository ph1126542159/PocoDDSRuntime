# MQTT 协议组件

## 实现过程

`MqttClient` 基于 Eclipse Paho MQTT C，封装连接参数、QoS、消息、发布、订阅和回调，并以统一 `Protocol` 生命周期管理连接。

## 用法

构造 `MqttClient::Options`，填写 broker、客户端标识和认证信息，再连接、订阅或发布。QoS 必须按业务的丢失、重复和延迟容忍度选择。

Paho 依赖由依赖 superbuild 安装；凭据应从部署配置或安全存储加载，不应写入源码或日志。

## Options 与调用

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| `serverUri` | 无 | 必填，如 `tcp://127.0.0.1:1883` |
| `clientId` | 无 | 必填，Broker 内应唯一 |
| `username/password` | 空 | Broker 认证 |
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

Paho 回调线程调用 Handler，Handler 内不要长时间阻塞。当前没有 `pdr.mqtt.*` 自动配置，调用方需在自己的 Bundle 中读取配置并构造客户端。
