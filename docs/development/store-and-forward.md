# Store-and-Forward Outbox

Store-and-Forward Outbox 为 MQTT、DDS、HTTP 或产品自定义外发链路提供统一的可靠发送边界。业务先把消息持久写入 Outbox；独立 Runtime Bundle 再调用动态发现的 Delivery Provider。Provider 不在线时，消息保持 `pending`，不会退化为进程内临时队列。

Runtime 向中央 `SchedulerService` 注册 fixed-delay `pump()`/过期清理任务，owner 固定为
`pdr.service.outboxRuntime`。Scheduler 再把每轮工作提交到 ResourceGovernor；该 Bundle
不再创建私有节拍线程，停止时使用 `cancelAndWait()` 清空并销毁回调。

## 组件边界

- `PocoDDS::StoreForwardAPI`：消息、投递结果、Provider 和 Runtime 服务接口。
- `PocoDDS::StoreForwardCore`：SQLite Store、有序调度、退避、配额和死信状态机。
- `pdr.service.outboxRuntime`：Provider 动态发现、后台投递和终态数据清理。
- Delivery Provider Bundle：只负责一次真实投递尝试，例如 MQTT publish 或 HTTP request。

业务模块只能调用 `OutboxRuntimeService::enqueue`，不能直接控制后台线程或 SQLite。Provider 不能删除 Outbox 消息，只能返回 acknowledged、retry 或 permanentFailure。

## 可靠性语义

- `provider + idempotencyKey` 唯一，重复入队返回原消息。
- 调用 Provider 前先持久写入 `delivering` 和 attempt；进程退出后恢复为 `pending`。
- 同一 `provider + orderingKey` 一次只放行最早的非终态消息。
- Retry 支持 Provider 指定延时；未指定时使用指数退避并受最大延时限制。
- 达到最大次数、永久失败、过期或新 Provider 的载荷上限不兼容时进入 `dead-letter`。
- 死信必须显式 `redrive`，重投会保留消息 ID 和幂等键并重置尝试次数。
- 活跃消息配额和全局载荷上限提供明确背压。
- Delivered/Cancelled 按保留期清理，Dead Letter 不自动删除。

Provider 调用采用“至少一次”语义：外部系统已接受消息、但本地 acknowledgement 检查点尚未提交时发生进程中断，恢复后会再次投递。因此 Provider 应把 `DeliveryRequest::idempotencyKey` 传给支持幂等键的外部系统，或在适配器侧实现去重。

## Provider 注册

```cpp
class MqttDelivery final
    : public PocoDDS::StoreForward::DeliveryProviderService
{
public:
    ProviderDescriptor descriptor() const override
    {
        return {"mqtt", "1.0.0", 256 * 1024};
    }

    DeliveryResult deliver(const DeliveryRequest& request) override;
};
```

```cpp
Poco::OSP::Properties properties;
properties.set("pdr.delivery.provider.kind", "outbox");
properties.set("pdr.delivery.provider.type", "mqtt");
context->registry().registerService(
    "pdr.delivery.provider.mqtt", new MqttDelivery, properties);
```

Runtime 验证注册属性与 `descriptor().type` 一致，并拒绝重复类型。Provider 可以独立升级或暂时下线；未投递消息仍留在 Outbox。

## 入队

```cpp
PocoDDS::StoreForward::EnqueueRequest request;
request.provider = "mqtt";
request.destination = "factory/line-1/events";
request.idempotencyKey = eventId;
request.orderingKey = deviceId;
request.payload = jsonPayload;
const auto stored = outbox->enqueue(request);
```

不要在 payload 中存放明文密钥；Provider 应通过后续独立的 `SecretProvider` 获取凭据。

## 配置

```properties
pdr.outbox.schedulerEnabled = true
pdr.outbox.schedulerIntervalMilliseconds = 100
pdr.outbox.schedulerJitterMilliseconds = 0
pdr.outbox.maintenanceIntervalSeconds = 60
pdr.outbox.maximumActiveMessages = 10000
pdr.outbox.maximumPayloadBytes = 1048576
pdr.outbox.maximumAttempts = 8
pdr.outbox.initialRetryDelayMilliseconds = 1000
pdr.outbox.maximumRetryDelayMilliseconds = 60000
pdr.outbox.deliveryBatchSize = 100
pdr.outbox.terminalRetentionHours = 168
# 默认：Bundle 持久目录/messages.sqlite
# pdr.outbox.database = ${application.dir}data/outbox/messages.sqlite
```

三个 scheduler 键由 `outbox-scheduler` 事务参与者精确认领，可在线禁用、调整周期或抖动并
在事务失败时回滚；Outbox 数据、重试状态和累计消息不会因调度禁用而删除。

外部 Provider 项目只需要：

```cmake
find_package(PocoDDSRuntime CONFIG REQUIRED COMPONENTS StoreForwardAPI)
target_link_libraries(my_delivery_provider PRIVATE PocoDDS::StoreForwardAPI)
```

## 当前边界

- v1 为单 Runtime 写入模型，不支持多个 Runtime 进程同时消费同一 SQLite 文件。
- 严格顺序只在相同 Provider 和非空 ordering key 内保证，不在不同设备或不同 Provider 间建立全局顺序。
- Outbox 不替代业务 Workflow；Workflow 负责编排，Outbox 负责一次最终外发的可靠交付。
