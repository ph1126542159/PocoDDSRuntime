# MobileConnection 服务

## 实现过程

公共接口描述移动数据连接状态和操作。默认 `MemoryMobileConnectionService` 用于可移植运行；Legato 后端在支持的平台控制实际数据连接。Activator 将服务注册到 OSP 并桥接 DDS。

## 用法

跨进程通过 `pdr.mobile.request/response` 控制或查询，订阅 `pdr.mobile.state` 获取状态。使用 Legato 后端前必须在目标平台提供相应 SDK 和运行服务。

内存后端只用于软件联调，不代表调制解调器已联网。
