# ROS Bridge 协议组件

## 实现过程

`BridgeClient` 通过 rosbridge WebSocket JSON 协议连接 ROS，提供 Topic 订阅及消息回调，避免运行时直接依赖 ROS C++ 客户端库。

## 用法

先启动 ROS 和 rosbridge_server，再配置 WebSocket 地址，创建 `BridgeClient` 并按 `SubscribeOptions` 订阅 Topic。消息载荷仍是 JSON，业务层负责验证字段和类型。

本组件不是 ROS 节点运行时，不能替代 rosbridge_server。

## C++ 用法

```cpp
using PocoDDS::Protocols::ROS::BridgeClient;
BridgeClient bridge(Poco::URI("ws://127.0.0.1:9090"));
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

订阅选项可指定消息类型、节流、队列长度、分片大小和压缩方式。组件没有 properties 自动加载，URI 与订阅项由调用者提供。

```bash
ros2 launch rosbridge_server rosbridge_websocket_launch.xml port:=9090
```

WebSocket 建连成功不代表 Topic 正确；还要验证 Topic 名、消息类型和 JSON 字段。
