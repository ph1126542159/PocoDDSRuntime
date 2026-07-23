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
