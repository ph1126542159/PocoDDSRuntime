# Fast DDS Transport Adapter

`PocoDDS::FastDDSTransport` 将通用 `RuntimeCore::IMessageTransport` 映射到现有 Fast DDS
`Envelope` 数据面。业务代码只依赖 RuntimeCore；Adapter 将 `PDRM/1` 以 Base64 封装在 Envelope
Payload 中，并通过 `TransportRegistry` 以 `fastdds` ID 创建。

## 什么时候使用

- 大型桌面/边缘应用需要跨主机低延迟发布订阅、自动发现时，可选 Fast DDS；普通单进程桌面程序
  仍使用 `inproc`，同机多进程优先 `ipc`。
- 机器人管理面可复用本 Adapter，但机器人强类型接口、Action/Service、生命周期与安全控制应使用
  `robotics/ros2_ws` 中的原生 ROS 2 包，不能把通用 Envelope 当作完整 ROS 2 模型。
- WebUI 继续通过 Host 的 HTTP/WebSocket 管理面访问，不直接链接 Fast DDS。

## 配置

```cmake
find_package(PocoDDSRuntime CONFIG REQUIRED COMPONENTS FastDDSTransport)
target_link_libraries(my_service PRIVATE PocoDDS::FastDDSTransport)
```

Registry 工厂支持 `domainId`（0..232）、`participantName`、`topicPrefix` 和
`maximumFrameBytes`（默认 180 KiB）。不同项目必须显式规划 Domain ID 与 Topic Prefix，避免同一
网络中的发现域和业务命名冲突。当前 180 KiB 上限为现有 256 KiB Envelope 序列化边界保留了
Base64 和 CDR 开销；大数据应走对象存储、共享内存或分片数据面，不应盲目提高此值。

## 当前语义边界

- 每个逻辑 Topic 映射为一个 Fast DDS Topic；消息体统一为 `PDRM/1`。
- Adapter 抑制自身 DDS 回环，但先执行本进程投递，因此本地和远端订阅具有同一业务契约。
- 现有底层 `PocoDDS::FastDDS::Runtime` 使用 Fast DDS 默认 QoS；因此本 Adapter 当前不宣称
  durable，也不把 `TopicSpec::durable` 映射为持久化历史。需要可靠性、History、Deadline、Liveliness
  或共享内存传输的项目，应先扩展显式 QoS Profile，再进行项目级性能与故障验收。
- 底层 Runtime 暂不支持物理 DataReader 单独删除；逻辑取消订阅会立即移除业务 Handler，物理
  Reader 在本次 Runtime 生命周期内保留，并在 `stop()` 时统一回收。

`fastdds-transport-smoke` 使用两个独立 DomainParticipant 验证真实跨 Participant 下发、二进制
Payload、回环抑制、注册表和 7 项 Transport Conformance。它是本机网络闭环，不等于跨设备、丢包、
多网卡或实时性验收。
