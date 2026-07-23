# DeviceGateway 服务

## 实现过程

`services/DeviceGateway/src/BundleActivator.cpp` 读取 `pdr.*` 配置，创建仿真、Modbus、串口、GNSS、GPIO、LED、XBee 和 CAN 设备，注册本地 OSP 服务，并通过 `DeviceBridge` 连接 DDS。

## 用法

在 `pdr-runtime.properties` 中只启用实际存在且已配置的设备后端。启动后通过：

- `pdr.device.state` 接收状态；
- `pdr.device.request` 发送操作；
- `pdr.device.response` 接收结果。

先用仿真设备验证上层链路，再逐个启用物理设备，便于定位协议层和业务层边界。

## 启动和注册流程

1. 从 OSP `PreferencesService` 取得统一配置。
2. 创建名为 `pdr-device-gateway` 的 DDS Runtime。
3. 无条件创建 `simulation-1`。
4. 根据 `pdr.*.enabled` 创建物理设备。
5. 每个设备注册一个 OSP 服务，名称为 `pdr.device.<deviceId>`，属性包含 `pdr.device`、`pdr.deviceType` 和 `pdr.bundle`。
6. 每个设备创建独立 `DeviceBridge`，启动设备并桥接三个 DDS Topic。

停止时先停所有 bridge，再注销 OSP 服务、销毁设备，最后停止 DDS Runtime。

## 完整配置入口

| 后端 | 开关 | 主要配置 |
| --- | --- | --- |
| Simulation | 无，始终创建 | ID 固定 `simulation-1` |
| Modbus | `pdr.modbus.enabled` | host、port、unitId |
| Serial | `pdr.serial.enabled` | port、baudRate |
| GNSS | `pdr.gnss.enabled` | port、baudRate |
| GPIO | `pdr.gpio.enabled` | pin、direction、sysfsRoot、manageExport |
| XBee | `pdr.xbee.enabled` | id、port、sourceAddress、channel、conversion |
| CAN | `pdr.can.enabled` | id、interface、frameId、位域与缩放 |
| LED | `pdr.led.enabled` | id、path |

具体字段、格式和操作见对应设备 README。

## DDS 使用

向 `pdr.device.request` 发布 Envelope，`operation` 为设备支持的操作，payload 为该操作规定的字符串，并携带目标设备 ID。网关在 `pdr.device.response` 返回相同 correlation ID；异步快照发布到 `pdr.device.state`。

当前 Activator 只支持每类一个实例，除 CAN/XBee/LED 外多数 ID 固定。需要多设备时不能简单复制同名配置，应扩展为编号列表并保证 OSP service name 与 DDS 路由 ID 唯一。

## 验证顺序

先确认日志中的设备数量，再查 OSP Registry，最后检查 DDS state/request/response。物理设备验收必须同时查看总线报文或硬件状态。
