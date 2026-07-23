# 仿真设备

## 实现过程

`SimulatedDevice` 在内存中生成或保存设备状态，不依赖物理接口，供默认启动、DDS 链路和 WebUI 联调使用。

## 用法

默认配置启用 `simulation-1`。启动 `pdr-runtime` 后可通过设备网关 Topic 或 WebUI 查看并操作它。

仿真通过只证明软件路径，不证明串口、CAN、Modbus、GPIO 或真实硬件闭环。
