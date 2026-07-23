# MQTT 协议组件

## 实现过程

`MqttClient` 基于 Eclipse Paho MQTT C，封装连接参数、QoS、消息、发布、订阅和回调，并以统一 `Protocol` 生命周期管理连接。

## 用法

构造 `MqttClient::Options`，填写 broker、客户端标识和认证信息，再连接、订阅或发布。QoS 必须按业务的丢失、重复和延迟容忍度选择。

Paho 依赖由依赖 superbuild 安装；凭据应从部署配置或安全存储加载，不应写入源码或日志。
