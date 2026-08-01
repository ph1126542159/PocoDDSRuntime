# 串口设备

## 实现过程

`SerialPortDevice` 将 `SerialChannel` 适配为设备模型，对外提供串口设备状态和字节流操作。

## 用法

```properties
pdr.serial.enabled = true
pdr.serial.port = COM18
pdr.serial.baudRate = 115200
pdr.serial.parameters = 8N1
pdr.serial.flowControl = none
pdr.serial.reconnectEnabled = true
pdr.serial.reconnectDelayMilliseconds = 250
pdr.serial.readTimeoutMilliseconds = 250
```

启动运行时后检查端口打开日志和设备状态。端口不能同时被多个进程独占打开；调试工具使用前应先停用网关中的串口设备。

## 实现与操作

`start()` 打开 `SerialChannel` 并启动后台读线程；收到字节后更新最后 payload、sequence、诊断计数和快照。`execute("write", payload)` 把 payload 的原始字节写入串口。后台读取异常会进入 `fault`，不会再让未捕获异常终止 Runtime；启用恢复策略时会关闭失效句柄、按固定间隔重新打开，并在恢复后回到 `ready`。

```cpp
SerialPortDevice device("serial-1", "COM18", 115200);
device.start();
device.execute("write", std::string("\x01\x03\x00\x00", 4));
auto snapshot = device.snapshot();
device.stop();
```

这里的 payload 不是十六进制文本：字符串 `"01 03"` 会实际发送 ASCII 字符。若通过 JSON/DDS 控制二进制协议，应先定义 base64 或 hex 编码层，当前实现未自动解码。

多个串口使用编号配置：

```properties
pdr.serial.count = 2
pdr.serial.0.id = fixture-control
pdr.serial.0.port = COM18
pdr.serial.0.baudRate = 115200
pdr.serial.0.parameters = 8N1
pdr.serial.0.flowControl = rtscts
pdr.serial.1.id = fixture-meter
pdr.serial.1.port = COM19
pdr.serial.1.baudRate = 9600
```

旧的 `pdr.serial.enabled/port/baudRate` 仍作为单实例兼容入口。`parameters` 使用 POCO 串口格式，例如 `8N1` 或 `7E1`；`flowControl` 支持 `none` 和 `rtscts`。

串口写操作不会自动重放。写调用在传输过程中失败或只写入部分字节时，设备进入 `fault` 并抛出错误；后台线程可以重连端口，但是否补发必须由业务层根据设备响应和幂等规则决定。

`SerialPortDevice` 实现 `DiagnosticDevice`，`/api/v1/devices` 可查看成功/失败操作数、连续失败、重连次数和最后错误。`serial-device-recovery` 使用可注入串口传输验证读线程断线不会导致进程终止、恢复后重新接收数据，并验证失败写入只执行一次。

开发和 CI 可以显式配置 `transport=loopback`，不需要虚拟 COM 驱动即可验证完整 Bundle、设备生命周期和 API 诊断路径。默认值是 `port`；loopback 只证明软件闭环，不能作为真实串口、电平、波特率、流控或线缆的 HIL 证据。

```properties
pdr.serial.count = 1
pdr.serial.0.id = serial-reference
pdr.serial.0.transport = loopback
```
