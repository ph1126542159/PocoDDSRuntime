# WebTunnel 底层组件

## 实现过程

`platform/WebTunnel` 包含隧道协议、SocketDispatcher、LocalPortForwarder 和 RemotePortForwarder，负责建立连接、转发双向字节流并管理 Socket 生命周期。

## 用法

在 CMake 中链接 `Poco::WebTunnel`，按角色创建本地或远程转发器，并交给调度器运行。上层服务元数据使用 `PocoDDS::WebTunnelProtocol` 描述。

生产部署必须限制可访问的目标地址、端口和认证身份，并设置连接超时及资源上限。
