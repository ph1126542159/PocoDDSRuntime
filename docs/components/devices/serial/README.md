# 串口设备

## 实现过程

`SerialPortDevice` 将 `SerialChannel` 适配为设备模型，对外提供串口设备状态和字节流操作。

## 用法

```properties
pdr.serial.enabled = true
pdr.serial.port = COM18
pdr.serial.baudRate = 115200
```

启动运行时后检查端口打开日志和设备状态。端口不能同时被多个进程独占打开；调试工具使用前应先停用网关中的串口设备。

## 实现与操作

`start()` 打开 `SerialChannel` 并启动后台读线程；收到字节后更新最后 payload、sequence 和快照。`execute("write", payload)` 把 payload 的原始字节写入串口。

```cpp
SerialPortDevice device("serial-1", "COM18", 115200);
device.start();
device.execute("write", std::string("\x01\x03\x00\x00", 4));
auto snapshot = device.snapshot();
device.stop();
```

这里的 payload 不是十六进制文本：字符串 `"01 03"` 会实际发送 ASCII 字符。若通过 JSON/DDS 控制二进制协议，应先定义 base64 或 hex 编码层，当前实现未自动解码。

网关配置只支持一个 `serial-1`。需要多个端口或校验位配置时，应把 properties 扩展为编号列表。
