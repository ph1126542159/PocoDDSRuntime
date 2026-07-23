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

各协议独立链接；聚合目标 `PocoDDS::Protocols` 仅用于表达协议层依赖。

## 实现和接入规则

所有有生命周期的协议实现 `PocoDDS::Protocols::Protocol`，统一暴露 `name()`、`open()`、`close()` 和 `isOpen()`。协议类负责连接和原始报文，不负责把业务字段注册为 OSP 服务；设备层或业务 Bundle 完成该映射。

```cmake
target_link_libraries(my_bundle PRIVATE
    PocoDDS::Modbus
    PocoDDS::CAN)
```

协议库原则上不主动读取 `pdr-runtime.properties`。DeviceGateway 读取 `pdr.modbus.*`、`pdr.serial.*`、`pdr.can.*`、`pdr.xbee.*` 等配置，再把参数传给协议/设备构造函数。MQTT、ROS、UDP、BtLE 和 WebTunnel 尚无统一运行时配置，需由使用者定义。

## 测试

```powershell
ctest --test-dir build -C Release `
  -R "protocol|modbus|mqtt|ros|btle|xbee|webtunnel" `
  --output-on-failure
```

Smoke Test 主要验证编解码和本机软件接口；CAN、串口、BtLE、XBee 等仍需目标硬件测试。
