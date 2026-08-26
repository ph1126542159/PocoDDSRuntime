# 中央受治理调度

`pdr.service.schedulerRuntime` 是独立 OSP Bundle，提供
`PocoDDS::Scheduling::SchedulerService` 和只读接口
`GET /api/v1/scheduled-tasks`。它以一个 `steady_clock` 定时线程管理 Runtime 内的周期任务，
但不在定时线程执行任何业务：

`Bundle → SchedulerService → central timer → ResourceGovernor owner lane → business work`

因此，任务节拍、业务并发和 Bundle 生命周期分别由 Scheduler、ResourceGovernor 和 OSP
拥有。Scheduler 不依赖 `SystemMonitoring.cpp`，也不拥有 Workflow、Outbox 或设备业务状态。

## 调度语义

- `fixed-delay`：上一次完成后再等待 interval，天然不重叠，适合轮询和维护任务。
- `fixed-rate`：按计划时刻触发；前一轮未结束时不会并发执行同一个任务。
- `skip`：记录错过次数并跳过已错过的 fixed-rate 时刻。
- `coalesce`：多个错过时刻合并成前一轮完成后的一个立即执行。
- `jitter`：在每个 interval 后增加 `[0, jitter]` 的稳定伪随机延迟，避免多个 Bundle
  同时唤醒；jitter 不得大于 interval。
- `rejectionBackoff`：ResourceGovernor 因队列、熔断或关停拒绝时的再次尝试间隔；不会
  在拒绝后形成忙循环。
- `enabled=false`：保留任务身份、回调和累计计数，只停止未来触发；已开始的一轮允许
  正常完成，因此事务回滚不会面对被强制终止的不可逆副作用。

所有业务执行仍受 owner lane 的并发、有限队列、排队超时、协作执行超时和熔断约束。
Scheduler 只保证同一任务不重入，不替代跨任务/跨 Bundle 的 ResourceGovernor 配额。

## Bundle 生命周期

Bundle 在 `start()` 注册任务，在 `stop()` 首先调用 `cancelAndWait(taskId)`。取消标记与
ResourceGovernor 的执行超时标记会合并到 `Scheduling::CancellationToken`；业务必须轮询
`requested()`。`cancelAndWait()` 返回前会等待 run 和 completion 退出，并销毁 Bundle
提供的 `std::function` 目标，防止 OSP 卸载 DLL 后遗留回调。

不得从任务自己的 run/completion 内调用该任务的 `cancelAndWait()`，因为这会等待当前
回调自身。忽略协作取消的原生代码仍可能拖延 Bundle 停止；不可信代码应放入独立进程。

```cpp
auto scheduler = Poco::OSP::ServiceFinder::find<
    PocoDDS::Scheduling::SchedulerService>(context);
PocoDDS::Scheduling::TaskSpec spec;
spec.id = "my.bundle.refresh";
spec.owner = context->thisBundle()->symbolicName();
spec.interval = std::chrono::seconds(5);
spec.jitter = std::chrono::milliseconds(500);
const auto registration = scheduler->schedule(spec,
    [](const PocoDDS::Scheduling::CancellationToken& token) {
        if (!token.requested()) refreshOneBatch();
    });

// BundleActivator::stop()
scheduler->cancelAndWait(spec.id);
```

## 事务式在线重排

`Scheduler::reconfigure(TaskSpec)` 在定时器互斥区内原子替换调度参数，保留任务回调、
owner 和执行计数；任务 ID 或 owner 不允许改变。`PocoDDS::SchedulingConfiguration`
提供通用 `ScheduleConfigurationParticipant`，业务 Bundle 只声明自己的任务和三个精确键：

- `schedulerEnabled`
- `schedulerIntervalMilliseconds`
- `schedulerJitterMilliseconds`

Workflow 和 Outbox 各自拥有这些键，ConfigurationRuntime 只负责编排，不知道业务回调。
配置提交失败时，Participant 使用事务的 previous snapshot 调回 `reconfigure()`，恢复原节拍。
启用后的第一次触发等待新 interval；禁用不会清空历史计数。

管理面通过 `POST /api/v1/configuration-transactions` 提交带 generation 和 request ID 的
字符串 patch。请求先经过 `configuration.manage`，再逐变更键检查
`configuration:write` capability。状态接口不会返回配置值或密钥。

## 状态、权限与限制

`GET /api/v1/scheduled-tasks?taskId=<id>` 返回 enabled、mode、misfire policy、下一次执行倒计时、
in-flight、触发/接受/拒绝/错过/完成/失败计数及最后状态。生产环境要求 Bearer Principal
具备 `resource.read`。

当前 Scheduler 管理的是由 Bundle 在启动时重新注册的**进程内周期任务**。它使用单调时钟，
不受系统时间回拨影响，但不提供 cron/墙钟日历，也不持久化任意业务回调。需要跨进程重启
恢复的业务状态仍应使用 Workflow Runtime；需要可靠外发仍应使用 Outbox。
