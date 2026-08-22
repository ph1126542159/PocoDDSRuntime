# Fast DDS 通信组件

## 职责

`platform/DDS` 提供统一消息信封、Topic 类型、发布订阅运行时、请求/响应服务端点和设备桥接，用于进程或主机之间通信。

## 实现过程

`Envelope` 保存关联 ID、操作、载荷和追踪上下文；`EnvelopeTopicDataType` 完成序列化；`Runtime` 管理 DomainParticipant、Reader 和 Writer；`ServiceEndpoint` 将请求放入工作队列并发布响应/事件；`DeviceBridge` 将设备状态和命令映射到 DDS Topic。

`PDRFastDDS` 必须作为进程内唯一的共享库部署。主程序与可热装卸 OSP Bundle
不得各自静态链接一份 Fast DDS，否则 Linux 下的进程级 participant/factory 状态会在
Bundle 卸载和进程退出阶段发生重复析构。机器人路径不加载此兼容库，而由 ROS 2/RMW
独立管理通信实现。

## 用法

创建 `Runtime(domainId, participantName)`，调用 `start()`，再使用 `subscribe()` 和 `publish()`。服务 Bundle 通常直接创建 `ServiceEndpoint`，传入 request、response 和 event Topic 及处理函数。

设备网关 Topic 为 `pdr.device.state`、`pdr.device.request`、`pdr.device.response`。参与者必须使用相同 Domain ID，并确保网络发现和防火墙允许 Fast DDS 流量。

## 验证

构建后运行 `pdr-fastdds-device-smoke` 和 `pdr-service-integration-smoke`。

## 数据模型

`Envelope` 是所有 Topic 共用的数据载体，核心字段包括关联 ID、操作名、JSON/文本载荷和 W3C trace context。`EnvelopeTopicDataType` 实现 Fast DDS 序列化，使不同服务不需要各自生成 IDL 类型。

请求/响应约定：

```text
客户端发布 request Envelope
        │ correlationId 保持不变
        ▼
ServiceEndpoint 工作线程调用 Handler
        │
        ├─ 成功：发布 response Envelope
        └─ 异常：发布带错误信息的 response Envelope
```

## Runtime 用法

```cpp
#include <PocoDDS/DDS/Runtime.h>

PocoDDS::FastDDS::Runtime runtime(0, "example-client");
runtime.start();
runtime.subscribe("demo.response", [](const auto& envelope) {
    // 根据 correlationId 匹配请求
});
runtime.preparePublisher("demo.request");
runtime.publish("demo.request", requestEnvelope);
runtime.stop();
```

`start()` 后才能发布或订阅；析构前应调用 `stop()`。同一 `Runtime` 可管理多个 Topic，Writer/Reader 会按需创建。

`Runtime::snapshots()` 返回当前进程内的只读诊断快照：Domain ID、Participant 名、启动状态、
Topic/Writer/Reader 数量、Topic 名称、传输和 QoS 摘要。诊断终端的 `dds participants`、
`dds discovery`、`dds qos` 和 `dds check` 使用该接口，并结合 `pdr.dds.*` 指标与失败 Trace。
该接口不跨进程读取对象；DDS 位于托管子进程时，终端会明确要求组合 `agent`、`trace` 和
`logs --follow`，避免把“无法观测”误判为“没有 Participant”。

## ServiceEndpoint 用法

```cpp
PocoDDS::FastDDS::ServiceEndpoint endpoint(
    domainId,
    "demo-service",
    "demo.request",
    "demo.response",
    "demo.event");

endpoint.start([](const PocoDDS::FastDDS::Envelope& request) {
    PocoDDS::FastDDS::Envelope response;
    response.payload = handle(request.operation, request.payload);
    return response;
});

endpoint.publishEvent("changed", R"({"value":42})");
```

停止 Bundle 时先 `endpoint.stop()`，再注销 OSP 服务，防止 DDS 工作线程访问已销毁对象。

## 配置与网络

```properties
pdr.fastdds.domainId = 0
```

运行时、所有服务 Bundle 和外部客户端必须使用相同 Domain ID。仓库没有暴露 XML QoS 文件配置项；需要自定义发现、传输或 QoS 时，应在 `Runtime.cpp` 中增加明确配置入口，不能假设环境变量已生效。

## 验证命令

```powershell
ctest --test-dir build -C Release -R "fastdds|service-integration" `
  --output-on-failure
```

Smoke Test 证明本机进程间 Topic 路径；跨机器验收还需检查组播/单播发现、防火墙和实际网卡。
