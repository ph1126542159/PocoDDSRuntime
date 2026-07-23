# ROS Bridge 协议组件

## 实现过程

`BridgeClient` 通过 rosbridge WebSocket JSON 协议连接 ROS，提供 Topic 订阅及消息回调，避免运行时直接依赖 ROS C++ 客户端库。

## 用法

先启动 ROS 和 rosbridge_server，再配置 WebSocket 地址，创建 `BridgeClient` 并按 `SubscribeOptions` 订阅 Topic。消息载荷仍是 JSON，业务层负责验证字段和类型。

本组件不是 ROS 节点运行时，不能替代 rosbridge_server。
