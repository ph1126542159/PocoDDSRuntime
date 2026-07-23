# DeviceStatus 服务

## 实现过程

服务维护状态更新、消息和设备状态变化，通过 ActiveDispatcher 串行处理异步更新。Activator 注册 OSP 服务，并将请求、响应和状态事件映射到 DDS。

## 用法

进程内获取 `DeviceStatusService` 发布/查询状态；跨进程使用 `pdr.status.request`、`pdr.status.response`，并订阅 `pdr.device.status`。

状态 class/标识必须稳定；同类状态的替换规则由服务接口定义。
