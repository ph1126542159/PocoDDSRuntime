# Bundle 事务式排空与恢复

## 目标与边界

Service 依赖守卫会拒绝直接停止仍被 Active Consumer 依赖的 Provider。Lifecycle Runtime 在此
基础上提供受控维护事务：先停止接收新业务并等待在途工作结束，再按依赖方向停止，失败时逆序
回滚。它只编排当前 Runtime 进程内的 Bundle，不替代外部进程编排、数据库迁移或跨主机协调。

```text
预检 Provider 停止影响
  -> Consumer 全部 quiesce，拒绝新请求并等待 in-flight=0
  -> 停止 Consumer
  -> 再次计算依赖影响，防止 TOCTOU
  -> 停止 Provider

恢复：启动 Provider -> 按停止顺序的逆序启动 Consumer
失败：按已完成步骤逆序回滚
```

Lifecycle Runtime 会递归展开 Active Consumer 依赖链：最深层 Consumer 先停止，恢复时反向
启动；检测到活动依赖环时 fail-closed，因为守卫下无法安全地逐个停止循环成员。只要任一
Active Consumer 没有注册排空参与者，事务就在改动 Bundle 状态前 fail-closed。不会
通过强制停止绕过 `BundleLifecycleGuard`。排空超时范围为 10~30000 ms，所有 Consumer 共享同一
总期限，不会为每个参与者重新计算完整超时。

## 组件职责

| 组件 | Owner | 职责 |
|---|---|---|
| `PocoDDS::LifecycleCore` | 平台团队 | `DrainGate`、RAII 在途 Lease、超时排空与恢复 |
| `PocoDDS::LifecycleAPI` | 平台团队 | OSP 排空参与者和维护 Service 接口 |
| `PocoDDS::LifecyclePersistence` | 平台团队 | SQLite WAL/FULL 计划日志、序列和跨重启幂等 |
| `pdr-lifecycle-store` / `pdr.py lifecycle` | 运维工具团队 | 离线完整性检查、有界 JSON 导出和一致性备份 |
| 业务 Bundle | 各业务团队 | 在完整业务操作期间持有 Lease，注册自己的参与者 |
| `pdr.service.lifecycleRuntime` | Runtime 团队 | 发现影响、编排、二次校验、回滚、API 和健康状态 |
| Service Dependency Runtime | 契约治理 | 依赖图、启动/停止准入和最终执行点守卫 |

WorkflowRuntime 和 OutboxRuntime 是首批参与者。新团队不需要修改 Lifecycle Runtime 的中央
列表；参与者按 OSP Service 属性动态发现。

## 业务 Bundle 接入规则

1. Bundle 内部持有一个 `DrainGate`，每个同步请求、异步任务和调度回调在访问业务状态前调用
   `tryEnter()`，并让返回的 Lease 覆盖完整在途生命周期。
2. Gate 不接受新 Lease 时，对外请求返回明确的“正在排空”错误；周期任务直接跳过本轮，不能
   在排空后重新提交后台工作。
3. 注册 `DrainParticipantService`，Service 名为
   `pdr.lifecycle.drainParticipant.<bundle-symbolic-name>`，并设置
   `pdr.lifecycle.participant=true` 和 `pdr.bundle=<owner>`。
4. Bundle 卸载时先注销参与者，再取消并等待中央调度任务，最后调用 `closeAndWait()`；只有
   Lease 全部释放后才能销毁业务 Service。
5. `quiesce()` 必须有界且可重复，`resume()` 必须无异常；参与者 Owner 必须与实际 Bundle
   symbolic name 一致，不能代理其他团队的资源。

安装后消费者可只依赖核心门：

```cmake
find_package(PocoDDSRuntime 0.1 CONFIG REQUIRED COMPONENTS LifecycleCore)
target_link_libraries(my_bundle_core PRIVATE PocoDDS::LifecycleCore)
```

需要注册 OSP 参与者时改用 `LifecycleAPI`。
需要独立检查或维护计划数据库时使用 `LifecyclePersistence`；业务 Bundle 不应直接修改 Runtime
拥有的日志。

## 管理 API

- 查询：`GET /api/v1/lifecycle-maintenance`，权限 `resource.read`；可用 `planId` 过滤。
- 排空：`POST /api/v1/lifecycle-maintenance`，权限 `bundle.manage`，请求体
  `{"action":"drain","target":"pdr.service.schedulerRuntime","timeoutMilliseconds":5000}`。
- 恢复：同一 POST，正文
  `{"action":"restore","planId":"maintenance-1"}`。
- 崩溃恢复重试：`{"action":"recover","planId":"maintenance-1"}`，仅接受
  `drainRecoveryPending` 或 `restoreRecoveryPending`。
- POST 必须携带合法 `X-PDR-Request-Id`。计划、完整步骤和请求结果写入 SQLite；同 ID、同输入
  即使跨 Runtime 重启也返回原结果，同 ID、不同输入拒绝。

计划增加 `draining`、`restoring`、`drainRecoveryPending`、`restoreRecoveryPending` 状态，并记录
创建/更新时间和恢复次数。Runtime 在 `systemStarted` 后恢复中断事务：中断的 restore 完成为
`restored`；中断的 drain 恢复原 Active 拓扑并标记 `rolledBack`。恢复仍不完整时 Readiness
降级，错误码为 `PDR-HEALTH-LIFECYCLE-RECOVERY_PENDING`；普通回滚不完整继续使用
`PDR-HEALTH-LIFECYCLE-ROLLBACK_INCOMPLETE`。

成功完成的 `drained` 计划就是 Runtime 内唯一的 durable desired-stopped 状态。Lifecycle Runtime
以 `005` 启动级别先于所有可管理业务 Bundle 加载日志，对 Provider 和完整 Consumer 闭包设置
auto-start block，并注册独立的 desired-state 生命周期守卫；因此完整 Runtime 重启不会擅自恢复
业务拓扑。只有携带幂等请求 ID 的显式 `restore` 才会先解除该计划的阻止，再按
Provider → Consumer 顺序恢复。`restoreRolledBack` 同样保持停止，防止失败恢复后下一次重启意外启动。

只有真正中断的 `draining` / `restoring` 才进入 crash recovery：前者恢复原 Active 拓扑并标记
`rolledBack`，后者完成恢复并标记 `restored`。多个维护计划共享 Bundle 时按 plan ID 引用计数，
恢复一个计划不会误解除另一个计划拥有的停止意图。直接调用 Bundle start 绕过维护 API 会收到
`PDR-BUNDLE-DESIRED-STATE-STOPPED`。

## 当前限制与后续演进

SQLite 保留最近 128 条已闭合计划、全部仍为 `drained`、`restoreRolledBack` 或待恢复的未闭合计划，以及最近 256
条幂等结果；单进程最多同时保留 64 个未闭合维护窗口。数据库路径带操作系统级独占租约，
防止两个 Runtime 对同一持久化计划重复执行；残留 `.lock` 文件本身不代表仍被占用。启动还会
执行 SQLite `quick_check`。数据库文件损坏、磁盘不可写、租约冲突时，Lifecycle Bundle 保持在
admission-only 降级模式：所有可管理 Bundle 继续 auto-start blocked，组合守卫拒绝直接启动，
Readiness 返回 503 并报告 `PDR-HEALTH-LIFECYCLE-DESIRED-STATE-UNAVAILABLE`，但 Liveness 和诊断
入口仍可用。系统不会静默降级为内存事务。该日志只协调单个 Runtime 进程内 Bundle；多 Runtime、
跨主机一致性和数据库迁移仍需更高层编排器。

LifecyclePersistence 还暴露 `openExisting()`、`snapshot()`、`verifyIntegrity()` 和 `backupTo()`；
检查模式启用 SQLite `query_only`，备份使用 `VACUUM INTO` 获取包含 WAL 已提交内容的一致性快照，
并对目标再次执行完整数据库和负载校验。所有离线操作复用相同独占租约，不能与 Runtime 并发。

该能力由独立 lifecycle 平台库和 Runtime Bundle 提供，不依赖也不修改
`SystemMonitoring.cpp`。
