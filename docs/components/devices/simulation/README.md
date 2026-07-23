# 仿真设备

## 实现过程

`SimulatedDevice` 在内存中生成或保存设备状态，不依赖物理接口，供默认启动、DDS 链路和 WebUI 联调使用。

## 用法

默认配置启用 `simulation-1`。启动 `pdr-runtime` 后可通过设备网关 Topic 或 WebUI 查看并操作它。

仿真通过只证明软件路径，不证明串口、CAN、Modbus、GPIO 或真实硬件闭环。

## 行为

`start()` 启动工作线程并进入 ready；线程周期性更新快照。支持：

| operation | payload | 结果 |
| --- | --- | --- |
| `read` | 空 | 当前数值 |
| `set` | 可被 `std::stod` 解析的浮点文本 | 更新数值并发布快照 |

```cpp
SimulatedDevice device("simulation-test");
device.setSnapshotHandler([](const DeviceSnapshot& s) {
    // 检查 s.sequence 和 s.payload
});
device.start();
device.execute("set", "42.5");
device.stop();
```

DeviceGateway 无条件创建 ID 为 `simulation-1` 的仿真设备，没有关闭配置。若产品部署不允许仿真设备，需要修改 Activator 增加显式开关。

## 验证和故障

通过 `pdr.device.request` 发送 `set`，再同时检查 response 和 `pdr.device.state` 的 payload/sequence。非法浮点文本会由 `std::stod` 抛出并转换成失败响应。

线程停止后不应继续产生 sequence。若卸载 DeviceGateway 后仍收到状态，应检查是否存在另一个 DDS participant 或旧进程，而不是重复启动 Bundle。
