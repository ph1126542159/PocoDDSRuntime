# XBee 模拟量传感器

## 实现过程

`XBeeAnalogSensor` 从指定源地址和模拟通道提取 IO Sample，并支持 raw、mV 等转换方式，最终输出物理量、单位和设备状态。

## 用法

配置 `pdr.xbee.port`、`baudRate`、`escapedApiMode`、`sourceAddress`、`analogChannel`、`conversion`、`physicalQuantity` 和 `physicalUnit`，再启用 `pdr.xbee.enabled`。

先用原始 API 帧确认源地址和通道存在，再验证转换值。

## 接收与换算

后台线程从 `XBeePort` 读取帧，`IoSample::decode()` 后只接受匹配 `sourceAddress` 且包含指定 analogChannel 的样本。更新流程为 raw → conversion → value/snapshot 回调。

| conversion | 结果 |
| --- | --- |
| `raw` | 原始 ADC count |
| `millivolts` | 毫伏 |
| `temperature` | 摄氏温度换算 |
| `humidity` | 相对湿度换算 |

设备操作仅支持 `read`。

```properties
pdr.xbee.enabled = true
pdr.xbee.id = room-temperature
pdr.xbee.port = /dev/ttyUSB0
pdr.xbee.baudRate = 9600
pdr.xbee.escapedApiMode = false
pdr.xbee.sourceAddress = 0013A200405291AB
pdr.xbee.analogChannel = 0
pdr.xbee.conversion = temperature
pdr.xbee.physicalQuantity = temperature
pdr.xbee.physicalUnit = Cel
```

启动失败常见原因是串口被占用、AP 模式不一致或 sourceAddress 非法；无数据还应检查远端采样周期和通道 mask。
