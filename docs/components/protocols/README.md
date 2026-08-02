# 协议组件总览

`platform/protocols` 将外部协议封装为统一 C++ 接口。它们不会被 Fast DDS 取代：协议组件负责连接现场设备，DDS 负责把数据送往其他进程或机器。

| 组件 | 主要用途 | 平台边界 |
| --- | --- | --- |
| BtLE | 扫描、GATT | 当前为接口层 |
| CAN | SocketCAN、信号解码 | SocketCAN 依赖 Linux |
| Modbus | Modbus TCP 客户端 | TCP |
| MQTT | 发布订阅 | Paho MQTT C |
| ROS | rosbridge WebSocket | ROS Bridge |
| Serial | 字节流串口 | Win32/POSIX |
| UDP | UDP 收发 | 跨平台 Socket |
| WebTunnel | 服务描述接口 | 配合平台 WebTunnel |
| XBee | API 帧和 IO Sample | 串口 |

安装后的 CMake Package 会导出所有协议目标。优先独立链接实际使用的协议；聚合目标 `PocoDDS::Protocols` 用于确实需要完整协议集合的产品：

## 实现和接入规则

所有有生命周期的协议实现 `PocoDDS::Protocols::Protocol`，统一暴露 `name()`、`open()`、`close()` 和 `isOpen()`。协议类负责连接和原始报文，不负责把业务字段注册为 OSP 服务；设备层或业务 Bundle 完成该映射。

MQTT、ROS 和 UDP 返回统一的 `ProtocolDiagnostics` 快照，包括成功/失败操作、重连、收发消息与字节、超时、回调异常和最后错误。诊断读取是线程安全的，Runtime/Web 层不需要针对每个协议重新定义计数字段。

MQTT、ROS 和 UDP 同时实现 ABI 独立的 `FailureDiagnosticProtocol`。结构化 `Failure` 提供稳定
`PDR-PROTOCOL-*` 错误码、故障类别、是否可重试、是否仍活跃、发生时间和错误文本。成功操作只把
`active` 置为 false，保留最近故障用于事后分析；旧 `lastError` 字段继续同步维护。第三方协议无需
重新实现原接口，未迁移的自由文本错误由管理 API 标记为 `PDR-PROTOCOL-UNCLASSIFIED`。

```cmake
find_package(PocoDDSRuntime CONFIG REQUIRED COMPONENTS Modbus CAN)
target_link_libraries(my_bundle PRIVATE
    PocoDDS::Modbus
    PocoDDS::CAN)
# 完整集合需请求 COMPONENTS Protocols 后链接 PocoDDS::Protocols
```

组件化 Package 只加载所需传递依赖。例如基础 `SDK` 或 CAN 不要求 Paho；MQTT 会自动加载 Paho/OpenSSL，ROS 和 WebTunnel 会加载 NetSSL。未知组件在配置阶段失败。

协议库原则上不主动读取 `pdr-runtime.properties`。DeviceGateway 读取 `pdr.modbus.*`、`pdr.serial.*`、`pdr.can.*`、`pdr.xbee.*` 等设备配置；ProtocolGateway 读取 `pdr.mqtt.*`、`pdr.ros.*` 和 `pdr.udp.*` 多实例配置。两个 Bundle 都把参数传给协议/设备构造函数，协议库本身保持可独立复用。BtLE 和 WebTunnel 尚无统一运行时配置，需由使用者定义。

ProtocolGateway 将 MQTT、ROS Bridge、UDP 实例注册为 `pdr.protocol.*` OSP 服务。`/api/v1/protocols` 返回配置身份、打开状态和统一诊断；所有 `required=true` 实例必须打开，否则启动失败或 readiness 下降。可选实例打开失败不会阻断 Runtime，但会保留关闭状态和最后错误供 Web/API 排查。

## 测试

```powershell
ctest --test-dir build -C Release `
  -R "protocol|modbus|mqtt|ros|btle|xbee|webtunnel" `
  --output-on-failure
```

Smoke Test 主要验证编解码和本机软件接口；CAN、串口、BtLE、XBee 等仍需目标硬件测试。
