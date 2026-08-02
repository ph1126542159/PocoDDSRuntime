# WebTunnel 协议适配组件

## 实现过程

`platform/protocols/WebTunnel` 提供两个层次：`Service/SimulatedService` 用于上层状态与测试适配，`LocalForwarder` 是可直接使用的真实本地端口转发器。底层 WebSocket 数据转发和 Socket 调度复用 `platform/WebTunnel`。

## 用法

业务层为 `LocalForwarder::Options` 指定本地监听地址、隧道 WebSocket URI 和远端目标端口，再执行 `open()`。本地 TCP 连接到来时会建立独立的 WebSocket 隧道；`close()` 停止监听并关闭现有转发。重复 `open/close` 是幂等的。

```cpp
using PocoDDS::Protocols::WebTunnel::LocalForwarder;
LocalForwarder::Options options;
options.localHost = "127.0.0.1";
options.localPort = 0; // 自动选择空闲端口
options.remoteUri = "wss://tunnel.example.com/device";
options.remotePort = 9080;
options.authorization = "Bearer ...";
options.trustStore = "certificates/site-ca.pem";
options.clientCertificate = "certificates/device.pem"; // 可选 mTLS
options.privateKey = "certificates/device.key";
LocalForwarder forwarder(std::move(options));
forwarder.open();
auto port = forwarder.localPort();
```

`connectTimeoutSeconds` 控制 WebSocket 建连，`localIdleTimeoutSeconds` 和 `remoteIdleTimeoutSeconds` 控制空闲连接，`maximumQueuedConnections`、`maximumThreads` 限制本地并发资源。`ws://` 不允许携带 TLS 材料；客户端证书和私钥必须成对配置。生产环境应使用 `wss://`，保持证书链和主机名验证开启。

安装 SDK 后，外部 CMake 项目直接链接导出的目标，不需要手工查找静态库：

```cmake
find_package(PocoDDSRuntime CONFIG REQUIRED COMPONENTS WebTunnelProtocol)
target_link_libraries(my_app PRIVATE PocoDDS::WebTunnelProtocol)
```

## 使用与配置边界

协议层 `Service` 保存连接状态回调；真正的协议握手、Socket 调度与端口转发位于 `platform/WebTunnel`。连接回调可并发更新，回调异常会被隔离并由 `connectionHandlerFailures()` 计数，避免业务回调破坏隧道状态机。

```cpp
using namespace PocoDDS::Protocols::WebTunnel;
SimulatedService service;
service.updateProperties({{"host", "127.0.0.1"}, {"port", "9080"}});
service.setConnectionHandler([](bool connected) { /* 更新状态 */ });
```

当前没有 `pdr.webTunnel.*`，因此 `LocalForwarder` 由嵌入该库的应用显式构造，不会因 Runtime 默认配置意外开放端口。隧道服务端必须将请求中的目标端口与设备/身份白名单绑定，不能仅信任客户端提交的 `X-WebTunnel-RemotePort`，否则会形成任意端口转发。Authorization 应由应用从秘密存储或环境变量注入，不应写入日志和普通配置文件。

## 构建验证

```powershell
ctest --test-dir build -C Release -R webtunnel-protocol-smoke `
  --output-on-failure
ctest --test-dir build -C Release -R webtunnel-local-forwarder-integration `
  --output-on-failure
ctest --test-dir build -C Release -R webtunnel-tls-integration `
  --output-on-failure
```

`webtunnel-protocol-smoke` 验证模拟状态、指标、回调隔离和非法安全配置拒绝。`webtunnel-local-forwarder-integration` 启动真实本地 TCP 客户端、带 Authorization/端口白名单的 WebSocket 隧道服务和远端 TCP Echo，验证任意二进制字节双向穿透及幂等启停。`webtunnel-tls-integration` 动态生成临时 CA、服务端和客户端证书，验证 wss/mTLS/Authorization、错误 CA、主机名不匹配、缺失客户端证书拒绝及秘密不泄漏。生产代理策略、证书轮换、并发压力、跨公网断线恢复和长稳仍需对应环境验收。
