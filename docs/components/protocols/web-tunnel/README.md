# WebTunnel 协议适配组件

## 实现过程

`platform/protocols/WebTunnel` 定义可转发服务及其属性，是上层服务描述接口；Socket 调度、本地和远程端口转发由 `platform/WebTunnel` 实现。

## 用法

业务层构造 `Service` 和属性集合，平台层建立转发器并连接隧道端点。部署时必须显式限制允许转发的主机和端口，并对隧道入口做认证。

该目标本身是 INTERFACE 库，不单独启动网络服务。
