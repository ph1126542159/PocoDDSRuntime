# Fast DDS 通信组件

## 职责

`platform/DDS` 提供统一消息信封、Topic 类型、发布订阅运行时、请求/响应服务端点和设备桥接，用于进程或主机之间通信。

## 实现过程

`Envelope` 保存关联 ID、操作、载荷和追踪上下文；`EnvelopeTopicDataType` 完成序列化；`Runtime` 管理 DomainParticipant、Reader 和 Writer；`ServiceEndpoint` 将请求放入工作队列并发布响应/事件；`DeviceBridge` 将设备状态和命令映射到 DDS Topic。

## 用法

创建 `Runtime(domainId, participantName)`，调用 `start()`，再使用 `subscribe()` 和 `publish()`。服务 Bundle 通常直接创建 `ServiceEndpoint`，传入 request、response 和 event Topic 及处理函数。

设备网关 Topic 为 `pdr.device.state`、`pdr.device.request`、`pdr.device.response`。参与者必须使用相同 Domain ID，并确保网络发现和防火墙允许 Fast DDS 流量。

## 验证

构建后运行 `pdr-fastdds-device-smoke` 和 `pdr-service-integration-smoke`。
