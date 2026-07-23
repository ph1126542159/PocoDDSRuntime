# CAN 协议组件

## 实现过程

`SocketCanEndpoint` 在 Linux SocketCAN 上完成帧收发；`SignalCodec` 按 bit offset、bit length、大小端、有符号、factor 和 offset 解码工程值；`CanEndpoint` 定义统一帧接口。

## 用法

先在 Linux 配置并启用 `can0`，然后创建 `SocketCanEndpoint`。设备层通常通过 `CanSignalSensor` 使用本组件，并在 `pdr-runtime.properties` 中设置 `pdr.can.*`。

Windows 构建可编译公共逻辑，但 SocketCAN 实际收发必须在 Linux 目标验证。
