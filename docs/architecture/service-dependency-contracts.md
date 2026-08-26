# Service 依赖契约与 Readiness 传播

## 解决的问题

OSP `Require-Bundle` 负责 Bundle 解析和启动前的硬依赖，但它不能回答以下运行期问题：

- 目标 Bundle 已经 Active，实际 Service 是否完成注册；
- Consumer 要求的 Service 版本是否匹配；
- 缺失的是 Provider、版本还是注册状态；
- 依赖是必需还是可选；
- 哪个 Bundle 拥有声明以及故障是否应阻断 Runtime Readiness。

Service Dependency Runtime 补充这一层，不替代 OSP Bundle 解析，也不接管业务 Service
生命周期。边界仍为：

```text
Bundle Manifest Require-Bundle   -> 代码装载和 Bundle 启动顺序
Bundle service-contracts.json    -> Service 版本、可用性和 Readiness
Consumer Bundle                  -> 实际 Service 获取、重绑定和业务降级策略
```

## 去中心化声明

每个 Bundle 在自己的资源根目录放置 `service-contracts.json`。Owner 总是由承载该资源的
Bundle symbolic name 推导，JSON 不能自行声明 Owner，因此一个团队不能替另一个团队伪造
Provider 或 Requirement。

```json
{
  "schemaVersion": 1,
  "provides": [
    {
      "contract": "example.temperature",
      "version": "1.2.0",
      "serviceName": "example.service.temperature"
    }
  ],
  "requires": [
    {
      "contract": "pdr.scheduling",
      "versionRange": "[1.0.0,2.0.0)",
      "required": true,
      "minimumProviders": 1
    }
  ]
}
```

Bundle spec 必须包含 `<files>bundle/*</files>`。完整格式由
`contracts/schemas/service-contracts.schema.json` 约束：每个文档最多声明 128 个 Provider
和 128 个 Requirement；Service 版本使用数字 `major.minor.patch`；范围支持精确版本或
`[lower,upper)` 形式。

## Provider 判定

Provider 只有同时满足以下条件才是 `ready`：

1. 声明它的 Bundle 状态为 Active；
2. `serviceName` 已存在于当前进程 OSP Service Registry；
3. Service 注册属性 `pdr.bundle` 等于声明 Bundle，阻止同名 Service 冒充 Owner；
4. 可选属性 `pdr.service.readiness` 为 `ready`。

Provider 可以注册 `pdr.service.readiness=degraded` 或 `unavailable` 及
`pdr.service.readiness.detail`。如果原地修改 ServiceRef 属性，OSP 不会产生注册事件；此时
Provider 应重新注册 Service，或调用 `ServiceDependencyRuntimeService::refresh()`。

## Requirement 状态

| 状态 | 含义 | 必需依赖对 Readiness 的影响 |
|---|---|---|
| `satisfied` | 满足版本范围的 Ready Provider 数达到 `minimumProviders` | 无 |
| `missing` | 没有任何 Bundle 声明此 Contract | 阻断 |
| `versionMismatch` | 有 Provider，但版本均不匹配 | 阻断 |
| `providerDegraded` | 版本匹配，但 Provider 声明降级 | 阻断 |
| `providerUnavailable` | 版本匹配，但 Bundle 未 Active、Service 未注册或 Owner 不符 | 阻断 |

可选 Requirement 仍保留完整状态与诊断，但不会使 `/health/ready` 返回 503。格式错误、未知
字段、重复声明和非法范围属于声明错误，会独立阻断 Readiness，避免错误配置被静默忽略。
单个 Bundle 文档采用 fail-closed 解析：文档任一条目无效时，该 Bundle 的全部声明都不进入
有效模型。

停止状态的 Consumer 仍保留 Requirement，用于下一次启动准入，但不计入进程 Readiness。
因此“Consumer 当前未运行”和“Consumer 启动后依赖不满足”是两个独立结论，不会互相污染。

## 生命周期准入与影响分析

OSP Core 提供通用 `osp.bundleLifecycleGuard` 扩展点，`BundleLoader` 在任何入口实际启动或停止
Bundle 前统一调用它。Service Dependency Runtime 注册默认策略：

- 启动 Consumer 前，必需 Requirement 不满足或自身声明无效时拒绝启动；可选依赖只产生警告；
- 停止 Provider 前，模拟该 Provider 全部 Service 不可用；若会使当前 Active Consumer 丢失
  已满足的必需 Contract，则拒绝停止；
- 存在其他 Ready Provider 且仍满足 `minimumProviders` 时允许停止；
- 已停止的 Consumer 不阻断 Provider 停止；Runtime 整体关机仍按 Consumer → Provider 顺序完成。

拒绝使用稳定代码 `PDR-BUNDLE-DEPENDENCY-START_BLOCKED` 或
`PDR-BUNDLE-DEPENDENCY-STOP_BLOCKED`。该守卫位于 BundleLoader，而不位于某个 Web 管理入口，
所以 Web、CLI、测试或插件内部触发的生命周期操作采用同一策略。未注册守卫时，OSP 保持原有
行为，其他部署也可以注册不同策略实现。

## 运行时接口

- OSP Service：`pdr.service.serviceDependencyRuntime`
- 管理 API：`GET /api/v1/service-dependencies`
- 影响分析：`GET /api/v1/service-dependencies/impact?action=start|stop&target=<bundle>`
- 过滤：`owner`、`contract`
- 权限：Management Bearer 的 `resource.read`
- Health Contributor：`service-dependencies`

API 返回原子 generation、Provider、Requirement、匹配版本、阻塞数量和声明错误，不返回
配置值、令牌或 Service 对象地址。模型在 Bundle 安装/启动/停止/失败/卸载以及 Service
注册/注销时自动刷新。

影响分析接口无副作用，返回 `allowed`、结构化 blocker/warning 和受影响 Consumer。它适合在
部署、升级或维护界面中先预检；实际操作仍会由 BundleLoader 再次强制检查，避免“预检后状态
变化”造成 TOCTOU 绕过。

## 多人协作规则

1. Provider 团队拥有 Contract 名、实现版本和 Service 注册名。
2. Consumer 团队只在自己的 Bundle 声明版本范围、必需性和最小 Provider 数。
3. Contract 的不兼容修改必须提升主版本；Consumer 不应使用无上界范围接受未知主版本。
4. `satisfied` 证明 Service 可发现，不证明 Consumer 已实现运行期重绑定；需要在线重启
   Provider 的 Consumer 仍须使用 ServiceListener 或等价 Port 实现 detach/attach。
5. `Require-Bundle` 继续用于必须在 Activator 启动前存在的代码依赖；不要仅靠 Service
   Contract 解决动态库装载问题。
6. 运维工具应先调用 impact API 展示影响，但不能把预检结果当作执行授权；最终准入由
   BundleLoader 在状态变更点重新计算。

仓库内生产 Bundle 还必须通过
[生产 Service 契约图与兼容门禁](../development/service-contract-graph.md)。该门禁扫描完整
`services/` 图并固定已发布 Provider 基线，防止只运行某个 Consumer fixture 时漏掉其他团队的
版本迁移、Service 名冲突或必需依赖环；它不替代这里描述的动态 Registry/readiness 判断。

直接停止被依赖的 Provider 会被守卫拒绝。需要维护时使用
[Bundle 事务式排空与恢复](lifecycle-maintenance.md)，由 Lifecycle Runtime 先排空 Active
Consumer、等待在途工作，再停止 Consumer 和 Provider，并在失败时逆序回滚。

该能力由独立平台核心和 `pdr.service.serviceDependencyRuntime` Bundle 提供，不依赖
`SystemMonitoring.cpp`。
