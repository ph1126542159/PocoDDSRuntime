# WebTunnel 底层组件

## 实现过程

`platform/WebTunnel` 包含隧道协议、SocketDispatcher、LocalPortForwarder 和 RemotePortForwarder，负责建立连接、转发双向字节流并管理 Socket 生命周期。

## 用法

在 CMake 中链接 `Poco::WebTunnel`，按角色创建本地或远程转发器，并交给调度器运行。上层服务元数据使用 `PocoDDS::WebTunnelProtocol` 描述。

生产部署必须限制可访问的目标地址、端口和认证身份，并设置连接超时及资源上限。

## 类职责

| 类 | 作用 |
| --- | --- |
| `Protocol` | 隧道控制帧/握手协议 |
| `SocketDispatcher` | 统一管理可读写 Socket 和事件循环 |
| `LocalPortForwarder` | 接收本地连接并送入隧道 |
| `RemotePortForwarder` | 在远端接收并转发到目标服务 |

调用者负责创建已认证的隧道连接，再构造对应 forwarder 并交给 dispatcher。析构前必须先停止接受新连接，再关闭活动转发会话。

本库没有 `pdr.webTunnel.*`。生产配置需要自行定义 endpoint、认证、允许目标、并发数、空闲超时、重连退避和审计日志。

## 验证步骤

1. 启动一个只监听 `127.0.0.1` 的已知 TCP echo 服务。
2. 建立本地 forwarder、隧道连接和远端 forwarder。
3. 发送不同长度的双向数据并逐字节比较。
4. 中断任一侧网络，确认 Socket、线程和会话资源被释放。
5. 验证白名单外目标、认证失败和并发超限均被拒绝。

只验证端口可连接不足以证明转发正确；必须比较完整双向 payload 并检查断线后的资源状态。
