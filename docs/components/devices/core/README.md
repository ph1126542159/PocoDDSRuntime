# 设备基础模型

## 实现过程

`platform/devices/Devices` 定义 `Device`、`DeviceState`、`DeviceSnapshot`，并派生 Sensor、DigitalIO、LED、Switch、SerialDevice、GNSSSensor、运动传感器和媒体设备等接口。

## 用法

新增设备时继承最接近的抽象，保证 `id()` 稳定，并实现状态读取/控制及快照。设备实现不应直接耦合 WebUI；由 `DeviceGateway` 注册到 OSP，再由 DDS 桥接。

聚合目标为 `PocoDDS::Devices`，核心实现目标为 `PocoDDS::DeviceCore`。

## Device 接口契约

```cpp
virtual const std::string& id() const noexcept = 0;
virtual const std::string& type() const noexcept = 0;
virtual void start() = 0;
virtual void stop() noexcept = 0;
virtual DeviceSnapshot snapshot() const = 0;
virtual std::string execute(operation, payload) = 0;
virtual void setSnapshotHandler(handler) = 0;
```

`DeviceSnapshot` 包含 `id`、`type`、`offline/ready/fault`、单调递增 sequence、微秒时间戳和字符串 payload。设备每次有效变化后递增 sequence 并调用 SnapshotHandler，DDS `DeviceBridge` 依靠这个回调发布 `pdr.device.state`。

## 新设备实现步骤

1. 继承 `Device` 或更具体的 `Sensor`/`DigitalIO`。
2. 构造函数只保存配置，不启动线程或打开硬件。
3. `start()` 打开协议并进入 ready；失败时清理资源并进入 fault。
4. `execute()` 定义稳定的 operation 和 payload 格式，对非法输入抛出明确异常。
5. `stop()` 必须幂等、不得抛异常，并先停线程再关闭句柄。
6. 在 DeviceGateway 中创建、注册 OSP 服务并建立 DeviceBridge。
7. 添加硬件无关单元测试和目标板测试。

设备基础层不读取 properties；配置所有权在创建它的 Bundle。
