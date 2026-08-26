# Bundle 资源治理与背压

`pdr.service.resourceGovernor` 是独立 Runtime Bundle，拥有
`PocoDDS::ResourceGovernance::ResourceGovernorService` 和
`GET /api/v1/resource-governance`。它不依赖 `SystemMonitoring`，也不把 Bundle
生命周期、健康或进程控制的所有权转移给资源治理层。

## 边界

资源治理对象是当前 Runtime 进程中的 **Bundle/模块 owner lane**：

`Runtime Process → ResourceGovernor Service → owner lane → governed work`

每个 owner lane 有独立工作线程、有限队列、计数器和熔断状态。一个 lane 队列饱和、
执行缓慢或熔断时，其他 owner 仍使用自己的线程和队列。Bundle 应以
`context->thisBundle()->symbolicName()` 作为 owner，避免团队之间共享配额。

这不是任意原生代码沙箱。直接创建线程、绕过 Service API 的工作不会自动受控；进程内
Bundle 仍可能造成进程崩溃或内存破坏。不可信原生插件必须放入独立 Plugin Host/子进程，
再叠加 OS 进程限制。

## 背压和超时语义

- `maximumConcurrency`：owner 同时执行的最大工作数。
- `queueCapacity`：owner 等待队列上限；满载立即返回 `queue-full`，不形成无界积压。
- `queueTimeoutMilliseconds`：工作开始前的最长排队时间；超时不再执行。
- `executionTimeoutMilliseconds`：到期后设置 `CancellationToken`。Bundle 工作必须轮询
  `token.requested()` 并安全返回。
- `failureThreshold`：连续失败或执行超时达到阈值后打开 owner 熔断器。
- `circuitResetMilliseconds`：到期只允许一个 half-open 探测；成功关闭，失败重新打开。

C++ 不能安全强杀任意线程，因此执行超时是协作式的。忽略取消的工作继续占用**自己的**
并发槽位，直到自行返回；框架不会虚假释放槽位，也不会让它挤占其他 owner lane。

## Bundle 接入

Bundle 代码优先使用 `ManagedWorkLane`，由适配层绑定 owner，并在 Bundle 停止时形成回调
卸载屏障：

```cpp
auto governor = Poco::OSP::ServiceFinder::find<
    PocoDDS::ResourceGovernance::ResourceGovernorService>(context);
PocoDDS::ResourceGovernance::ManagedWorkLane lane(
    governor, context->thisBundle()->symbolicName());
const auto admission = lane.submit({
    "refresh-cache",
    [](const PocoDDS::ResourceGovernance::CancellationToken& token) {
        while (hasMoreWork() && !token.requested()) processNextBatch();
    },
    [](const PocoDDS::ResourceGovernance::Completion& result) {
        recordCompletion(result.status);
    }});

// BundleActivator::stop() 在释放 Bundle 对象和卸载 DLL 前调用：
lane.closeAndWait();
```

调用方必须处理 `queue-full`、`circuit-open` 和 `shutting-down`，不能在失败后无退避地
立即重试。`complete` 回调在治理线程上运行，必须短小、非阻塞。即使 completion 抛出，
适配层也会收敛在途计数；但框架会吞掉该异常，因此业务仍应自行记录。

`ManagedWorkLane::closeAndWait()` 不得从该 lane 自己的 run/complete 回调内调用，否则会
等待当前回调自身。普通一次性后台工作可直接使用该适配层；周期任务应注册到独立的
`SchedulerService`。Scheduler 统一管理节拍并把每轮工作提交到 ResourceGovernor，详见
[中央受治理调度](managed-scheduling.md)。

## 配置

默认 policy 使用 `pdr.resourceGovernor.default.*`；最多 128 个 owner 覆盖使用：

```properties
pdr.resourceGovernor.default.maximumConcurrency = 2
pdr.resourceGovernor.default.queueCapacity = 128
pdr.resourceGovernor.default.queueTimeoutMilliseconds = 1000
pdr.resourceGovernor.default.executionTimeoutMilliseconds = 30000
pdr.resourceGovernor.default.failureThreshold = 5
pdr.resourceGovernor.default.circuitResetMilliseconds = 10000
pdr.resourceGovernor.overrides.count = 1
pdr.resourceGovernor.overrides.0.owner = pdr.service.workflowRuntime
pdr.resourceGovernor.overrides.0.maximumConcurrency = 4
```

配置 Validator 和 JSON Schema 对并发、容量、超时、阈值、owner 格式及重复 owner
执行同一组检查。当前 policy 在 Bundle 启动时生效；在线事务换代属于后续独立治理能力，
不能通过修改内存对象绕过配置事务。

## 状态和权限

`GET /api/v1/resource-governance?owner=<id>` 返回 policy、active/pending、熔断状态以及
接受、队列拒绝、熔断拒绝、排队超时、执行超时、成功、失败和取消计数。生产环境要求
Bearer Principal 具备 `resource.read`；响应不包含令牌、线程句柄或内部地址。
