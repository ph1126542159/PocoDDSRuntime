# WebEvent 服务

## 实现过程

服务接收 Web 事件并分发给注册接收者。Activator 建立 OSP 服务和 DDS Endpoint，使 Web 事件可跨进程请求、响应和广播。

## 用法

进程内注册接收者；跨进程使用 `pdr.web.request` 和 `pdr.web.response`，事件订阅 `pdr.web.event`。

事件载荷进入前端前必须做结构验证和输出转义，不能把不可信文本直接拼接为 HTML。
