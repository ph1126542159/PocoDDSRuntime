# Fast DDS 通信组件

外部插件和独立进程应优先使用版本化、不透明的
`PocoDDS::FastDDSAbiV1`，不要把旧 `PDRFastDDS.dll` 的 C++ 对象布局当作稳定 ABI。完整的
生命周期、错误、回调所有权和迁移约束见
[`Fast DDS 稳定 ABI v1`](../../development/fastdds-abi-v1.md)。

## 职责

`platform/DDS` 提供统一消息信封、Topic 类型、发布订阅运行时、请求/响应服务端点和设备桥接，用于进程或主机之间通信。

## 实现过程

`Envelope` 保存关联 ID、操作、载荷和追踪上下文；`EnvelopeTopicDataType` 完成序列化；`Runtime` 管理 DomainParticipant、Reader 和 Writer；`ServiceEndpoint` 将请求放入工作队列并发布响应/事件；`DeviceBridge` 将设备状态和命令映射到 DDS Topic。

`PDRFastDDS` 必须作为进程内唯一的共享库部署。主程序与可热装卸 OSP Bundle
不得各自静态链接一份 Fast DDS，否则 Linux 下的进程级 participant/factory 状态会在
Bundle 卸载和进程退出阶段发生重复析构。机器人路径不加载此兼容库，而由 ROS 2/RMW
独立管理通信实现。

## 用法

创建 `Runtime(domainId, participantName)`；受控部署在进程启动前通过 `PDR_FASTDDS_PROFILE` 选择
部署文件，统一设置接口、初始 Peer、组播边界和 SHM。调用 `start()` 后再使用 `subscribe()` 和
`publish()`。服务 Bundle 通常直接创建 `ServiceEndpoint`，不单独管理网络策略。

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

多网卡或禁止组播的部署使用进程级策略，不让业务模块直接接触 Fast DDS QoS 类型：

```properties
profileVersion=1
interfaceWhitelist=192.168.10.20
initialPeers=192.168.10.21
avoidBuiltinMulticast=true
sharedMemory=true
maxInitialPeersRange=4
```

生产部署应在启动 Runtime 前执行：

```powershell
pdr-fastdds-profile-check --profile C:\deploy\fastdds-deployment.properties
```

需要防止预检后文件被替换时，固定同一内容摘要：

```powershell
$env:PDR_FASTDDS_PROFILE_SHA256 = (Get-FileHash -Algorithm SHA256 $env:PDR_FASTDDS_PROFILE).Hash.ToLowerInvariant()
pdr-fastdds-profile-check
```

Profile 以二进制方式单次读取，最大 64 KiB；解析和摘要比较使用同一份字节。摘要必须为 64 位小写
十六进制，只有路径而没有摘要仍保持原有兼容行为。

该命令复用 Runtime 的生产解析路径，但不会调用 `Runtime::start()`，因此不会创建 Participant 或打开
网络传输。返回码可直接作为 Launcher、CI、容器探针或滚动发布的配置门禁。

Peer 端口为 `0` 表示按 `maxInitialPeersRange` 展开标准 Domain/Participant 端口；显式端口只连接该
端口。关闭内建组播但没有配置 Peer 会在创建阶段失败。

`start()` 后才能发布或订阅；析构前应调用 `stop()`。同一 `Runtime` 可管理多个 Topic，Writer/Reader 会按需创建。

`Runtime::snapshots()` 返回当前进程内的只读诊断快照：Domain ID、Participant 名、启动状态、
Topic/Writer/Reader 数量、Topic 名称、`UDPv4`/`SHM` 组合和去标识化的部署摘要。诊断终端的 `dds participants`、
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

运行时、所有服务 Bundle 和外部客户端必须使用相同 Domain ID。`PDR_FASTDDS_PROFILE` 指向的版本化
部署文件是发现/传输边界；业务 Bundle 不应包含 Fast DDS 头文件或直接修改 `Runtime.cpp`。不同
Runtime 子进程可以选择不同文件，同一进程内所有 Participant 共享同一部署策略。端点 QoS 目前仍
使用默认值，尚未提供 XML QoS 文件入口。

## 验证命令

```powershell
ctest --test-dir build -C Release -R "fastdds|service-integration" `
  --output-on-failure
```

Smoke Test 证明同一 OS 进程内独立 Participant 的 Topic 路径，不证明独立进程。跨进程/跨机器验收
还需检查组播/单播发现、防火墙和实际网卡。
