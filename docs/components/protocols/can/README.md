# CAN 协议组件

## 实现过程

`SocketCanEndpoint` 在 Linux SocketCAN 上完成帧收发；`SignalCodec` 按 bit offset、bit length、大小端、有符号、factor 和 offset 解码工程值；`CanEndpoint` 定义统一帧接口。

## 用法

先在 Linux 配置并启用 `can0`，然后创建 `SocketCanEndpoint`。设备层通常通过 `CanSignalSensor` 使用本组件，并在 `pdr-runtime.properties` 中设置 `pdr.can.*`。

Windows 构建可编译公共逻辑和 loopback 测试端点，但 SocketCAN 实际收发必须在 Linux 目标验证。

## 实现细节

`CanFrame` 保存帧 ID、标准/扩展/远程/error 标志和最多 64 字节 CAN FD 数据。`SocketCanEndpoint` 打开 PF_CAN RAW socket 并绑定接口，启用 CAN FD，并订阅 controller、protocol、bus-off 和 restarted 错误帧。经典 CAN 帧使用 `CAN_MTU` 写入，超过 8 字节时才使用 `CANFD_MTU`，避免把经典帧错误地一律按 CAN FD 发送。`SignalCodec` 的换算为：

```text
engineeringValue = decodedRaw × factor + offset
```

## C++ 用法

```cpp
using namespace PocoDDS::Protocols::CAN;
SocketCanEndpoint can("can0");
can.open();
CanFrame frame = can.receive(Poco::Timespan(1, 0));
double value = SignalCodec::decodeScaled(
    frame, 0, 16, BitOrder::littleEndian, false, 0.1, -40.0);
can.close();
```

## Linux 配置

```bash
sudo ip link set can0 down
sudo ip link set can0 type can bitrate 500000
sudo ip link set can0 up
candump can0
```

协议库不读取 properties；`pdr.can.*` 由 DeviceGateway 转换为 `CanSignalSensor::Options`。必须用已知帧验证 frame ID、大小端、符号位和缩放。
