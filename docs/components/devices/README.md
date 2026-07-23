# 设备组件总览

`platform/devices` 分为设备抽象和具体后端。所有设备公开统一的标识、状态和快照语义，`DeviceGateway` 负责创建启用的设备并通过 OSP/DDS 对外提供。

| 组件 | 数据来源 |
| --- | --- |
| Core | 设备、传感器、数字 IO 等抽象 |
| CAN | CAN 帧中的位域信号 |
| GNSS | 串口 NMEA 语句 |
| Linux | sysfs GPIO/LED |
| Modbus | Modbus 寄存器 |
| Serial | 原始串口 |
| Simulation | 内存仿真 |
| XBeeSensor | XBee IO Sample |

具体后端只有在对应 `pdr.*.enabled=true` 时由设备网关启用；默认可移植配置只启用仿真设备。
