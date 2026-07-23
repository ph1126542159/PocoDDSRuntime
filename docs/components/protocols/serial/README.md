# Serial 协议组件

## 实现过程

`SerialChannel` 在 `Poco::Serial` 跨平台串口库上封装打开、关闭和字节收发，并实现统一 `Protocol` 生命周期。

## 用法

提供串口名、波特率等参数后打开通道。Windows 端口示例为 `COM18`，Linux 示例为 `/dev/ttyUSB0`。在设备网关中可通过 `pdr.serial.port` 和 `pdr.serial.baudRate` 启用。

验证时必须实际打开端口后再复位设备并采集启动输出；一次延迟的 0 字节读取不能证明 UART 无输出。
