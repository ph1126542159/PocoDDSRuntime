# MobileConnection 服务

## 实现过程

公共接口描述移动数据连接状态和操作。默认 `MemoryMobileConnectionService` 用于可移植运行；Legato 后端在支持的平台控制实际数据连接。Activator 将服务注册到 OSP 并桥接 DDS。

## 用法

跨进程通过 `pdr.mobile.request/response` 控制或查询，订阅 `pdr.mobile.state` 获取状态。使用 Legato 后端前必须在目标平台提供相应 SDK 和运行服务。

内存后端只用于软件联调，不代表调制解调器已联网。

## 后端配置

```properties
# memory 或 legato
mobile.backend = memory
mobile.legato.cmPath = /legato/systems/current/bin/cm
pdr.fastdds.domainId = 0
```

`memory` 在内存中维护状态，适合 UI/DDS 联调。`legato` 调用配置的 `cm` 工具查询 SIM、注册、信号和数据连接，必须在 Legato 目标系统使用。

## DDS 操作

| operation | 关键 payload |
| --- | --- |
| `state` | 空对象 |
| `enableRadio` | `{"enabled":true}` |
| `setAPN` | `{"apn":"internet"}` |
| `setPDPType` | `{"type":枚举整数}` |
| `authenticate` | method、username、password |
| `enterPIN` | `{"pin":"..."}` |
| `connect` / `disconnect` | 空对象 |

连接变化发布 `connected`/`disconnected` 到 `pdr.mobile.state`。密码和 PIN 不得进入普通日志或追踪字段。

## 验证边界

memory 后端返回 connected 只证明服务状态机。Legato 验收还必须核对 `cm` 输出、网络接口/IP、默认路由、DNS 和真实数据收发。
