# CAN 信号传感器

## 实现过程

`CanSignalSensor` 监听指定 CAN frame ID，调用 `SignalCodec` 从位域解码数值，并应用 factor 与 offset 生成带物理量和单位的传感器快照。

## 用法

在配置中设置 `pdr.can.transport`、`interface`、`frameId`、`extended`、`bitOffset`、`bitLength`、`bitOrder`、`signed`、`factor`、`offset`、`physicalQuantity` 和 `physicalUnit`，再启用 `pdr.can.enabled`。

上线前用已知 CAN 帧验证大小端、符号扩展和比例换算。

## 线程与数据流

`start()` 打开 `CanEndpoint` 并启动接收线程。线程同时过滤标准/扩展标志和 frame ID，匹配后调用 `SignalCodec::decodeScaled()`，更新 value、sequence、诊断和快照。接收异常或 CAN error frame 会进入 `fault`、关闭端点并按策略重建；恢复连接后保持 `offline`，直到收到新的匹配帧才回到 `ready`。业务回调异常会被隔离，不会杀死接收线程。

`staleAfterMilliseconds` 是数据新鲜度边界：曾经 ready 的信号超过该时间没有新匹配帧会进入 `offline`，并记录一次 `CAN signal stale`。这避免总线静默后页面永久显示旧值正常。

支持的设备操作只有：

```text
operation = read
payload   = 空
result    = 当前快照 payload
```

## 完整配置

```properties
pdr.can.enabled = true
pdr.can.transport = socketcan
pdr.can.id = coolant-temperature
pdr.can.interface = can0
pdr.can.frameId = 0x123
pdr.can.extended = false
pdr.can.bitOffset = 0
pdr.can.bitLength = 16
pdr.can.bitOrder = little
pdr.can.signed = false
pdr.can.factor = 0.1
pdr.can.offset = -40
pdr.can.physicalQuantity = temperature
pdr.can.physicalUnit = Cel
pdr.can.reconnectEnabled = true
pdr.can.reconnectDelayMilliseconds = 250
pdr.can.receiveTimeoutMilliseconds = 250
pdr.can.staleAfterMilliseconds = 2000
```

`frameId` 支持十进制和 `0x`，并严格限制在 29 位 CAN 标识符范围内。`bitOrder` 只接受 `little` 或 `big`。位偏移支持 CAN FD 的 64 字节载荷，但单个解码信号最多 64 位，且 `bitOffset + bitLength` 不能超过 512。

开发和 CI 可显式使用 `transport=loopback` 验证设备状态机、错误帧、陈旧数据和 Bundle/API 路径；生产安全门禁禁止该传输。loopback 不构成 Linux SocketCAN、收发器、终端电阻、bitrate 或 bus-off 恢复的 HIL 证据。
