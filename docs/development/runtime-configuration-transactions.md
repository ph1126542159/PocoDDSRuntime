# Runtime 事务式配置热更新

`pdr.service.configurationRuntime` 为同一 Runtime 内的多个 Bundle 提供两阶段配置提交。
它补充离线 `pdr project config plan/preflight/apply/recover`：离线工具负责产品配置分层和发布，Runtime
服务负责已启动组件的原子切换、版本冲突、幂等重试和崩溃恢复。

离线 `preflight` 会生成带 SHA-256 自校验的无副作用证据；journal v3 使用持久原子写，并在
未完成事务恢复前拒绝其他操作者提交，防止跨进程配置覆盖竞态。
项目策略还可按 JSON Pointer 将安全、身份等路径标为高风险；离线 `apply` 只有在短期请求的
M-of-N Ed25519 审批同时满足人数、角色与发起人分离后才进入两阶段提交。
离线事务终态还写入带 actor、previous-record SHA-256 和持久 head 的审计链；计划和候选配置
使用事务私有快照，避免共享构建文件被后续协作者覆盖后破坏恢复。独立审计身份可用
`project config audit-checkpoint` 对已验证链生成 Ed25519 签名锚，再由部署门禁用
`verify-audit-checkpoint --state-dir ...` 证明该序列仍是当前链前缀。

## 边界

| 组件 | 职责 |
|---|---|
| `ConfigurationValidator` | 对完整候选配置执行全局规则校验 |
| `ConfigTransactionAPI` | 快照、请求、结果、参与者和 Runtime 服务契约 |
| `ConfigTransactionCore` | 两阶段提交、拓扑排序、回滚、幂等和 SQLite 日志 |
| `ConfigurationPreflightRuntimeService` | 无副作用预演、受影响键和参与者顺序 |
| `ConfigurationParticipantCatalogRuntimeService` | 配置 Owner 前缀、执行依赖、注册代次和准入拒绝的只读状态 |
| Bundle 本地 `configuration-participants.json` | 声明该 Bundle 承诺注册的 Participant、Service 名、Owner 前缀和排序依赖 |
| `pdr.service.configurationRuntime` | OSP 参与者发现、Preferences 原子快照激活 |
| 业务 Participant Bundle | 只校验、提交和回滚自己声明的配置前缀 |

事务层不修改 `SystemMonitoring.cpp`，也不把业务配置解析集中到管理 UI。进程内客户端通过
Runtime 服务提交完整候选快照；外部管理客户端使用独立的
`/api/v1/configuration-transactions` 适配器提交有限 patch。

## 参与者

参与者实现 `ConfigurationParticipantService` 并注册：

- `pdr.configuration.participant.kind=transactional`
- `pdr.configuration.participant.id=<descriptor.id>`

`ownedPrefixes` 使用点分配置键前缀。不同参与者的前缀不得重叠；变更无人认领时事务在预检前
直接拒绝。`after` 定义受影响参与者之间的提交顺序，回滚严格逆序执行。

```cpp
ParticipantDescriptor descriptor() const override
{
    return {"motion-control", {"robot.motion"}, {"safety-boundary"}};
}
```

Participant 必须按 `transactionId` 实现幂等的 `preflight`、`commit` 和 `rollback`。`preflight`
不得产生外部副作用；`rollback` 必须能处理“commit 已调用但响应尚未持久化”的情况。
参与者注销会先从 catalog 移除，再等待已取得的事务调用 lease 归零；因此 Bundle stop 返回时
不会遗留 preflight/commit/rollback 虚函数调用。不得从自己的事务回调中同步注销自身服务。

拥有配置 Participant 的 Bundle 必须把 `configuration-participants.json` 放进自身 `bundle/` 目录，
不在中央清单登记。例如：

```json
{
  "schemaVersion": 1,
  "participants": [{
    "id": "motion-control",
    "serviceName": "pdr.configuration.participant.motionControl",
    "ownedPrefixes": ["robot.motion"],
    "after": ["safety-boundary"]
  }]
}
```

ConfigurationRuntime 在 Bundle install/start/stop/fail/uninstall 和 Participant register/unregister 时
自动重算声明状态。Active Bundle 的 Service 名、`pdr.bundle` Owner、ID、`ownedPrefixes`、`after`
必须与实际已准入 Participant 完全一致；缺失或漂移都会阻断 readiness。Inactive Bundle 保留
`inactive` 诊断但不阻断 readiness，避免受控停止产生误报。非法文档、未知字段、重复 ID/Service、
超限文档和跨 Bundle 冲突一律 fail-closed。

提交或合并前使用同一套静态规则检查多个团队的声明，无需启动 Runtime：

```powershell
python tools/configuration_participant_contract.py `
  --declaration services/WorkflowRuntime/bundle/configuration-participants.json `
  --declaration services/OutboxRuntime/bundle/configuration-participants.json `
  --baseline contracts/configuration-participant-baseline.json `
  --report build/reports/configuration-participant-contract.json

# 单个组件也可通过统一 pdr CLI 固定其他团队声明
pdr component participant-contract-test `
  plugins/Diagnostics/bundle/configuration-participants.json `
  --provider-declaration contracts/providers/scheduler/configuration-participants.json `
  --baseline contracts/providers/scheduler/configuration-participant-baseline.json `
  --report build/reports/diagnostics-participant-contract.json
```

安装 SDK 还提供 `pdr_add_configuration_participant_contract_test()`。组件把自己的声明放在
`DECLARATION`，把协作团队发布的声明固定在 `PROVIDER_DECLARATIONS`，并可用 `BASELINE` 绑定已发布
Participant 表面，即可在独立 CTest 中提前阻断跨 Bundle 冲突、依赖环及兼容性破坏。
已发布 Participant 的 ID、Service 名和 Bundle Owner 不得直接修改；已发布前缀可以扩大但不能缩窄或
转移，已发布 `after` 依赖可以增加但不能移除。新增 Participant 不影响旧基线。基线更新属于发布审查，
不能用于掩盖未迁移的破坏。

`pdr new bundle/plugin` 模板 v8 已默认生成真实参与者、声明和该测试；
旧模板升级只生成空声明，避免在未改写产品 Activator 的情况下制造虚假 readiness 承诺。

## 配置键弃用与迁移

Participant 前缀稳定并不代表其中每个键可以静默改名。需要 rename/remove 已发布键时，Owner Bundle
必须增加 `bundle/configuration-key-lifecycle.json`：

```json
{
  "schemaVersion": 1,
  "entries": [{
    "id": "PDR-CFG-0001",
    "participantId": "motion-control",
    "operation": "rename",
    "sourceKey": "robot.motion.periodMs",
    "replacementKey": "robot.motion.periodMilliseconds",
    "deprecatedSince": "0.1.0",
    "removalAllowedFrom": "1.0.0"
  }]
}
```

`sourceKey` 和非空 `replacementKey` 必须都在同一 Participant 的 `ownedPrefixes` 内；`remove` 的
`replacementKey` 必须为 `null`。最早移除版本必须位于首次弃用后的主版本，替代图不得成环。工具还可
把产品 `config/migrations/vN-to-vN+1.json` 作为输入，要求每个 rename/remove 与 Owner 声明完全匹配：

```powershell
pdr component key-lifecycle-test `
  services/MotionRuntime/bundle/configuration-key-lifecycle.json `
  --participant-declaration services/MotionRuntime/bundle/configuration-participants.json `
  --migration products/Robot/config/migrations/v1-to-v2.json `
  --runtime-version 0.1.0 `
  --report build/reports/motion-key-lifecycle.json
```

发布审查把条目快照写入 `contracts/configuration-key-lifecycle-baseline.json`。候选版本在
`removalAllowedFrom` 之前删除条目、改变 source/replacement/Owner/Participant，或把移除窗口提前都会
失败；达到允许版本后才可删除已发布条目。报告分别绑定候选输入集合和基线 SHA-256。

安装 SDK 的 `pdr_add_configuration_key_lifecycle_contract_test()` 提供相同门禁。Runtime 自动发现该
Bundle 资源，并在 `/api/v1/configuration-participants` schema v4 返回生命周期 generation、Owner、
替代键、版本窗口及脱敏问题。Active Bundle 的越权/非法声明降级 readiness；Inactive Bundle 只保留
诊断。Runtime 不自动重写 Preferences，实际值迁移仍由经过计划、审批、预检和回滚保护的产品配置
事务执行。

## 提交流程

1. 客户端读取当前 `generation`，可先用相同候选值执行 `preflight`。
2. 客户端提交 `requestId + expectedGeneration + 完整候选值`；正式提交不信任旧预检，重新执行全部检查。
3. Runtime 校验候选快照、SHA-256 摘要、敏感值和配置所有权。
4. 受影响参与者按拓扑顺序全部 `preflight`。
5. 每次调用 `commit` 前先把 `commitAttempted` 写入 SQLite WAL。
6. 所有参与者成功后，Preferences 使用同一对象原子替换完整快照。
7. 快照和事务状态在一个 SQLite 事务内提交。
8. 任一步失败时恢复旧 Preferences，并逆序回滚所有已尝试参与者。

相同 `requestId` 和相同输入返回原事务结果；相同 ID 配不同输入会拒绝。过期
`expectedGeneration` 不会覆盖新配置。

## 管理 API

- `GET /api/v1/configuration-transactions?historyLimit=20`：只返回 generation、digest、参与者和
  带 principal 的事务历史，不返回配置值。
- `POST /api/v1/configuration-transactions`：要求 `X-PDR-Request-Id`，请求体为
  `expectedGeneration + changes`；最多 128 个字符串键值、1 MiB。
- `POST /api/v1/configuration-transactions/preflight`：使用相同鉴权、请求头和请求体，只返回
  当前 generation 下的全局校验、逐键 capability、受影响键、参与者顺序和拒绝原因；不写事务历史、
  不替换 Preferences，也不调用 Participant `commit/rollback`。
- `GET /api/v1/configuration-participants`：返回按 ID 排序的 Participant、`ownedPrefixes`、`after`、
  尚未注册的排序依赖 `unresolvedAfter`、`registrationGeneration`，以及每次成功 attach/detach 都推进的
  目录 `generation` 和完整拓扑摘要；同时返回独立的 `admissionGeneration`、有界脱敏
  `rejectedParticipants` 和 `admissionOverflow`，以及 `expectationGeneration`、`expectationsReady`、
  `declaredParticipants` 和脱敏 `declarationIssues`。不返回配置值、对象标识或原始异常文本。

服务端把 patch 合并到当前完整快照后再运行全局校验和两阶段提交。Patch 自身的稳定摘要用于
幂等身份，所以即使之后已有新 generation，重放旧请求也只返回旧结果，不会重新覆盖当前配置。
HTTP 主体先要求 `configuration.manage`，TransactionEngine 再逐键要求
`configuration:write` capability，形成身份权限与资源权限两层门禁。

预检结果是时间点证据，不是执行授权。generation 或 Participant 拓扑在预检后发生变化时，
正式提交会返回冲突或重新计算所有权；预检通过不能绕过正式提交的校验。`changed=false` 表示候选
与当前快照一致，也不会创建空事务记录。

多人协作时，Owner 团队应以参与者目录确认自己拥有的键前缀，Consumer/运维工具应把目录
`generation + digest` 当作时间点观察值。同一个 Participant 内部彼此覆盖的前缀、跨 Participant
前缀重叠、重复 ID，以及新注册后形成的完整 `after` 环都会在 attach 阶段拒绝，失败的 attach 不推进
目录 generation。Participant 可以先于排序前驱注册，此时 `unresolvedAfter` 明确显示缺口；它只表示
相对执行顺序尚无对应节点，不等同于 Service 可用性依赖。Bundle 注销会先从目录移除并推进
generation，再等待在途事务 lease 归零。目录快照不替代正式配置提交的所有权检查。

Participant 的 Service 类型、descriptor、注册属性、Owner 前缀或依赖图不合法时，注册拒绝不再只写日志：
ConfigurationRuntime 记录稳定准入错误码，`configuration-participant-admission` Health contributor 进入
`degraded`，因此 `/health/ready` 返回 503 而 `/health/live` 仍保持存活语义。相同拒绝不会反复推进
`admissionGeneration`；受影响 Service 注销并以合法契约重新注册后，拒绝记录清除、readiness 自动恢复。
最多保留 128 条脱敏记录，容量溢出保持 fail-closed，需修复注册风暴并重启 ConfigurationRuntime。
即使 Participant 从未尝试注册，Active Bundle 的本地声明仍会产生
`participant-required-missing`；已注册但 Owner、Service 名、前缀或依赖漂移则产生
`participant-declaration-mismatch`。这补齐了仅靠注册失败日志无法发现“完全缺失 Owner”的盲区。

例如只允许调度运维主体调整 Workflow 节拍，而不授予数据库路径或其他业务配置：

```json
{
  "effect": "allow",
  "principal": "schedule-operator",
  "resourceKind": "configuration",
  "resource": "pdr.workflow.scheduler*",
  "actions": ["read", "write"]
}
```

## 崩溃恢复与安全

启动时，generation 1 的数据库快照允许由新的启动配置重新建立；一旦产生已提交 generation 2+
快照，持久快照成为 Runtime 热更新的权威覆盖层。未完成事务不会推进当前 generation。

若 Runtime 在 commit 中断，记录进入 `recovery-pending`，等待所有 `commitAttempted` 参与者重新
注册后再逆序回滚。缺少参与者时不会假装恢复成功。

键名包含 `password`、`secret`、`token` 或 `privateKey` 的变更只接受空值或
`env://ENVIRONMENT_VARIABLE`；以 `Environment` 结尾的现有配置键也接受裸环境变量名称。
SQLite 恢复日志保存完整内部快照，但 Runtime 对外历史只返回
generation、SHA-256 摘要、principal、变更键、参与者和状态，不返回配置值；数据库文件必须使用操作系统
ACL 限制为 Runtime 服务账户可读。

默认数据库位于 Bundle 的持久目录，也可配置：

```properties
pdr.configurationRuntime.database = C:/ProgramData/PocoDDS/configuration/transactions.sqlite
```
