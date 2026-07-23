# CAN 信号传感器

## 实现过程

`CanSignalSensor` 监听指定 CAN frame ID，调用 `SignalCodec` 从位域解码数值，并应用 factor 与 offset 生成带物理量和单位的传感器快照。

## 用法

在配置中设置 `pdr.can.interface`、`frameId`、`bitOffset`、`bitLength`、`bitOrder`、`signed`、`factor`、`offset`、`physicalQuantity` 和 `physicalUnit`，再启用 `pdr.can.enabled`。

上线前用已知 CAN 帧验证大小端、符号扩展和比例换算。

## 线程与数据流

`start()` 创建 `SocketCanEndpoint` 并启动接收线程。线程过滤 `frame.id == options.frameId`，匹配后调用 `SignalCodec::decodeScaled()`，更新 value、sequence 和快照，再依次通知 SnapshotHandler 与 ValueHandler。`stop()` 先清运行标志、关闭 socket 解除阻塞，再 join 线程。

支持的设备操作只有：

```text
operation = read
payload   = 空
result    = 当前快照 payload
```

## 完整配置

```properties
pdr.can.enabled = true
pdr.can.id = coolant-temperature
pdr.can.interface = can0
pdr.can.frameId = 0x123
pdr.can.bitOffset = 0
pdr.can.bitLength = 16
pdr.can.bitOrder = little
pdr.can.signed = false
pdr.can.factor = 0.1
pdr.can.offset = -40
pdr.can.physicalQuantity = temperature
pdr.can.physicalUnit = Cel
```

`frameId` 使用 `std::stoul(..., base=0)`，因此支持十进制和 `0x`。`bitOrder` 只有精确值 `big` 选择大端，其他值均落到 little；部署前应校验拼写。
