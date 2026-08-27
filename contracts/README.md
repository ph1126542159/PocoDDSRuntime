# PocoDDSRuntime 契约

本目录是跨入口契约的唯一文档入口：

- `schemas/component-template-state.schema.json`：生成组件的类型、模板版本、结构受管文件和业务所有文件边界。
- `schemas/component-template-transaction.schema.json`：组件模板采用、升级、备份和中断恢复日志。
- `component-templates/v1.json`：全部 12 类生成组件的冻结 v1 渲染指纹，防止旧模板被静默改写。
- `schemas/release-pipeline.schema.json`：框架发布和产品项目共用的哈希绑定阶段计划；可选 metadata 明确计划类型及自动/外部验收边界。
- `schemas/external-acceptance.schema.json`：候选、附件和可选约束绑定的外部验收；项目 SIL/HIL/长稳使用独立签名类型。
- `schemas/runtime-config.schema.json`：运行时配置类型、范围和必填项。
- `schemas/process-desired-state.schema.json`：受管子进程人工启停授权的版本化、SHA-256 自校验持久快照；提交协议先刷盘 `.new`，再原子切换 `.previous`/主文件并同步元数据，Runtime 重启恢复与损坏 fail-closed 共用该格式。
- `schemas/process-desired-state-lease.schema.json`：期望状态单写者租约的只读 Owner 元数据；锁是否生效由 OS 句柄/`flock` 决定，文件内容本身不构成锁。
- `schemas/runtime-schema-contract.schema.json`：Bundle Provider 发布的消息、事件、命令、配置和服务 Schema 信封。
- `schemas/schema-compatibility-catalog.schema.json`：冻结基线与当前候选的构建门禁目录。
- `schema-registry/`：不可变 Schema 基线、当前候选及 `pdr-schema-check` 兼容门禁输入。
- `schemas/framework-model.schema.json`：CMake 解析后的框架族、Host 模型、传输、能力和 WebUI 导航契约。
- `framework-components.json` 与 `schemas/framework-components.schema.json`：框架源码路径、逻辑 Owner、直接依赖、构建 Target 和 CTest label 的 fail-closed affected-only CI 契约；生产 Service 按治理、网关和通用服务团队分开建模。
- `schemas/framework-change-impact.schema.json` 与 `schemas/framework-ci-execution-evidence.schema.json`：受影响组件计划及其真实 CTest 执行证据；证据通过 SHA-256 绑定计划，不能挪用到另一组变更。
- `framework-recovery-matrix.json`、`schemas/framework-recovery-matrix.schema.json` 与 `schemas/framework-recovery-evidence.schema.json`：Host、Runtime、Process、Bundle、Service、Transport 和 Persistence 的故障注入场景、Owner、CTest 标签、超时、机器可观察断言，以及绑定测试命令、测试程序和共享运行库集合的 v2 执行证据。
- `repository-owners.json` 与 `schemas/repository-owners.schema.json`：逻辑 `team/...` Owner 到 GitHub 用户/组织 Team 的可审计映射，是生成 `.github/CODEOWNERS` 的唯一输入。
- `schemas/framework-dependency-boundary.schema.json`：生产源码跨组件头文件依赖报告；未声明直接依赖、公共头文件所有权冲突，以及通过相对/仓库路径直接包含其他组件私有头文件均阻断 CI。
- `schemas/framework-link-manifest.schema.json` 与 `schemas/framework-link-dependency-boundary.schema.json`：带 Profile 身份的 CMake 直接 target 链接和 include directory 清单及依赖报告；未归属 target、混合所有权、未解析内部表达式、跨组件私有目录暴露、Profile 错配和未声明组件边均阻断 CI。
- `schemas/framework-link-dependency-matrix.schema.json`：命名 Profile 链接门禁汇总；缺失、重复、意外 Profile 或任一失败报告都不能形成通过证据。
- `schemas/framework-component-build-groups.schema.json` 与 `schemas/framework-component-build-groups-validation.schema.json`：CMake 实际生成的独立组件聚合 Target 及其全量生产成员证据；漏收、跨 Owner 误收或目录/CMake 漂移均阻断 CI。
- `schemas/framework-build-execution-evidence.schema.json`：将变更影响计划、源修订与变更文件、CMakeCache、Target 图、组成员、依赖清单和真实构建命令绑定的执行证据与缓存身份。
- `schemas/sdk-public-surface-snapshot.schema.json` 与 `schemas/sdk-public-surface-compatibility.schema.json`：安装后公共头文件、导出 CMake target 和平台 ABI 的快照及比较报告契约。
- `sdk-deprecations.json`、`schemas/sdk-deprecation-catalog.schema.json` 与 `schemas/sdk-deprecation-policy.schema.json`：公共 SDK 表面的弃用公告、最早移除主版本、替代入口、Owner 和发布快照绑定契约；未经已发布公告的破坏性变更不能仅靠提升主版本放行。
- `schemas/sdk-header-self-containment-plan.schema.json` 与 `schemas/sdk-header-self-containment-evidence.schema.json`：每个已安装公共头文件独立翻译单元的全量编译计划和摘要绑定通过证据。
- `schemas/runtime-resource.schema.json`：Host → Runtime → Process → Bundle → Service 的作用域、所有权和生命周期所有者公共契约。
- `schemas/service-contracts.schema.json`：Bundle 本地 Service Provider、版本范围、必需/可选依赖和最小 Provider 数量契约；Owner 由承载 Bundle 推导，不能由文档伪造。
- `schemas/component-contract-conformance.schema.json`：组件、Consumer Service 契约和显式 Provider 契约摘要绑定的离线兼容报告；记录每个 Requirement 的匹配版本、数量、状态与阻断原因。
- `schemas/configuration-participants.schema.json`、`configuration-participant-baseline.json`、`schemas/configuration-participant-baseline.schema.json` 与 `schemas/configuration-participant-contract-report.schema.json`：Bundle 本地事务配置参与者声明、已发布 Participant 身份/Owner/配置前缀/执行顺序保证，以及联合多个团队声明生成的摘要绑定构建期检查证据；阻断重复 ID/Service、前缀覆盖、依赖环和未迁移的已发布表面破坏。
- `schemas/configuration-key-lifecycle.schema.json`、`configuration-key-lifecycle-baseline.json`、`schemas/configuration-key-lifecycle-baseline.schema.json` 与 `schemas/configuration-key-lifecycle-contract-report.schema.json`：Bundle 自有配置键的 rename/remove、替代键、首次弃用版本和最早移除主版本声明及已发布基线；聚合门禁把产品迁移操作与 Participant Owner/前缀及候选/基线摘要绑定，阻止跨团队改键、替代环、无公告删除和移除窗口到期前撤销声明。
- `schemas/team-contract-package-manifest.schema.json`、`schemas/team-contract-package-signature.schema.json`、`schemas/team-contract-trust-policy.schema.json`、`schemas/team-contract-package-lock.schema.json` 与 `schemas/team-contract-package-resolution.schema.json`：跨仓库团队将 Service、Participant、配置键生命周期声明及已发布基线封装为确定性、内容寻址契约包；Ed25519 签名和 SHA 固定的团队策略校验 Owner、包范围、有效期与撤销。消费方锁文件只保存身份和摘要，不保存开发机/密钥路径，离线解析拒绝路径穿越、符号链接、额外文件、摘要漂移、错包和非受信发布者。
- `schemas/team-contract-consumer-catalog.schema.json` 与 `schemas/team-contract-upgrade-impact.schema.json`：显式登记跨仓库 Consumer 对包角色的依赖及必跑 CTest 标签；锁升级预演在完整复核当前/候选签名证据后，阻断同版本漂移和已发布 Service、Participant、配置键生命周期破坏，输出摘要绑定的受影响 Owner/Consumer/测试路由。
- `schemas/team-contract-impact-execution-evidence.schema.json`、`schemas/team-contract-impact-approval-policy.schema.json`、`schemas/team-contract-impact-approval.schema.json` 与 `schemas/team-contract-impact-gate.schema.json`：把兼容升级报告与实际选中 CTest 命令、JUnit 结果、当前测试目录及每个受影响 Consumer Owner 的短期 Ed25519 批准绑定；策略固定批准人/key、公钥 SHA、有效期和撤销，拒绝失败/跳过/禁用测试、测试目录漂移、缺 Owner、重复批准人、过期或吊销批准。
- `schemas/team-contract-registry-pointer.schema.json`、`schemas/team-contract-registry-state.schema.json`、`schemas/team-contract-registry-operation.schema.json` 与 `schemas/team-contract-registry-resolution.schema.json`：跨团队签名契约包的不可变 Registry、状态 SHA 链、原子当前指针、通道 generation、晋级/回退记录及无包路径解析证据；staging/production 只能接收前置通道当前锁并绑定影响 Gate，拒绝同版本漂移、未发布包、降级、跳级和并发覆盖。
- `schemas/team-contract-runner-trust-policy.schema.json`、`schemas/team-contract-runner-attestation.schema.json` 与 `schemas/team-contract-runner-attestation-verification.schema.json`：独立于 Owner/发布者密钥的 CI Runner 签名证明，固定 repository、source revision、workflow/job/run 及 impact、执行、JUnit、CTest 程序/catalog/命令摘要；策略限制 Runner/key/repository/workflow、有效期和撤销。
- `schemas/team-contract-gate-authorization-policy.schema.json`、`schemas/team-contract-gate-authorization.schema.json` 与 `schemas/team-contract-gate-authorization-verification.schema.json`：发布授权服务重放完整 Gate 后签发的短时凭证，绑定 Gate 原始字节、候选锁、Runner 证明、Registry 与允许通道；staging/production 会独立验证授权密钥、策略 pin、范围、有效期和撤销状态。
- `schemas/team-contract-registry-access-policy.schema.json`、`team-contract-registry-access-policy-v2.schema.json`、`team-contract-registry-access-policy-trust-policy.schema.json` 与 `team-contract-registry-access-policy-activation.schema.json`：远程 Registry 的 bootstrap 访问策略、Ed25519 签名连续 revision、独立轮换密钥信任及原子激活证据；后继策略绑定上一策略原始 SHA、Registry/Policy ID、token 撤销和控制目录容量，拒绝无签名替换、跳 revision 与回退。
- `schemas/process-file-lease-status.schema.json`、`schemas/team-contract-registry-remote-lease-status.schema.json`、`schemas/team-contract-registry-remote-command.schema.json`、`schemas/team-contract-registry-remote-response.schema.json`、`schemas/team-contract-registry-remote-request-status.schema.json`、`schemas/team-contract-registry-remote-capacity.schema.json` 与 `schemas/team-contract-registry-remote-recovery*.schema.json`：跨机器 Registry 控制面协议；服务端按 principal 的 reader/publisher/promoter/rollback/auditor/operator 角色、package ID 和 channel scope 授权，客户端只上传摘要绑定制品字节，不传服务端路径。写请求强制 expected revision 与幂等 request ID；中断请求只能由 operator 绑定原请求 SHA 和观测 revision 后明确标记 aborted/uncertain；容量接口公开实际记录/字节用量并在写入前 fail-closed。Registry 写者与控制事务使用 OS 所有权租约、可观察 Owner 和持久 epoch，进程退出后无需删除锁文件即可安全接管；提交前 fencing 校验阻止已被新 epoch 取代的写者发布，HTTPS 为非 loopback 默认门禁。
- `schemas/team-contract-registry-remote-audit-*.schema.json`：远程请求 started/completed/recovered 状态迁移的不可变 SHA-256 链、当前 head、验证报告，以及由独立 Ed25519 审计方保存在控制目录外的签名检查点；分段归档用外部 `.pdraudit`、不可变注册 marker 与连续 base 保留历史前缀，只有显式、基线固定的 prune 才移除已逐字节验证的在线副本，请求和幂等响应仍保持在线可验证。
- `schemas/team-contract-registry-anchor-policy.schema.json`、`schemas/team-contract-registry-anchor.schema.json` 与 `schemas/team-contract-registry-anchor-verification.schema.json`：Registry 外部审计服务签名的 revision/state SHA 锚及验证报告；沿当前状态链证明锚点仍存在，从而发现整个 Registry 被回退为较旧但内部自洽副本。
- `schemas/team-contract-registry-recovery-manifest.schema.json` 与 `schemas/team-contract-registry-recovery-report.schema.json`：把完整 Registry 状态链、当前累计 package/lock blob、固定 trust policy 和精确当前 revision 的外部 Ed25519 anchor 封装为可携带 `.pdrregistry`；恢复要求介质 SHA、源端失效确认、外部操作审计和不存在的目标目录，禁止覆盖健康 Registry 或用旧锚签署未锚定的新尾部。
- `schemas/team-contract-registry-standby-*.schema.json`：由外部锚恢复点初始化和快进只读 Registry 热备；marker 固定 standby ID、已应用 revision/state、恢复介质 SHA、同步代次和上一 marker SHA。核心 publish/promote/rollback 路径直接拒绝 standby，同步要求停服确认、精确旧基线和候选链包含证明，并保留完整上一目录。
- `schemas/team-contract-registry-leader-*.schema.json` 与 `schemas/team-contract-registry-fencing-state.schema.json`：外部 Ed25519 Leader authority、最长 24 小时 grant 租约、单调 fencing token、不可变 grant 前驱链、本地 leader binding 与已观察 token 高水位；跨节点转移必须先签发无 Leader 的 fence grant，备节点只在 grant 精确匹配本地 revision/state 后晋升，Registry 指针提交前会再次读取外部 current grant 以拒绝竞态中的旧写者及权威文件回退。
- `schemas/team-contract-registry-leader-backend-*.schema.json`：Leader authority 的可插拔外部进程 SPI、能力请求/清单/协商报告与独立 Conformance 证据；schema v2 在存储访问前协商协议 major/minor 及原子 CAS、不可变 history、线性读取等语义能力，配置、可执行程序和适配器制品继续由 SHA 固定。旧 schema v1 可显式加载但不产生协商证据；新适配器团队从安装 SDK 的参考实现和公开验收命令独立开发。
- `schemas/team-contract-registry-leader-backend-migration*.schema.json`：后端迁移的在线历史同步、共享事务、实时阶段、pre-fence abort 与 fenced cutover 证据；只复制逐字节一致的不可变前缀。事务既可使用兼容的本地文件租约，也可复用能力协商后的 Leader Backend SPI，把 stateVersion/前驱摘要作为单调 CAS 链存入独立 file/etcd scope；预期 SHA 阻止过期操作者覆盖，可对账接纳中断后留下的固定 checkpoint。schema v3 使用内容寻址 Artifact 引用替代证据路径；schema v4 再用稳定 Backend Config Reference 替代 source/target 的主机配置路径。只有 source 仍是绑定可写 Leader 时允许终止；Fence 后必须完成切换或反向迁移。切换在 Registry lease 内复核后写 schema v3 binding；交换 source/target 即为同协议回滚，普通 renewal 仍不能换后端。
- `schemas/team-contract-artifact-*.schema.json`：独立 Artifact Store SPI 的固定配置、能力协商、Put/Get 请求响应与便携引用。适配器必须提供命名空间隔离、不可变幂等创建、内容寻址读取和写后读；配置、执行程序和适配器由 SHA 固定。引用仅携带 store、namespace、SHA-256、字节数和媒体类型，不携带本地路径；安装 SDK 提供文件参考适配器，远程对象存储由独立团队按同一协议实现。
- `schemas/team-contract-backend-config-*.schema.json`：跨主机 Backend Config Resolver SPI 的固定配置、能力协商、请求响应与稳定引用。共享事务只保存 resolver/config/backend/revision 身份；各主机独立固定 resolver、mapping 和本机 backend config，解析结果必须重新通过 backend scope、制品 pin 和能力协商。安装 SDK 提供本地映射参考适配器，mapping 明确禁止存储秘密值。
- `schemas/team-contract-secret-*.schema.json`：版本固定的 Secret Provider SPI、能力协商、租约响应与脱敏可用性报告。Backend schema v3 保留精确单版本引用；schema v4 使用有序 `versions`、显式 `fallbackUntil` 和最小剩余租约完成双版本轮换。解析值仅进入本次 Backend 子进程环境；配置、事务、证据、报告和日志不得保存值、摘要或长度。安装 SDK 的环境变量适配器只用于迁移和测试，生产适配器应对接 Credential Manager、Vault、云 Secret Manager/KMS 或 workload identity。
- `tools/team_contract_adapter_runtime.py`：Backend、Secret Provider、Artifact Store 与 Config Resolver 的公共外部进程宿主 SDK，统一无 shell 执行、制品重校验、环境隔离、超时、响应上限、stderr 脱敏、JSON 边界和稳定能力摘要。各协议仍独立拥有 scope、身份及业务不变量。
- `schemas/team-contract-adapter-manifest.schema.json`、`schemas/team-contract-adapter-catalog*.schema.json` 与 `tools/team_contract_adapter_catalog.py`：以摘要固定的 Manifest/Catalog 自动发现新增 Adapter 类型，并执行通用只读 Capability 检查；业务 operation 仍由各协议宿主校验，不在核心注册表或 Catalog 中分派。
- `schemas/team-contract-adapter-catalog-{pointer,state,state-operation,current,current-check,state-verification}.schema.json` 与 `tools/team_contract_adapter_catalog_state.py`：以 fenced writer lease、generation CAS、唯一 operation ID、不可变摘要链和原子 pointer 管理 Host 当前 Catalog；回滚复用历史固定内容但创建新 generation，探测中切换不会产生可接受的旧快照证据。
- `schemas/team-contract-adapter-catalog-reconciler-*.schema.json`、`schemas/team-contract-adapter-catalog-reconcile-*.schema.json` 与 `tools/team_contract_adapter_catalog_reconciler.py`：固定外部 lifecycle Hook，通过 durable journal 协调 prepare、drain、原子 switch、activate、有限 health、commit/abort/rollback；进程中断和 rollback Hook 失败均可幂等恢复，报告不保存业务 payload、秘密或原始 stderr。
- `schemas/team-contract-adapter-catalog-fleet-*.schema.json`、`tools/team_contract_adapter_catalog_fleet.py` 与 `tools/team_contract_adapter_catalog_fleet_state_store.py`：以固定 Fleet Plan 和 Node Executor SPI 执行零失败 Canary、有序 wave、失败预算及有界并发；Plan v4 可把不可变 journal 放入 Artifact Store，并以 Leader Backend 的 CAS/fencing Pointer 支持跨协调 Host 接管；超预算后停止准入并通过节点 Reconciler 严格逆序撤销 committed 节点。
- `schemas/team-contract-adapter-catalog-wave-gate-*.schema.json` 与 `tools/team_contract_adapter_catalog_wave_gate.py`：Plan v2 以独立能力协商 Gate 对每个 wave 执行有界 SLO/观察判定；长观察期非阻塞，pause 需带 CAS 与审计身份的 resume/abort，证据仅跨边界传递摘要。
- `schemas/team-contract-adapter-catalog-control-authorizer-*.schema.json` 与 `tools/team_contract_adapter_catalog_control_authorizer.py`：Plan v3 通过独立默认拒绝 Authorizer 把 resume/abort 绑定到认证 Principal；只发送脱敏控制意图和 reason SHA，allow/deny 证据进入自摘要 journal，拒绝不会改变发布状态。
- `schemas/team-contract-registry-leader-etcd-*.schema.json`：安装 SDK 的 etcdctl 生产适配路径、只读集群预检和一次性验收证据；至少三个 HTTPS endpoint、etcdctl/CA/客户端证书/私钥和命名空间均被制品摘要固定，Acceptance 把写前预检、正式 Conformance（同一事务内的 current compare、history create 和 current put）及写后预检的报告摘要绑定在一起。
- `schemas/team-contract-registry-drain-*.schema.json`、`schemas/team-contract-registry-remote-drain-*.schema.json`、`schemas/team-contract-registry-handoff-evidence.schema.json` 与 `schemas/team-contract-registry-handoff-trust-policy.schema.json`：旧主的持久 command admission drain、pending request 集合摘要、已观察 fence token、远程审计 head 及最长一小时的节点 Ed25519 交接证据；远程协议只允许 operator 以 Registry ID、精确 generation/revision/state 和 handoff ID 控制生命周期，客户端不接触服务端路径或签名密钥，精确重试返回原证据；跨节点 leader grant 必须绑定证据 SHA，篡改、过期、状态不一致、遗留 pending 或旧主未观察 fence 都会拒绝切换。
- `service-contract-baseline.json`、`schemas/service-contract-baseline.schema.json` 与 `service-contract-graph.schema.json`：已发布生产 Provider 表面及仓库级 Bundle Service 依赖图证据，阻止未迁移的主版本替换、全局 Service 名冲突和必需依赖环。
- `schemas/pdr-project.schema.json`：产品项目组合、机器人 Backend、组件路径、配置层和验收要求。
- `schemas/project-component.schema.json`：项目内 Module、Service、Bundle、Subprocess 等组件的
  ID、Owner、公共 CMake Target、隔离方式与显式依赖契约；项目同步按依赖拓扑组合并拒绝越层依赖。
- `schemas/project-config-capabilities.schema.json`：组件配置所有权、热更新能力、顺序依赖及无 shell 执行协议入口。
- `schemas/project-config-approval-policy.schema.json`、`project-config-approval-request.schema.json` 与 `project-config-approval-signature.schema.json`：按配置路径定义 M-of-N、必需角色、发起人分离、短期请求和 Ed25519 审批证据。
- `schemas/project-config-audit-record.schema.json`、`project-config-audit-head.schema.json` 与 `project-config-audit-verification.schema.json`：跨事务 hash-chain、持久 head、操作者、journal 终态绑定和离线验证证据。
- `schemas/project-config-audit-checkpoint.schema.json`、`project-config-audit-checkpoint-signature.schema.json` 与 `project-config-audit-checkpoint-verification.schema.json`：外部 Ed25519 审计锚、签名信封和当前链前缀验证证据。
- `schemas/project-config-status.schema.json`：团队交接所需的活动锁、事务发起人、待恢复 journal、审计健康和下一次提交就绪状态。
- `schemas/project-config-plan.schema.json`：当前配置、候选配置、能力清单、审批规则和变更参与者的摘要绑定计划。
- `schemas/project-config-transaction.schema.json`：私有计划/候选快照、预检、提交、逆序回滚、中断恢复和审计指针的事务日志契约。
- `schemas/project-template-state.schema.json`：项目脚手架版本、渲染上下文、受管和项目定制文件基线。
- `schemas/project-template-transaction.schema.json`：模板采用、升级、备份和中断恢复日志契约。
- `schemas/project-package-manifest.schema.json`：项目交付包内 payload、锁文件、配置和 SBOM 的摘要绑定。
- `schemas/release-trust-policy.schema.json`：发布允许密钥、有效期与吊销列表格式。
- `schemas/release-artifact-manifest.schema.json`：安装制品清单、SPDX SBOM 摘要和 Git/Builder/Profile/artifact-set 来源绑定。
- `schemas/plugin-trust-policy.schema.json`：插件发布者、允许命名范围、Ed25519 公钥、有效期和吊销契约。
- `schemas/bundle-repository-attestation.schema.json`：Bundle 仓库发布者、仓库身份、单调 rollout sequence、候选摘要，以及发布清单、SPDX SBOM、Git/Builder/Profile 来源的分离证明负载。
- `schemas/bundle-repository-trust-policy.schema.json`：Bundle 仓库允许发布者、密钥、仓库范围、有效期和吊销契约。
- `schemas/plugin-host-state.schema.json`：隔离插件宿主向 Runtime/Web 暴露的跨进程状态快照。
- `schemas/release-qualification.schema.json`：自动化测试、制品、Git 与外部验收的统一发行资格证据。
- `schemas/external-acceptance.schema.json`：目标板、物理协议、生产身份、现场网络和长稳的候选绑定验收证据。
- `schemas/external-approver-trust-policy.schema.json`：外部验收批准者、Ed25519 密钥、允许类型、有效期及吊销契约。
- `schemas/evidence-bundle.schema.json`：可移植发行证据 ZIP 内部文件、角色、大小和摘要清单。
- `schemas/release-pipeline.schema.json`：一键发行阶段、命令参数、超时和输入输出检查点契约。
- `openapi/runtime.yaml`：HTTP 管理接口契约入口。
- `GET /api/v1/devices`：当前活跃设备适配器的版本化清单。
- `asyncapi/runtime.yaml`：DDS/MQTT/事件契约入口。
- `compatibility/0.1.0.json`：已发布公共 SDK 和通信契约的兼容基线。
- `compatibility/sdk-surface-0.1.0.json`：从实际安装树生成的完整 SDK API/CMake surface 与 Windows MSVC DLL 导出符号基线。
- `pdr-plugin-runtime.json`（安装到 Runtime `bin`）：插件 API、ABI、目标平台和工具链契约；
  Bundle Manifest 使用四个 `PDR-*` 字段声明其构建兼容范围。
- DDS 数据结构仍以 `platform/DDS/idl` 中的 IDL 为代码生成来源；新增 Topic 必须同时登记到 AsyncAPI。

契约变更规则：

1. 删除字段、收紧范围或改变单位属于不兼容变更，必须提升主版本。
2. 新增可选字段属于兼容变更。
3. `requestId`、`traceId`、`deviceId` 是跨入口公共元数据，不得复用为业务字段。
4. CI 的 `contract-files` 保证契约文件完整，`configuration-contract` 对照 C++ Validator 检查全局数值范围、全部索引族、协议边界及已发布必填项的兼容子集，`compatibility-baseline` 阻止同一主版本删除或收紧已发布契约。历史 Schema 未要求 `pdr.subprocess.shutdownTimeoutMilliseconds`，同一主版本只发布其类型和范围；Runtime 与离线校验仍要求实际部署提供该字段。
5. 插件 API 或 ABI 版本变化属于破坏性变更；同一 Runtime 主版本不得静默修改，ABI 指纹由构建平台和编译器主版本生成。
6. 已安装 SDK 的现有公共头文件 token、`PocoDDS::` target 或同 ABI key 下 DLL 导出符号发生删除/变化时，必须提升 Runtime 主版本；Linux 二进制 ABI 需使用独立 ELF 基线，不能沿用 Windows 结论。
