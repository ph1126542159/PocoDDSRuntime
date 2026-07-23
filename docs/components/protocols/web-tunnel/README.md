# WebTunnel 协议适配组件

## 实现过程

`platform/protocols/WebTunnel` 定义可转发服务及其属性，是上层服务描述接口；Socket 调度、本地和远程端口转发由 `platform/WebTunnel` 实现。

## 用法

业务层构造 `Service` 和属性集合，平台层建立转发器并连接隧道端点。部署时必须显式限制允许转发的主机和端口，并对隧道入口做认证。

该目标本身是 INTERFACE 库，不单独启动网络服务。

## 使用与配置边界

协议层 `Service` 保存服务标识、属性和连接状态回调；真正的协议握手、Socket 调度与端口转发位于 `platform/WebTunnel`。

```cpp
using namespace PocoDDS::Protocols::WebTunnel;
Service service("diagnostics");
service.setProperty("host", "127.0.0.1");
service.setProperty("port", "9080");
service.setConnectionHandler([](bool connected) { /* 更新状态 */ });
```

当前没有 `pdr.webTunnel.*`。新增部署配置时至少需要远端 URI、认证材料、允许的本地目标、连接超时和重连退避。必须使用目标白名单，避免形成任意端口转发。

## 构建验证

```powershell
ctest --test-dir build -C Release -R webtunnel-protocol-smoke `
  --output-on-failure
```

该测试只验证服务描述和回调接口。完整验收需启动本地监听端、远端隧道端和目标 TCP 服务，分别验证双向数据、断线释放、重连、并发上限和未授权目标拒绝。
