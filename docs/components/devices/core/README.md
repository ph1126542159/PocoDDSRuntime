# 设备基础模型

## 实现过程

`platform/devices/Devices` 定义 `Device`、`DeviceState`、`DeviceSnapshot`，并派生 Sensor、DigitalIO、LED、Switch、SerialDevice、GNSSSensor、运动传感器和媒体设备等接口。

## 用法

新增设备时继承最接近的抽象，保证 `id()` 稳定，并实现状态读取/控制及快照。设备实现不应直接耦合 WebUI；由 `DeviceGateway` 注册到 OSP，再由 DDS 桥接。

聚合目标为 `PocoDDS::Devices`，核心实现目标为 `PocoDDS::DeviceCore`。
