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
3. 按 `pdr.simulation.count` 创建仿真设备，默认创建 `simulation-1`。
4. 按各设备族的编号配置创建物理设备；未使用 `count` 时兼容原单实例配置。
5. 每个设备注册一个 OSP 服务，名称为 `pdr.device.<deviceId>`，属性包含 `pdr.device`、`pdr.deviceType`、`pdr.deviceState` 和 `pdr.bundle`。
6. 每个设备创建独立 `DeviceBridge`，启动设备并桥接三个 DDS Topic。

停止时先停所有 bridge，再注销 OSP 服务、销毁设备，最后停止 DDS Runtime。

## 完整配置入口

| 后端 | 设备族 | 主要配置 |
| --- | --- | --- |
| Simulation | `pdr.simulation` | id |
| Modbus | `pdr.modbus` | id、host、port、unitId、timeoutMilliseconds、readRetryAttempts、retryDelayMilliseconds |
| Serial | `pdr.serial` | id、transport、port、baudRate、parameters、flowControl、重连与读取超时 |
| GNSS | `pdr.gnss` | id、transport、port、baudRate、重连/读取/陈旧超时 |
| GPIO | `pdr.gpio` | id、pin、direction、sysfsRoot、manageExport、exportTimeoutMilliseconds |
| XBee | `pdr.xbee` | id、transport、port、sourceAddress、channel、conversion、恢复/陈旧超时 |
| CAN | `pdr.can` | id、transport、interface、frameId、extended、位域、缩放、重连与陈旧超时 |
| LED | `pdr.led` | id、path |

具体字段、格式和操作见对应设备 README。

## DDS 使用

向 `pdr.device.request` 发布 Envelope，`operation` 为设备支持的操作，payload 为该操作规定的字符串，并携带目标设备 ID。网关在 `pdr.device.response` 返回相同 correlation ID；异步快照发布到 `pdr.device.state`。

## 多实例配置

每个设备族支持 `count` 加从零开始的编号项：

```properties
pdr.modbus.count = 2
pdr.modbus.0.id = cabinet-a
pdr.modbus.0.host = 192.168.10.11
pdr.modbus.0.port = 502
pdr.modbus.0.unitId = 1
pdr.modbus.0.timeoutMilliseconds = 2000
pdr.modbus.0.readRetryAttempts = 1
pdr.modbus.0.retryDelayMilliseconds = 50
pdr.modbus.1.id = cabinet-b
pdr.modbus.1.host = 192.168.10.12
pdr.modbus.1.port = 502
pdr.modbus.1.unitId = 1
```

`count` 存在时编号配置是唯一权威来源，旧的 `pdr.modbus.enabled` 等单实例键会被忽略。`count` 不存在时继续支持原有配置，以保证现场配置可以平滑升级。每个启用实例可以用 `enabled=false` 暂时关闭；所有设备族共享同一 ID 空间，重复或空 ID 会在启动校验阶段被拒绝。Modbus 只自动重试读操作；写寄存器不会自动重放，避免连接中断时产生不可判定的重复写。

每个设备实例默认 `required=true`。任一必需设备为 `offline` 或 `fault` 时，Runtime 仍保持 live，但 `/health/ready` 返回 503，`/health/detail` 的 `devices` 组件为 `DEGRADED`。监控型、可选外设或 CI loopback 可以显式配置 `required=false`；设备仍出现在 API 和 Web 中，但不阻止部署 readiness。

## 设备发现

`GET /api/v1/devices` 通过 OSP 设备服务对象读取实时快照，字段包括 `id`、`type`、
`state`、`sequence`、`timestampMicroseconds`、`bundle`、`service` 和 `required`。支持诊断能力的
适配器还会返回成功/失败操作数、连续失败数、重连次数、最后成功/失败时间和最后错误。
Web 控制台的“设备”页面使用同一接口，因此页面展示的是设备当前事实，而不是注册时
或静态配置推测出来的状态。

## 验证顺序

先确认日志中的设备数量，再查每个 `pdr.device.<id>` OSP 服务，最后检查 DDS state/request/response。物理设备验收必须同时查看总线报文或硬件状态。
