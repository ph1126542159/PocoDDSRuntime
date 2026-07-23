# CAN 信号传感器

## 实现过程

`CanSignalSensor` 监听指定 CAN frame ID，调用 `SignalCodec` 从位域解码数值，并应用 factor 与 offset 生成带物理量和单位的传感器快照。

## 用法

在配置中设置 `pdr.can.interface`、`frameId`、`bitOffset`、`bitLength`、`bitOrder`、`signed`、`factor`、`offset`、`physicalQuantity` 和 `physicalUnit`，再启用 `pdr.can.enabled`。

上线前用已知 CAN 帧验证大小端、符号扩展和比例换算。
