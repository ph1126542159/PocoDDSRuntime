# 持久化 Workflow Runtime

Workflow Runtime 用于需要跨线程、跨 Bundle 生命周期或跨进程重启继续执行的业务流程。它是独立的 OSP Bundle，不依赖 `SystemMonitoring.cpp`，也不把设备、协议或业务实现写入框架核心。

Runtime 向中央 `SchedulerService` 注册 fixed-delay `runDue()` 任务，owner 固定为
`pdr.service.workflowRuntime`。Scheduler 再把每轮工作提交到 ResourceGovernor；该 Bundle
不再创建私有节拍线程。停止时使用 `cancelAndWait()` 清空并销毁回调后再卸载。

## 组件边界

- `PocoDDS::WorkflowAPI`：稳定的定义提供者与运行时服务接口，供业务 Bundle 使用。
- `PocoDDS::WorkflowCore`：状态机与 SQLite 存储实现；业务代码不需要修改它。
- `pdr.service.workflowRuntime`：发现定义提供者、运行到期重试任务并注册 `WorkflowRuntimeService`。
- 业务 Bundle：实现 `WorkflowDefinitionService`，只负责步骤行为和反向补偿。

依赖方向固定为：业务入口 → `WorkflowRuntimeService` → Workflow Core → 定义提供者。定义提供者可以调用自己的 Application Port，但不能反向依赖 Runtime Bundle 实现。

## 已保证的运行语义

- `type + businessKey` 唯一；重复启动返回原实例，不会重复调用步骤。
- 每次调用业务步骤前先写入 `running` 检查点；异常退出后启动时转为 `interrupted`，由调用方明确恢复。
- 支持精确事件名等待、定时重试、最大尝试次数、取消和反向补偿。
- 每个补偿成功后单独写入检查点。进程在补偿期间退出时，可以跳过已经确认完成的补偿步骤。
- 定义版本写入实例；版本不一致时拒绝盲目恢复，防止新代码错误解释旧流程。
- SQLite 启用 WAL 和 `synchronous=FULL`。

步骤回调和补偿回调仍应按幂等方式实现。进程可能在外部副作用已经发生、但本地完成检查点尚未提交的极小窗口退出，此时恢复会形成“至少一次”调用。

## 定义提供者

```cpp
class ReleaseWorkflow final
    : public PocoDDS::Workflow::WorkflowDefinitionService
{
public:
    PocoDDS::Workflow::DefinitionDescriptor descriptor() const override
    {
        return {"release-device", "1.0.0",
                {"prepare", "approve", "publish"}, 3};
    }

    PocoDDS::Workflow::StepResult execute(
        const std::string& step,
        const PocoDDS::Workflow::StepContext& context) override;

    void compensate(
        const std::string& step,
        const PocoDDS::Workflow::StepContext& context) override;
};
```

注册服务时必须同时给出可审计的发现属性：

```cpp
Poco::OSP::Properties properties;
properties.set("pdr.workflow.provider.kind", "definition");
properties.set("pdr.workflow.provider.type", "release-device");
context->registry().registerService(
    "pdr.workflow.definition.release-device",
    new ReleaseWorkflow, properties);
```

类型必须为小写 kebab-case，步骤名必须非空且不可重复。已有未结束实例时，定义服务即使从注册表注销，Runtime 也会保留其引用，避免正在执行的流程失去实现。

## 调用与配置

通过 OSP 注册表获取 `pdr.service.workflowRuntime`，转换为 `WorkflowRuntimeService` 后调用 `startWorkflow`、`signalWorkflow`、`resumeWorkflow`、`cancelWorkflow`、`workflow` 或 `workflows`。

```properties
pdr.workflow.schedulerEnabled = true
pdr.workflow.schedulerIntervalMilliseconds = 100
pdr.workflow.schedulerJitterMilliseconds = 0
# 默认值为该 Bundle 的持久目录/instances.sqlite
# pdr.workflow.database = ${application.dir}data/workflows/instances.sqlite
```

以上三个 scheduler 键由 `workflow-scheduler` 事务参与者精确认领，可通过
ConfigurationRuntime 在线原子修改；数据库路径和其他未声明动态语义的键不会被假装热更新。

外部项目只实现定义时：

```cmake
find_package(PocoDDSRuntime CONFIG REQUIRED COMPONENTS WorkflowAPI)
target_link_libraries(my_workflow_bundle PRIVATE PocoDDS::WorkflowAPI)
```

需要自行托管状态机和 SQLite 存储时才请求 `WorkflowCore`。

## 当前边界

- v1 在单 Runtime 进程内串行化步骤状态变更，不提供分布式抢占和多节点 leader election。
- Workflow Runtime 只提供 OSP 服务接口；HTTP/DDS/CLI 是可独立部署的入口适配器，不应并入核心或 `SystemMonitoring.cpp`。
- 数据库存储的是 workflow 输入和事件载荷，调用方不得写入明文密钥；后续应通过独立 `SecretProvider` 传递密钥引用。
