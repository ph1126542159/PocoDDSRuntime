# DeviceGateway 服务

## 实现过程

`services/DeviceGateway/src/BundleActivator.cpp` 读取 `pdr.*` 配置，创建仿真、Modbus、串口、GNSS、GPIO、LED、XBee 和 CAN 设备，注册本地 OSP 服务，并通过 `DeviceBridge` 连接 DDS。

## 用法

在 `pdr-runtime.properties` 中只启用实际存在且已配置的设备后端。启动后通过：

- `pdr.device.state` 接收状态；
- `pdr.device.request` 发送操作；
- `pdr.device.response` 接收结果。

先用仿真设备验证上层链路，再逐个启用物理设备，便于定位协议层和业务层边界。
