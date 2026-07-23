# XBee 模拟量传感器

## 实现过程

`XBeeAnalogSensor` 从指定源地址和模拟通道提取 IO Sample，并支持 raw、mV 等转换方式，最终输出物理量、单位和设备状态。

## 用法

配置 `pdr.xbee.port`、`baudRate`、`escapedApiMode`、`sourceAddress`、`analogChannel`、`conversion`、`physicalQuantity` 和 `physicalUnit`，再启用 `pdr.xbee.enabled`。

先用原始 API 帧确认源地址和通道存在，再验证转换值。
