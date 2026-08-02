# ROS Bridge 协议组件

## 实现过程

`BridgeClient` 通过 rosbridge WebSocket JSON 协议连接 ROS，提供 Topic 订阅及消息回调，避免运行时直接依赖 ROS C++ 客户端库。接收端支持 WebSocket 文本分片、交错 Ping/Pong、关闭帧和跨超时保留未完成消息，并限制完整消息大小，避免固定 64 KiB 缓冲区截断或无限增长。

该类实现统一的 `PocoDDS::Protocols::Protocol` 生命周期，可由通用管理代码调用 `open()`、`close()`、`isOpen()` 和 `name()`；原有 `connect()`、`disconnect()`、`isConnected()` 保留兼容。

## 用法

先启动 ROS 和 rosbridge_server，再配置 WebSocket 地址，创建 `BridgeClient` 并按 `SubscribeOptions` 订阅 Topic。消息载荷仍是 JSON，业务层负责验证字段和类型。

本组件不是 ROS 节点运行时，不能替代 rosbridge_server。

## C++ 用法

```cpp
using PocoDDS::Protocols::ROS::BridgeClient;
BridgeClient::Options bridgeOptions;
bridgeOptions.uri = Poco::URI("ws://127.0.0.1:9090");
bridgeOptions.maximumMessageSize = 4 * 1024 * 1024;
bridgeOptions.connectTimeoutSeconds = 10;
// 生产环境使用 wss://，并设置 trustStore；mTLS 再设置客户端证书和私钥。
// bridgeOptions.authorization = "Bearer ...";
// bridgeOptions.trustStore = "certificates/ca.pem";
// bridgeOptions.clientCertificate = "certificates/client.crt";
// bridgeOptions.privateKey = "certificates/client.key";
BridgeClient bridge(std::move(bridgeOptions));
bridge.setMessageHandler([](Poco::JSON::Object::Ptr message) {
    // 校验 op、topic、msg
});
bridge.connect();
BridgeClient::SubscribeOptions options;
options.type = "sensor_msgs/msg/Temperature";
bridge.subscribe("/temperature", options);
bridge.unsubscribeAll();
bridge.disconnect();
```

`Options::maximumMessageSize` 可设置完整消息上限，默认 1 MiB。`connectTimeoutSeconds` 默认 10 秒。`wss://` 支持自定义 CA、服务端证书和主机名校验、mTLS 客户端证书/私钥及 HTTP `Authorization` 请求头。原有构造函数继续兼容：

```cpp
BridgeClient bridge(Poco::URI("ws://127.0.0.1:9090"), 4 * 1024 * 1024);
```

消息回调异常会被隔离，`receiveMessage()` 仍返回已解析对象；业务层应自行记录回调失败。单次接收的超时是整个调用的总预算，不会因分片数增加而重复累加。

`diagnostics()` 返回公共 `ProtocolDiagnostics`，统一提供成功/失败操作、收发消息与字节、超时、回调异常和最近错误，便于 Runtime/Web 诊断层直接聚合。

订阅选项可指定消息类型、节流、队列长度、分片大小和压缩方式。组件没有 properties 自动加载，URI 与订阅项由调用者提供。

```bash
ros2 launch rosbridge_server rosbridge_websocket_launch.xml port:=9090
```

WebSocket 建连成功不代表 Topic 正确；还要验证 Topic 名、消息类型和 JSON 字段。

`ros-bridge-integration` 使用本机真实 WebSocket 连接覆盖订阅、文本分片、交错 Ping/Pong、回调异常隔离、取消订阅和关闭。`ros-tls-integration` 动态生成临时 CA、服务端和客户端证书，验证 wss/mTLS、Authorization、错误 CA 与主机名不匹配拒绝，并通过完整 Runtime/ProtocolGateway 证明实例在线且秘密不进入报告或日志。它们仍不证明外部 rosbridge_server、ROS graph、真实 Topic 类型/QoS、生产认证策略、证书轮换或长期断网重连可用。
