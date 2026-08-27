# Team Contract Adapter Runtime SDK

`tools/team_contract_adapter_runtime.py` 是所有外部进程 Team Contract Adapter 的公共宿主边界。目前
Registry Leader Backend、Secret Provider、Artifact Store 和 Backend Config Resolver 都通过它启动适配器。
各团队仍独立拥有自己的请求/响应 schema、身份、scope 和业务一致性规则；公共层只负责不能分叉的进程安全语义。

## 分层边界

| 层 | 统一职责 | 不负责 |
|---|---|---|
| Adapter Runtime | 配置与制品 SHA 固定、无 shell 启动、最小环境、超时、响应上限、stderr 策略、JSON 对象边界、能力策略与稳定摘要 | CAS、Secret 版本选择、Artifact 内容校验、Backend scope |
| 协议宿主 | request/response 精确字段、身份匹配、授权 scope、业务不变量和失败分类 | 子进程生命周期细节 |
| Adapter 实现 | 对接 etcd、Vault、对象存储或本机参考后端 | 绕过宿主验证或直接写共享证据 |

这样新增适配器时只需要实现协议，不需要重新发明超时循环、临时文件、环境复制和输出读取。公共层改变属于所有
Adapter 团队的兼容面，必须运行四类集成测试和 PDR-REC-0037；单个协议变化仍由对应 Owner 的测试选择。

## 安全默认值

- 使用参数数组直接启动进程，禁止 shell 拼接。
- 子进程只获得 `SystemRoot/WINDIR`、显式必需变量及可选 allowlist；不会继承整个宿主环境。
- 必需变量缺失时在启动前失败；可选变量只在存在时传递，适合 Secret 双版本分阶段投放。
- stdout 写入临时文件并在进程运行期间检查字节上限，避免先把攻击者输出装入内存。
- 超时后终止并等待子进程，任何返回路径都不会留下失控 Adapter。
- stderr 默认脱敏。只有不处理凭据的兼容 Adapter 才能显式 `expose_stderr=True`，并且最多读取 1024 字节。
- 返回内容必须是非空、限长 JSON object；协议宿主随后继续做精确字段和身份校验。
- Capability SHA 只绑定 Adapter 身份、实现 ID、协议版本和能力集合，不包含随机 `requestId`。

## 新 Adapter 接入

1. 定义独立产品 ID、request/response、capability request/manifest schema 和 Owner。
2. 配置中固定 executable、adapter 及所有辅助制品 SHA，声明环境 allowlist、超时与响应上限。
3. 使用 `regular_pinned_file`/`revalidate_artifacts` 在每次调用前重校验制品。
4. 使用 `isolated_environment` 构造子进程环境；秘密来源必须放在明确的可选或必需列表中。
5. 使用 `invoke_json` 执行，再由协议宿主验证 request ID、Adapter ID、operation 和业务字段。
6. 使用 `enforce_capability_policy` 和 `capability_digest` 生成可重放的能力证据。
7. 增加独立故障测试、安装 SDK 实际调用以及恢复矩阵 marker，不能只做配置生成测试。

公共运行时故障测试覆盖制品漂移、环境泄露、缺变量、挂起、输出洪泛、非法 JSON、stderr 泄露、能力缺失和
随机 request ID 摘要漂移。它证明宿主边界行为，不替代远程 etcd/Vault/KMS/对象存储的生产验收。

## Manifest 与 Catalog 自动发现

`team_contract_adapter_catalog.py` 在公共执行边界之上增加声明式发现层。每个 Adapter 发布一个
`PocoDDSRuntimeTeamContractAdapterManifest`，声明 Adapter 类型、身份、Owner、协议、Capability 产品 ID，
并以 SHA-256 固定其协议配置。Host 本地的 `PocoDDSRuntimeTeamContractAdapterCatalog` 再按摘要固定一组 Manifest。
因此新增符合边界的 Adapter 类型只需要交付配置、Manifest 和 Catalog 条目，不需要在 `pdr.py` 或 Runtime 中增加
中心注册分支。

Catalog 的通用权限刻意保持很窄：

- `adapter-catalog-list` 只列出已经重新验证全部传递 pin 的安全元数据。
- `adapter-catalog-check` 只调用 Manifest 声明的只读 Capability operation，并输出稳定摘要。
- CAS、Secret 解析、Artifact 读写、配置解析等业务 operation 仍必须经过对应协议宿主的精确 schema、身份、scope
  和业务不变量校验；Catalog 不是通用业务调用器。
- Catalog、Manifest、配置、可执行程序和辅助制品任一漂移都会失败关闭；重复 Manifest、Adapter 身份或
  `(adapterType, adapterId)` 组合同样拒绝。
- 操作证据不携带配置路径、环境值或原始 stderr。Manifest/Catalog 的最小示例位于安装 SDK 的
  `examples/team-contract-adapter-catalog/`。

PDR-REC-0038 使用两个核心代码从未登记过的合成 Adapter 类型，验证自动发现、类型过滤、只读能力探测、
传递 pin、重复/漂移拒绝、脱敏以及稳定 Capability 摘要。

## Catalog 原子激活与回滚

`team_contract_adapter_catalog_state.py` 独立拥有 Catalog 生命周期，不把写控制混入发现模块或协议 Host。Host
状态目录保存内容寻址 Catalog blob、逐代不可变 state 链和唯一可变的 `catalog-state.json` pointer：

- 写操作先获取 OS 持有的 `ProcessFileLease`，每次获取推进 durable fencing epoch。
- `--expected-generation` 提供 CAS；旧操作者不能覆盖已经激活的新 Catalog。
- `--operation-id` 在完整历史中唯一。完全相同的重试返回原结果，不同意图复用同一 ID 会失败关闭。
- 普通激活只接受更高的 Catalog generation；Catalog ID 不能在同一状态根中漂移。
- Catalog blob 和新 state 先以 create-only 方式持久化，最后才原子替换 pointer。
- 回滚只允许选择已验证历史 generation，重新复核全部传递 pin，并创建一个新的 activation generation；
  pointer 和审计历史不会倒退。
- `adapter-catalog-current-check` 在能力探测前后复核 pointer。探测期间发生切换时丢弃旧快照结果。
- `adapter-catalog-state-verify` 重放摘要链、转换规则、Catalog blob 和当前传递依赖。

该控制面只负责“哪份 Catalog 当前生效”和一致的只读观察，不自动启动、停止或替换协议 Adapter 业务进程。
长运行消费者应在自己的安全边界读取当前 pointer，并按既有协议 Host 生命周期完成协调。
PDR-REC-0039 覆盖并发写、旧 generation、幂等/冲突重试、降级、依赖漂移、探测中切换、显式回滚和状态篡改。

## 可恢复的 Catalog Reconciler

`team_contract_adapter_catalog_reconciler.py` 在原子状态层之上协调长运行消费者，但生命周期副作用仍由独立、
摘要固定的 Hook 实现。标准顺序为：

`prepare → bounded drain → atomic switch → activate → bounded health → commit`

每个副作用前先原子更新自摘要 journal；请求携带稳定 transaction ID、源/候选 Catalog generation 与 SHA，Hook
必须提供 `idempotent-operations`。因此进程在任一请求完成前后死亡，恢复命令都能安全重发并根据 Catalog 不可变
状态链消除 switch/rollback 的结果歧义。

- prepare、drain 或 switch 前失败：调用 `abort`，current Catalog 不变。
- switch 后 activate、health 或 commit 失败：先对 Catalog 创建指向精确源版本的新 rollback generation，再调用
  lifecycle `rollback` 恢复旧消费者。
- rollback Hook 失败：journal 保持 `rollback-failed`；恢复会识别 Catalog 已回退，只重试幂等 rollback Hook。
- health 使用配置内显式次数和间隔；未在预算内健康即失败，不存在隐藏无限重试。
- capability、请求、响应、journal、报告均不包含业务 payload 或秘密值；错误只保留稳定 diagnostic code。
- Reconciler 拥有独立全局 writer lease，Catalog pointer 的唯一写入仍由 Catalog State 层的 CAS/fenced lease 完成。
- `adapter-catalog-reconcile-revert` 可撤销已经 committed 的事务：复用 journal 内的精确源 identity，创建新的
  Catalog rollback generation，并通过同一 lifecycle Hook 恢复旧消费者；命令及 Hook 均可精确重试。

安装 SDK 提供文件状态参考 Hook 和配置生成器。PDR-REC-0040 会真实杀死 health 阶段协调进程、恢复提交，随后
注入持续不健康和首次 rollback Hook 失败，证明 Catalog 自动回退及二次恢复；同时验证已提交事务的显式撤销。

## 多 Host Canary/Wave Fleet 发布

`team_contract_adapter_catalog_fleet.py` 只负责跨节点发布策略，不接管节点连接、凭据或本地路径。固定的 Fleet
Plan 声明候选 Catalog、Node Executor 配置、最大并发数以及有序 wave；第一波必须是 `canary` 且失败预算为零。
Node Executor SPI 把每个 `deploy/revert/status` 请求映射到目标 Host，参考实现再调用该 Host 的真实 Reconciler。
因此 Fleet 不会绕过 prepare/drain/health/commit，也不会直接覆盖 Catalog pointer。

- 前一 wave 未完成或超出 `maxFailures` 时，后续节点不准入。
- wave 内按 `maxParallelNodes` 分批并发；每批发起前先持久化节点 `deploying` 状态。
- 协调器在节点已完成但响应未落 journal 时死亡，恢复会用稳定的 `rolloutId.nodeId` 重发，由节点 Reconciler
  消除结果歧义。
- 失败预算超限后只撤销已经 committed 的节点；按 wave 与节点严格逆序串行调用 Reconciler explicit revert。
- 从未准入的 pending 节点保持原 activation generation；节点自身健康失败产生的自动回退也不被 Fleet 重复撤销。
- Fleet plan、Executor config、node map、Reconciler、Catalog 和执行依赖逐层 SHA 固定；journal 自摘要，报告只保存
  稳定错误码和子报告 SHA，不保存远程凭据或 stderr。

公开命令为 `adapter-catalog-fleet-run/recover/status`。安装示例提供 node map、Executor config、Fleet plan
生成器以及基于真实 Reconciler 的参考 Node Executor。PDR-REC-0041 覆盖 Canary、并发 wave、协调器崩溃、
失败预算、后续节点隔离、逆序回退、精确重放、计划冲突、pin、篡改和脱敏。

## Wave Gate、观察窗口与人工控制

Fleet Plan v2 可额外固定独立 `Wave Gate` 配置，并要求每个 wave 声明：最短观察秒数、最大判定次数以及拒绝时
暂停或回滚。Gate SPI 只接收 rollout/wave 身份、候选 Catalog 摘要、观察起点和脱敏节点计数，返回
`pass/pause/fail`、稳定诊断码及证据 SHA；它不获得节点路径、Reconciler 配置、业务 payload 或凭据。

- `minimumObservationSeconds` 采用持久时间门槛。未到期时 journal 进入 `waiting` 并立即返回，不在进程中 sleep。
- Gate evaluation ID 由 rollout、wave 和 attempt 稳定派生。Gate 已落决定但响应丢失时，恢复重发同一 ID。
- `pause` 会阻止下一 wave；普通 `recover` 不能绕过。只有带 control generation CAS、唯一 operation ID、actor
  和 reason 的 `adapter-catalog-fleet-resume` 才能继续。
- `adapter-catalog-fleet-abort` 把暂停发布送入原有逆序回滚路径；从未准入的节点不改变。
- resume/abort 控制记录保存在自摘要 journal 中，精确重放幂等，冲突意图失败关闭。
- Plan v1 保持原有无 Gate 行为；Plan v2 的 Gate config、可执行程序和 Adapter 在协商及每次判定前重新验 SHA。

参考 `wave_gate_adapter.py` 只用于 SDK 和故障注入。生产 Gate 应通过同一协议对接 Prometheus、OpenTelemetry、
错误预算或人工审批系统；指标采集实现不进入 Fleet 核心，也不依赖 `SystemMonitoring.cpp`。PDR-REC-0042 覆盖
判定响应丢失、持久暂停、CAS resume、非阻塞观察窗口、abort、pin 漂移、journal 篡改和秘密脱敏。

## Fleet Control Authorizer 与可信 Principal

Fleet Plan v3 在 Wave Gate 之外固定独立 `Control Authorizer`。v2 的 `actor` 仍是兼容审计字段；v3 不再仅凭
调用方自报 actor 执行控制，而是在持有 Fleet writer lease、完成 generation CAS 后，把脱敏控制意图交给
摘要固定的 Authorizer：rollout/wave/Catalog 身份、operation ID、action、claimed actor、control generation、
Gate evidence SHA 和 reason SHA。原始 reason、节点路径、凭据及环境秘密不跨越该边界。

- Authorizer 必须协商 `deny-by-default`、幂等判定、Principal 绑定、脱敏意图与无秘密证据能力。
- `allow` 只有在返回 Principal 与 claimed actor 完全一致时有效；Principal 不匹配或适配器异常均失败关闭。
- allow/deny 都写入自摘要 `authorizationAttempts`；deny 不增加 control generation，也不改变暂停 rollout。
- authorization ID 由 rollout 与 operation ID 稳定派生。判定已落地但响应丢失时，重试必须返回原决定。
- 已拒绝 operation ID 不会因环境策略后来改成 allow 而获准；新审批必须使用新的 operation ID。
- 允许的 control 通过 authorization ID 与 evidence SHA 连接授权记录，再执行既有 resume/abort 状态机。

参考 `control_authorizer_adapter.py` 是文件型 SDK/故障注入实现。生产适配器应对接 IAM、短期签名审批、OPA 或
企业发布授权服务，并在自己的安全边界验证凭据；Fleet 核心不复制身份系统，也不依赖
`SystemMonitoring.cpp`。Plan v1/v2 保持兼容，PDR-REC-0043 覆盖默认拒绝、Principal 冒用、授权响应丢失、
拒绝持久化、控制回滚、pin、篡改和脱敏。

## 跨主机 Fleet State Store 与协调器接管

Fleet Plan v4 把权威 journal 从协调器本地目录迁到可插拔的远程状态边界：不可变 journal 写入现有 Artifact
Store，只有一个小型 State Pointer 写入现有 Registry Leader Backend。Pointer 的 `fencingToken/stateVersion`
通过线性一致 CAS 单调递增，并同时固定前一 Pointer SHA、当前 journal 自摘要、Artifact reference、最后写入的
coordinator ID 和全部配置摘要。

- Plan 只绑定 Backend/Artifact Store 的逻辑 ID 与配置 SHA，不记录主机本地配置路径；不同协调主机分别用
  `--state-backend-config`、`--artifact-store-config` 提供本机路径，并用 `--coordinator-id` 标识写入者。
- `--state-dir` 在 v4 中只是非权威本地 scratch；新协调器可使用全新的空目录读取同一远程 journal 并继续。
- 每次状态变化先上传内容寻址 journal，再 CAS Pointer。CAS 失败的孤立 blob 不可见；旧协调器不能覆盖新版本。
- CAS 响应丢失时，协调器读取当前 Pointer；只有 token、journal SHA 和 coordinator identity 全部吻合才判定成功。
- Pointer、journal、Backend/Store scope 或 pin 任一漂移，以及 blob 缺失/篡改，都会失败关闭。
- Node Executor、Wave Gate 和 Control Authorizer 继续使用各自稳定 operation/evaluation/authorization ID 消除
  CAS 竞争窗口内的重复副作用；远程状态层不获得节点凭据、业务 payload 或控制原文。

Plan v1-v3 的本地 journal 与进程 lease 保持兼容。PDR-REC-0044 覆盖双协调器接管、旧 writer fencing、CAS
响应歧义、不同 scratch 路径、Artifact 篡改、配置 pin 和安装 SDK。
