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

具体后端通过 `pdr.<type>.count` 和 `pdr.<type>.<index>.*` 创建；未声明 `count` 时仍兼容 `pdr.*.enabled=true` 单实例配置。默认可移植配置只启用一个仿真设备。

## 统一实现流程

每个设备实现 `start/stop/snapshot/execute/setSnapshotHandler`。设备后端负责线程和物理协议；`DeviceBridge` 负责 DDS；`DeviceGateway` 负责配置和 OSP 注册。三层不能混在一起，否则设备无法独立测试。

```text
pdr-runtime.properties
→ DeviceGateway
→ Device 实现
→ Protocol/OS 驱动
→ 物理设备

DeviceSnapshot
→ DeviceBridge
→ pdr.device.state
```

配置项集中在 `config/pdr-runtime.properties`。每类最多配置 256 个实例，编号从零开始。所有启用实例的 `id` 必须在全部设备类型之间唯一，OSP 服务名和 DDS 路由均使用该 ID。

## 测试

```powershell
ctest --test-dir build -C Release `
  -R "device|gnss|can-signal|linux-sysfs|xbee-sensor" `
  --output-on-failure
```

测试成功证明设备模型和模拟输入路径；真实总线和物理量必须单独闭环。
