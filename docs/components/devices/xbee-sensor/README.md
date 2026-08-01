# XBee 模拟量传感器

## 实现过程

`XBeeAnalogSensor` 从指定源地址和模拟通道提取 IO Sample，并支持 raw、mV 等转换方式，最终输出物理量、单位和设备状态。

## 用法

配置 transport/port、baudRate、escapedApiMode、sourceAddress、analogChannel、conversion、physicalQuantity、physicalUnit 和恢复超时，再启用 `pdr.xbee.enabled`。

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
pdr.xbee.transport = port
pdr.xbee.port = /dev/ttyUSB0
pdr.xbee.baudRate = 9600
pdr.xbee.escapedApiMode = false
pdr.xbee.sourceAddress = 0013A200405291AB
pdr.xbee.analogChannel = 0
pdr.xbee.conversion = temperature
pdr.xbee.physicalQuantity = temperature
pdr.xbee.physicalUnit = Cel
pdr.xbee.reconnectEnabled = true
pdr.xbee.reconnectDelayMilliseconds = 250
pdr.xbee.receiveTimeoutMilliseconds = 250
pdr.xbee.staleAfterMilliseconds = 5000
```

启动失败常见原因是串口被占用、AP 模式不一致或 sourceAddress 非法；无数据还应检查远端采样周期和通道 mask。

当前兼容配置契约仍接受 `analogChannel=0..15`，但 XBee `0x92` IO Sample 的模拟通道 mask 只有 8 位，设备实现实际支持 0..7。8..15 将在下一次主版本契约迁移中移除；新配置不要使用这些值。

## 状态、恢复与诊断

- 串口打开后保持 `offline`，只有来源地址匹配且包含目标模拟通道的 IO Sample 才进入 `ready`。
- 错误来源地址和不含目标通道的合法样本被忽略，不计作设备失败。
- checksum、截断 IO Sample 或串口读异常进入 `fault`；启用恢复后关闭并重开串口，重连后等待新样本。
- 超过 `staleAfterMilliseconds` 没有匹配样本时进入 `offline`，诊断错误为 `XBee sample stale`。
- 上层 value/snapshot 回调异常被隔离，不会杀死采集线程。

`/api/v1/devices` 公开成功、失败、连续失败、重连次数和最近错误。设备默认 `required=true`，因此故障或陈旧会阻止 readiness；可选传感器应显式配置 `required=false`。

开发和 CI 可使用 `transport=loopback` 验证 Bundle/API/诊断路径，生产安全门禁禁止 XBee loopback。真实串口电平、XBee AP 模式、射频链路、远端采样周期和长期丢包仍需目标机 HIL。
