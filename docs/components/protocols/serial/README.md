# Serial 协议组件

## 实现过程

`SerialChannel` 在 `Poco::Serial` 跨平台串口库上封装打开、关闭和字节收发，并实现统一 `Protocol` 生命周期。

## 用法

提供串口名、波特率等参数后打开通道。Windows 端口示例为 `COM18`，Linux 示例为 `/dev/ttyUSB0`。在设备网关中可通过 `pdr.serial.port` 和 `pdr.serial.baudRate` 启用。

验证时必须实际打开端口后再复位设备并采集启动输出；一次延迟的 0 字节读取不能证明 UART 无输出。

## C++ 用法

```cpp
using PocoDDS::Protocols::Serial::SerialChannel;
SerialChannel channel("COM18", 115200);
channel.open();
const std::uint8_t request[] = {0x01, 0x03, 0, 0, 0, 2};
channel.write(request, sizeof(request));
auto response = channel.read(9, Poco::Timespan(1, 0));
channel.close();
```

上层协议必须自行处理帧头、长度、粘包、半包和校验。`port()` 可访问底层 `Poco::Serial::SerialPort`。

## 配置边界

DeviceGateway 读取 `enabled`、`port`、`baudRate`、`parameters`、`flowControl`、`reconnectEnabled`、`reconnectDelayMilliseconds` 和 `readTimeoutMilliseconds`。`parameters` 支持例如 8N1、7E1 的格式，硬件流控使用 `flowControl=rtscts`。端口不能同时被其他程序独占打开。
