# WebEvent 服务

## 实现过程

服务接收 Web 事件并分发给注册接收者。Activator 建立 OSP 服务和 DDS Endpoint，使 Web 事件可跨进程请求、响应和广播。

## 用法

进程内注册接收者；跨进程使用 `pdr.web.request` 和 `pdr.web.response`，事件订阅 `pdr.web.event`。

事件载荷进入前端前必须做结构验证和输出转义，不能把不可信文本直接拼接为 HTML。

## 数据流与操作

唯一 DDS 请求操作为 `notify`。请求 payload 被解析为 JSON，服务生成 `WebEvent` 并同步通知进程内接收者，同时向 `pdr.web.event` 发布 operation=`notify` 的事件；响应经 `pdr.web.response` 返回。

```text
pdr.web.request/notify
  ├─ WebEventService 进程内接收者
  ├─ pdr.web.event 广播
  └─ pdr.web.response 确认
```

Bundle 注册服务名 `pdr.service.webEvent`，run level 230。唯一配置为公共 `pdr.fastdds.domainId`。

客户端应给事件定义明确的 type、source 和 data schema，并限制 payload 大小。通知分发不是持久队列，接收者离线期间的消息不会自动补发。

## 验证

```powershell
ctest --test-dir build -C Release -R web-event-smoke `
  --output-on-failure
```

集成测试时启动一个 DDS 请求端和事件订阅端：发送唯一 event ID，确认 response correlation ID 一致，并且订阅端只收到一次对应事件。需要离线补发时应接入持久消息系统，不能依赖本服务。
