# 下一版本发布说明（未发布）

状态：**开发候选，尚未批准发布**。

当前 Windows Release 基线已完成多 Profile 构建、契约、安装消费者与 CTest 验证；精确结果以候选提交对应的 CI 和资格报告为准。这些证据仍只覆盖本地构建、工具和模拟运行路径。PetaLinux 目标、真实协议设备、生产身份、现场网络以及 24/72 小时长稳证据尚未全部签署，因此不得把本说明当作生产放行记录。

## 本轮变化

- Registry Leader Backend 新增 schema v3 Secret Provider SPI：配置仅保存版本化 secret 引用，固定 Provider
  制品并在每次业务调用时解析、仅注入目标子进程；能力协商不读取凭据，公开检查报告不输出值、摘要或长度。
  安装 SDK 包含环境变量迁移示例、公开 CLI、七份契约 schema 和 PDR-REC-0036 恢复场景；生产 Provider
  应对接 Credential Manager、Vault、云 Secret Manager/KMS 或 workload identity。
- Secret Provider v2 与 Backend schema v4 增加有时间边界的双版本轮换：有序首选/回退版本、显式回退截止、
  撤销感知、租约剩余时间校验及可选秘密来源 allowlist。新旧值可分阶段投放；旧值不会在截止后被静默使用，
  过短租约也不会启动 Backend 子进程。v1 精确引用继续兼容。
- 新增公共 Team Contract Adapter Runtime SDK，Backend、Secret Provider、Artifact Store 和 Config Resolver
  统一使用同一无 shell 子进程边界、最小环境、硬超时、响应上限、默认 stderr 脱敏及稳定能力摘要，减少多团队
  重复实现和安全策略漂移；PDR-REC-0037 独立覆盖边界故障注入。
- 新增摘要固定的 Adapter Manifest 与 Host 本地 Catalog：新 Adapter 类型通过数据声明即可被公开 CLI 列举和执行
  只读 Capability 健康检查，无需修改核心注册表；配置、可执行程序和辅助制品仍逐层复核，协议业务调用继续由
  专用宿主强校验。安装 SDK 包含生成器与真实调用验证，PDR-REC-0038 覆盖未知类型、漂移、重复和脱敏边界。
- 新增 Host 本地 Adapter Catalog 原子激活控制面：跨进程 fenced writer lease、expected generation CAS、唯一
  operation ID、不可变内容寻址状态链和原子 pointer 防止多人并发覆盖；回滚选择历史固定 Catalog 但创建新
  activation generation，当前能力检查在探测中发生切换时拒绝旧快照。PDR-REC-0039 覆盖完整故障注入。
- 新增可恢复 Adapter Catalog Reconciler：通过摘要固定的幂等 lifecycle Hook 执行 prepare、bounded drain、原子
  switch、activate、有限 health gate 和 commit；切换前失败 abort，切换后失败自动创建源 Catalog rollback
  generation。自摘要 journal 支持 health 阶段进程死亡及 rollback Hook 失败后的继续执行，PDR-REC-0040 覆盖。
  已提交事务新增 `reconcile-revert`，使用原源身份和 lifecycle Hook 创建可重试的新 rollback generation，为后续
  多 Host 反向波次回退提供不绕过单节点生命周期的原语。
- 新增 Adapter Catalog Fleet 发布控制面：固定的 Plan 与 Node Executor SPI 支持第一波零失败 Canary、后续有序
  wave、每波失败预算和有界节点并发；协调器在节点完成但响应未持久化时死亡可按稳定身份恢复。超预算立即停止
  后续节点准入，并通过各节点真实 Reconciler 按 wave/节点逆序撤销 committed 事务；pending 节点保持不变。
  PDR-REC-0041 覆盖并发、崩溃、歧义重试、逆序回退、计划冲突、pin、journal 篡改和秘密脱敏。
- Adapter Catalog Fleet Plan v2 新增独立 Wave Gate SPI：每个 wave 可声明最短观察时间、最大判定次数和拒绝
  动作，通过证据 SHA 接收 SLO/错误预算或人工审批结果。长观察窗口持久化后立即返回；Gate pause 不能被普通
  recover 绕过，resume/abort 使用 generation CAS、唯一 operation ID、actor/reason 审计且幂等。Gate 响应丢失
  可按稳定 evaluation ID 消歧，abort 复用节点 Reconciler 逆序回滚。PDR-REC-0042 覆盖完整故障注入。
- Adapter Catalog Fleet Plan v3 新增独立 Control Authorizer SPI：resume/abort 不再仅信任自报 actor，而以
  外部认证 Principal、默认拒绝策略和证据 SHA 准入。传入 Authorizer 的是 reason SHA 与脱敏控制意图；allow/deny
  均进入自摘要 journal，deny 不改变 rollout/control generation，授权响应丢失可按稳定 authorization ID 恢复。
  Plan v1/v2 保持兼容，PDR-REC-0043 覆盖 Principal 冒用、拒绝重放、崩溃恢复、pin、篡改与秘密脱敏。
- Adapter Catalog Fleet Plan v4 新增跨协调 Host State Store：完整 journal 作为不可变内容写入 Artifact Store，
  Leader Backend 只保存线性 CAS/fencing Pointer。Plan 固定 Backend/Store ID 与配置 SHA，但不固化主机本地
  配置路径；新 Host 可使用空 scratch 接管，旧 writer、响应丢失、scope/pin 漂移和 blob 篡改均失败关闭或精确
  读回消歧。Plan v1-v3 保持兼容，PDR-REC-0044 覆盖 15 项接管与安全断言。
- Adapter Catalog Fleet Plan v5 新增统一、强类型的 Adapter Config Resolver 引用：Executor、Wave Gate、Control
  Authorizer、Registry Leader Backend 和 Artifact Store 不再把主机本地配置路径或配置摘要写入 Plan、远程 journal
  与 Pointer。不同 Host 可用各自固定的 Resolver/Mapping 解析同一逻辑引用，解析后仍由所属 Adapter 契约复核身份、
  revision、scope、制品 pin 和配置内容；PDR-REC-0045 覆盖 Host 差异、漂移与跨协调恢复。
- 统一 Adapter Conformance Kit 现在认证七类公共边界：六类 Fleet Adapter 加 Governance Approval Signer。
  Signer evidence 固定 signer ID、approver scope、config/capability SHA；独立 Certifier 可复用现有 Ed25519
  attestation 与 Trust Policy 对精确 signer kind/ID 签名、限权、到期和吊销。Fleet v6 的六类强制准入集合保持不变。
  Kit 使用各 Adapter 的权威解析器和能力协商，
  生成稳定 conformance ID、自摘要且脱敏的 integration-readiness 证据。安装 SDK 和公共 `pdr` CLI 均提供同一入口；
  PDR-REC-0046 覆盖公共 Kit；PDR-REC-0056 覆盖 Signer 实测、证据交付、独立认证、scope、到期与吊销。
- 三类 Governance Approval 外部签名命令现在可选用 SHA 固定的 Signer Admission 配置。每次创建审批前都会重新
  验证当前 signer/config/capability 与未过期 conformance evidence、独立 certifier attestation 和最低 generation
  trust policy；通过后生成无路径 schema v3 envelope，并把 conformance/certifier/policy provenance 纳入域分离签名。
  未启用准入的外部 v2 与显式本地 PEM v1 保持兼容。PDR-REC-0057 覆盖固定、时效、吊销、篡改与三类命令。
- Schema v3 现在同时是强制“执行时重新准入”契约。三个 verify/activate 命令必须提供 SHA 固定的本地
  Readmission Bundle 和 evidence 输出；Bundle 按 approval SHA 精确映射 Admission Config。执行方会用当前
  Trust Policy 重新检查 evidence 年龄、attestation、Certifier scope/有效期/撤销，并允许仍获授权的 policy
  generation 前进。无路径 Readmission Evidence 的 SHA 会写入 schema v2 业务报告。PDR-REC-0058 覆盖三条链路。
- Fleet Plan v6 将认证证据升级为执行前强制准入：Plan 固定认证等级、check-set、最大证据年龄和六类必需
  Adapter；每个 Host 使用 SHA 固定的本地 admission bundle，运行时再绑定实际配置、scope 与能力摘要。
  远程 journal 只保存 admission ID 和六项摘要，不保存本地路径；安装 SDK 已验证 Host A 暂停后 Host B
  用不同 Resolver/准入包恢复。PDR-REC-0047 覆盖过期、篡改、配置/能力漂移和跨 Host 接管。
- Fleet Plan v7 在 v6 准入之上增加 Ed25519 认证证明与 SHA 固定的 certifier trust policy。策略限制
  Adapter kind/ID、密钥有效期、最大证明寿命和最低 generation，并支持显式吊销及密钥轮换；远程 journal
  仅保存 policy/attestation/certifier/key 摘要身份。安装 SDK 验证 Host A 暂停后 Host B 使用独立签名 bundle
  恢复；PDR-REC-0048 覆盖过期、越权、吊销、轮换和策略 generation。
- Adapter Certifier Signer 新增固定配置与能力协商的外部进程协议，使 KMS/HSM/企业签名客户端不进入 Fleet
  核心。Signer 可按 key ID 路由，接收 SHA 绑定的规范 payload，私钥不返回主进程；主机用固定公钥再次验证
  Ed25519 签名。attestation v2 与 journal 记录脱敏 signer/config/capability 摘要；本地私钥模式继续兼容。
  PDR-REC-0049 覆盖配置/制品漂移、错误 key、拒绝和损坏签名。
- Adapter Certifier Trust Control 为 trust policy 变更新增 proposal、Ed25519 approval 与 activation 三阶段协议。
  普通变更至少需要两名不同审批人，并要求发起人、审批人、激活人职责分离；短期紧急模式只能新增 key
  吊销，不能增加 certifier、扩大 Adapter scope、改写旧吊销或放宽证明寿命。PDR-REC-0050 覆盖单人替换、
  重复审批、过期/陈旧 proposal、职责混用和紧急扩权。
- Adapter Certifier Trust Remote State 将活动策略、激活证据和状态记录保存为内容寻址的不可变 Artifact，
  并用 Registry Backend 的线性 CAS 指针、fencing token 和前驱 SHA 建立跨 Host 状态链。Host B/C 可在
  协调器丢失后接管；陈旧 Host 写入被拒绝，CAS 成功响应丢失时按精确提交身份读回消歧。公共 CLI 提供
  remote initialize/propose/activate/status；PDR-REC-0051 覆盖双人审批后的远程激活、接管、并发冲突、
  提交歧义和 Artifact 篡改。
- Adapter Certifier Trust State pointer v2 改用 Adapter Config Resolver 的强类型逻辑引用。Host A/B/C 可使用
  不同 Resolver 配置 SHA、不同 Backend/Artifact 配置路径和本机凭据 Provider，同时远程 pointer 不保存路径或
  Host 配置 SHA。Resolver 绑定 control ID、trust policy ID、Adapter kind/ID 和 revision；错误 revision/scope、
  引用漂移或解析身份不一致均失败关闭。pointer v1 继续兼容；PDR-REC-0052 覆盖三 Host 路径差异。
- Adapter Certifier Trust State 新增受治理的 pointer v1→v2 在线迁移。迁移 preflight 要求 direct 与 portable
  Adapter 对完整 v1 历史形成逐字节一致视图；proposal 固定源 pointer/state/policy、direct config pin 和目标
  Resolver 引用，两名不同 Ed25519 审批人与独立 activator 才能提交单次 CAS。迁移保持 policy generation/SHA
  不变，丢失成功响应按精确 pointer 回读，重复操作幂等；无签名迁移证据的混合历史、降级和旧 Host 写入均
  失败关闭。PDR-REC-0053 覆盖 Host B 迁移、Host C 接管、迁移后继续激活与证据篡改。
- 新增公共 Governance Approval 协议与验证引擎。通用 subject 固定 payload product/SHA、role、initiator、
  policy ID/SHA 和有效期；独立 signature 使用 Ed25519，verify 统一检查角色准入、不同人/不同 key 法定人数、
  撤销时间、公钥 pin 及 initiator/approver/executor 职责分离，并输出无本地路径的 evidence。Adapter Trust
  Policy 与 pointer Migration 保留既有 approval JSON 格式但已复用同一引擎；PDR-REC-0054 覆盖通用流程和
  两种兼容信封。
- Governance Approval 新增目的绑定的外部 Signer SPI。通用审批、Adapter Certifier Trust Policy 审批和
  pointer Migration 审批可使用配置/制品/公钥固定的 KMS、HSM、Vault 或企业签名进程；能力协商精确绑定
  signer、approver、key set 与允许 purpose；域分离签名载荷同时绑定 approval product、subject SHA 和
  signer/config/capability 摘要，主机对返回的 Ed25519 签名再次本地验证。外部模式输出无路径
  v2 approval envelope，本地 PEM 模式继续兼容 v1；PDR-REC-0055 覆盖三类信封及失败关闭。

- 跨仓库团队契约交付新增确定性、内容寻址的 `.pdrcontracts` 包和无路径锁文件：Service、配置
  Participant、配置键生命周期及其已发布基线可按包 ID/版本/Owner/SHA 协作；安装 SDK 提供离线
  `pack/verify/lock/resolve` CLI 与 CTest。Ed25519 签名及 SHA 固定信任策略进一步校验发布 Owner、
  精确包范围、公钥、有效期和撤销；锁定与每次解析都会重新验签，拒绝错包、旧锁、篡改、越权
  发布者、额外条目、符号链接和路径穿越。新增签名锁升级影响预演和显式 Consumer 目录，阻断
  同版本漂移及 Service/Participant/配置键生命周期破坏，并生成摘要绑定的 Owner 与 CTest 标签路由。
  兼容影响现在还必须执行路由选中的真实 CTest，并生成绑定 CTest 程序、测试目录/命令和 JUnit 的
  证据；每个受影响 Consumer Owner 使用独立、短期 Ed25519 批准，最终 Gate 重新检查目录漂移、
  策略 SHA、有效期和撤销。缺测试、失败/跳过/禁用测试、缺 Owner 或复用旧批准均不能放行。
  新增不可变团队契约 Registry：签名包和锁按 SHA-256 存储，原子指针连接完整 revision 状态链，
  `dev → staging → production` 后级晋级必须复用前置通道当前锁并绑定影响 Gate；通道 generation
  阻止多人并发覆盖。Consumer 可按通道解析而无需 Provider/cache 路径，显式 rollback 创建新代次并
  保留历史锁、操作者和原因。
  影响 Gate 进一步支持独立 CI Runner Ed25519 证明，绑定 repository/source revision、workflow、
  job/run 以及 impact、JUnit、CTest 程序/catalog/命令摘要；staging/production 晋级强制要求该证明。
  新增独立 Gate 发布授权：授权服务重放完整 Gate 后签名，短期凭证绑定 Gate 字节、候选锁、Runner、
  Registry ID 与允许通道；Registry 后级通道独立复核策略 pin、签名、范围、有效期及撤销并将授权
  SHA 写入状态链，伪造 Owner 汇总或跨 Registry/channel 复用均被拒绝。
  Registry 可把 revision/state SHA 由独立审计服务签名后保存到根目录外，并沿当前状态链检测整个
  Registry 被替换为较旧但内部自洽副本。
  新增跨机器 Registry 控制面与安装 SDK 客户端：Provider 上传 SHA 绑定制品而非服务端路径，
  Consumer 按通道远程解析；访问策略限制 reader/publisher/promoter/rollback、package ID、channel、
  token 有效期和撤销。mutation 强制 request ID、expected Registry revision 与 channel generation，
  相同请求幂等、换内容重放或并发旧 revision 拒绝；非 loopback 默认强制 TLS。契约包验证同时拒绝
  ZIP 结束记录后的未签名尾随字节。新增 auditor/operator 分权的请求状态与显式恢复：revision 未变
  只能标记 `aborted`，revision 已前进只能标记 `uncertain`，两者均禁止旧 ID 再执行。请求状态迁移写入
  不可变 SHA-256 审计链；独立 Ed25519 审计方可把链检查点保存到控制目录外，检测记录篡改、截断和
  控制状态整体回退。远程操作报告改用字段白名单，避免把 Registry 或服务端临时目录绝对路径泄露给
  Consumer。
  访问策略进一步支持 Ed25519 签名连续 revision 热加载：后继策略精确绑定上一策略原始 SHA、
  Registry/Policy ID、签发时间和独立轮换信任策略；无签名替换、回退、跳 revision、错误范围及撤销
  密钥均 fail-closed，成功切换写入同一不可变审计链。签名策略可限制活动请求、恢复、审计记录和控制
  目录总字节；`registry-remote-capacity` 暴露当前用量和准入结论，新写入在越界前返回容量错误，不会
  静默删除幂等响应或审计证据。
  Registry 写锁和远程控制锁进一步改为 Windows 独占句柄/POSIX `flock` 所有权租约：锁文件仅保存
  最近 Owner 证据，进程崩溃后由 OS 自动释放，无需人工删除。每次获取原子推进持久 epoch，本地指针
  发布和远程事务终结前执行 fencing 校验；新增本地/远程 lease status、安装 SDK Schema 与真实子进程
  崩溃故障注入，覆盖并发拒绝、崩溃接管、旧写者隔离和 epoch 损坏 fail-closed。

- 新增 `PocoDDS::FastDDSAbiV1`/`PDRFastDDSAbiV1`，以不透明句柄、定长错误缓冲区和十二个显式
  C 导出符号提供版本化 Fast DDS 二进制边界；旧自动导出 DLL 保留为兼容层，不再推荐新组件
  直接依赖。安装 SDK 门禁使用纯 C 工程验证头文件、布局、链接和生命周期，target 不向调用方
  传播 C++ 编译特性；可撤销订阅句柄会在插件卸载前禁止新回调并排空在途回调。

- Fast DDS 新增默认兼容、ABI 不变的进程级部署策略：`PDR_FASTDDS_PROFILE` 指向版本化文件，统一
  配置 UDPv4 接口白名单、初始 Peer、组播禁用、SHM 组合和有界 Peer 端口扫描；未知/重复 key、
  非法布尔值和危险范围 fail-closed，Runtime 快照输出去标识化部署摘要。同进程 Participant 测试不再
  表述为跨进程验收，现场网络与防火墙证据继续独立管理。安装包新增
  `pdr-fastdds-profile-check`，复用生产解析路径但不创建 Participant，供 Launcher、CI 与部署脚本
  在进程启动前执行确定性配置门禁。可选 `PDR_FASTDDS_PROFILE_SHA256` 进一步绑定最多 64 KiB 的
  Profile 原始字节，checker 与 Runtime 使用同一摘要，阻断预检后文件替换的 TOCTOU 漂移。
- 框架恢复治理新增七层可执行故障矩阵：场景绑定组件 Owner、CTest 注册/标签、超时和逐断言 marker；v2 证据同时绑定选中测试命令/程序与 Profile 共享运行库集合。新增 MQTT Broker 非预期断线后的协调重连/订阅恢复，以及 Fast DDS Subscriber Participant/DataReader 重建、原逻辑订阅恢复和 Publisher 连续运行验证。MQTT 受治理 Paho 构建还修复消息回调与 `disconnect/cleanSession` 并发时的队列双重释放，依赖能力标记和 `callbackTeardown` 故障注入阻止未修复库进入构建。本地故障注入与真实设备/HIL 验收保持明确边界。
- SDK 公共表面新增弃用生命周期门禁：公共头文件标记、CMake target 和 ABI artifact 必须登记 Owner、替代入口、首次公告快照及最早移除主版本；破坏性变更不能再仅靠提升主版本放行。
- 多模型框架：形成 `desktop-lite`、`desktop-distributed`、`embedded`、`edge-industrial`、`edge-test`、`server` 与 `robotics` Profile；构建清单明确 Host、Runtime、WebUI、能力和内置/外部 Transport，不再让普通桌面程序隐式依赖 ROS 2。
- RuntimeCore：新增稳定的 Host/Component、消息契约、`PDRM/1` 编解码、同步/有界异步 Executor、依赖排序与失败回滚、Transport Registry 和一致性测试边界。
- 传输适配：新增进程内、本机 IPC、MQTT 与 Fast DDS 的统一 `IMessageTransport` 实现；Windows Named Pipe、Linux Unix Domain Socket、MQTT Broker 和 Fast DDS Participant 均复用同一消息帧契约。
- 进程模型：`desktop-distributed` 新增 Native Process Supervisor；Windows 使用 Job Object，Linux 使用 Process Group，并提供根目录约束、依赖排序、优雅停止、进程树回收、有限重启预算和无副作用的 DAG 生命周期影响预检。OSP Runtime 的受管进程可选启用版本化、SHA-256 自校验的期望状态持久化，人工启停和 crash-loop 终止决策跨重启保持；原子写失败不执行生命周期动作，所有恢复快照损坏则在子进程启动前 fail-closed。
- Launcher 子进程边界：新增显式 `childWorkingDirectory`，使被监督 Runtime 的配置、动态库与相对资源解析不再隐式继承 Launcher 目录；目录缺失时启动前拒绝。
- Launcher 通用预检：新增无 shell、绝对可执行路径、参数/步骤上限和单步超时的 `preflight.N` 启动门禁；初始失败直接拒绝启动且不消耗重启预算，Bundle 候选失败进入既有 LKG 回滚。新增有界、严格判重的 `childEnvironment.N`，预检和子进程共享同一完整环境快照，可组合 Fast DDS 及后续组件校验器而不把协议逻辑写入 Launcher，也不会出现验证输入与运行输入漂移。
- 工程化：新增安装后 Transport/IPC 消费者、架构与兼容面检查、跨平台 CI、部署模型文档和进程内性能预算；ROS 2 保持为机器人工作区的外部 Adapter，不伪装成通用底层通信。
- 通用开发：提供可安装 CMake package、公共 SDK、版本信息和插件脚手架；默认配置不主动连接物理设备或外部协议。
- 插件治理：增加 API/ABI 与依赖检查、发布者签名和信任策略、隔离宿主、资源边界、隔离部署以及事务回滚/恢复。
- 稳定性：管理任务、幂等请求、审计、告警历史和插件隔离状态可持久化；设备与协议具备重连、超时、退避、诊断和 readiness 联动。
- 资源治理：新增独立 `pdr.service.resourceGovernor` Bundle 和 SDK API，按 Bundle/模块 owner 建立并发、有限队列、排队超时、协作执行超时及熔断隔离 lane，并提供最小权限状态接口。
- 受治理执行：新增 `ManagedWorkLane` owner 绑定和 Bundle 卸载屏障；WorkflowRuntime 与 OutboxRuntime 的周期业务已进入各自治理 lane，不再直接运行于节拍线程。
- 中央调度：新增独立 `pdr.service.schedulerRuntime`、单调时钟定时轮、fixed-delay/fixed-rate、skip/coalesce misfire、抖动、拒绝退避、协作取消及状态 API；WorkflowRuntime/OutboxRuntime 不再各自创建节拍线程。
- 在线调度配置：新增原子 `reconfigure`、enabled/interval/jitter 事务参与者及独立 ConfigurationRuntime 管理 API；支持 generation 冲突、稳定 patch 幂等、失败逆序回滚、双层权限和参与者卸载屏障。
- Runtime 配置预检：新增独立 `ConfigurationPreflightRuntimeService` 和受鉴权的
  `/api/v1/configuration-transactions/preflight`；复用正式提交的完整快照校验、逐键 capability、
  配置所有权、参与者拓扑和 preflight 回调，但不写事务 journal、不激活 Preferences，也不调用
  commit/rollback。正式 apply 始终重新校验 generation 和 Participant 拓扑，预检结果不能充当授权。
- 配置参与者目录：新增独立 `ConfigurationParticipantCatalogRuntimeService` 和只读
  `/api/v1/configuration-participants`，按 Participant ID 输出配置前缀 Owner、执行依赖、注册代次、
  未解析排序依赖、拓扑 generation 和摘要；成功 attach/detach 才推进 generation，冲突注册不污染
  目录版本。同一 Participant 内部覆盖前缀和新注册形成的完整 `after` 环现在在 attach 阶段 fail-fast。
  注册拒绝新增独立 admission generation、稳定脱敏错误码和 128 条有界诊断，并通过 Health contributor
  使 readiness 降级；Service 卸载/合法重注册后自动清除，原始异常文本不进入管理 API。
  进一步新增 Bundle 本地 `configuration-participants.json` 自动发现：Active Bundle 承诺的 Participant
  若完全缺失，或实际 Owner、Service 名、前缀、`after` 与声明漂移，均进入独立 expectation generation
  并阻断 readiness；Inactive Bundle 仅保留诊断。声明不依赖中央登记，非法/重复/超限文档 fail-closed。
  新增可安装的静态契约工具和 `pdr_add_configuration_participant_contract_test()`，可在不启动 Runtime
  的情况下联合检查多团队声明的重复 ID/Service、前缀覆盖及依赖环；Bundle/Plugin 模板升级到 v8，
  新组件默认生成真实参与者、Bundle 本地声明和独立 CTest，旧组件安全升级为空声明。进一步新增
  `configuration-participant-baseline.json` 已发布兼容面和摘要绑定报告：允许新增 Participant、扩大
  Owner 前缀及增加排序依赖，阻断删除/改名/换 Owner、缩窄或转移前缀及移除已发布排序保证；SDK
  CMake 函数和 `pdr component participant-contract-test --baseline` 均可复用同一门禁。
  在此基础上新增 Bundle 本地 `configuration-key-lifecycle.json`：把已发布键 rename/remove、替代键、
  Participant Owner、首次弃用版本和最早后续主版本移除窗口与产品 migration 文件交叉验证；阻断
  跨团队改键、未公告删除和替代环。ConfigurationRuntime 自动发现并通过 Participant Catalog schema
  v4 输出脱敏生命周期状态，Active Bundle 非法/越权声明传播至 readiness，Inactive Bundle 仅诊断；
  Runtime 不擅自重写 Preferences。已发布生命周期基线进一步阻断到期前删除声明、改变 Owner/替代键
  或提前移除窗口。安装 SDK 新增独立 CMake CTest，Bundle/Plugin 模板升级至 v9。
- Service 依赖治理：新增 Bundle 本地 `service-contracts.json` 自动发现、Provider/Requirement 版本匹配、Owner 防冒充、必需/可选依赖、声明错误 fail-closed、独立只读 API 和 `/health/ready` 传播；进一步增加通用 BundleLifecycleGuard、启动准入、Provider 停止影响分析及执行点二次校验，不需要在中央文件登记新业务服务。
- 生命周期维护：新增独立 Lifecycle Runtime、通用 `DrainGate` 和动态排空参与者；支持 Active Consumer 拒绝新请求、等待在途任务、Consumer→Provider 事务式停止、TOCTOU 二次校验、失败逆序回滚以及 Provider→Consumer 恢复。进一步增加 SQLite WAL/FULL 计划日志、跨 Runtime 重启幂等、启动后中断事务恢复、待恢复 Readiness 门禁、人工 `recover` 重试，以及离线完整性检查、JSON 导出和一致性备份；成功 `drained`/`restoreRolledBack` 现在作为持久化 desired-stopped 状态，在业务 Bundle 自动启动前恢复组合守卫，只有显式 `restore` 才重新激活拓扑。
- Runtime 成员视图：新增传输无关成员状态机和独立 MembershipRuntime Bundle；使用稳定实例 ID、SQLite 原子递增 incarnation、严格 sequence、接收端单调时钟 TTL、有界墓碑和优雅 leave 防止重启混淆及延迟消息复活。Fast DDS 只承担心跳传播，OSP Service/健康贡献者提供本地查询；该能力明确不宣称选主、法定人数或强一致。
- Runtime Service Directory：新增显式 `ServiceAdvertisementProvider`、接收端 TTL、Runtime incarnation/revision 重放防护、有界墓碑与容量，以及 round-robin、rendezvous-hash、prefer-local 三种健康感知路由。只有显式端点可被发现，Membership 精确代际作为路由资格；组件不自动暴露 OSP Service、不代理远程调用，也不宣称负载均衡遥测、选主或强一致。
- 跨 Runtime Service Client：新增传输无关调用协调器，在 Service Directory 选路之上提供总 deadline、幂等门禁、指数退避、跨实例故障切换、按 Runtime incarnation 隔离的 open/half-open/closed 熔断和有界状态快照。进一步增加独立 ServiceClientRuntime Bundle、动态 `ServiceInvocationProvider`、单协议唯一所有权、在途注销屏障、异步提交 Future、ResourceGovernor owner lane 和只读状态 API；非幂等操作默认禁止自动重试，晚到成功不会突破 deadline，框架也不提供任意远程代理 POST。首个独立 HTTP(S) Provider 增加固定已校验 IP 的 DNS rebinding 防护、显式 host/port/私网出站策略、受限 metadata 转发、有界请求响应、TLS 校验和可重试 HTTP 状态映射。
- Bundle 部署治理：仓库变化先做无副作用的严格包/依赖预检，坏包 fail-before-mutation；生产默认把合法变化持久化为 `restartRequired`，不再对原生动态库执行高风险进程内全卸载。新增 Launcher 跨进程激活事务：确定性 SHA-256 候选内容绑定、跨 Launcher OS 独占租约、独立保存旧代次、绑定事务 ID/指纹的 `activationReady` 握手、可选业务 Readiness、稳定 probation、计划内重启不消耗崩溃预算，以及候选篡改/崩溃/超时和 Launcher 中断后的停机原子回退；同时保留显式停机确认的离线恢复工具。
- Bundle 供应链：新增仓库级 Ed25519 发布者授权，使用候选仓库外的摘要绑定证明、固定策略 ID/SHA、公钥摘要、仓库命名范围、有效期和吊销列表；Runtime 在 OSP 初始化前拒绝未签名候选，Launcher 在停旧进程前及 probation 中复核完全相同的授权证据。证明 schema v2 增加签名 `rolloutSequence`，耐久高水位拒绝低序号和同序号不同内容；`committing` 状态支持崩溃后幂等完成，高水位推进前仍可恢复摘要不变的精确 LKG。
- Bundle 受控降级：新增离线 `request/approve/preflight/apply/recover` break-glass 流程，精确绑定源高水位、当前实际仓库摘要、目标发布授权、工单和短期 UUID；独立审批策略支持最多 16 人的 M-of-N 门槛，拒绝重复审批人/密钥、过期、吊销、源/目标漂移和重放。`preflight` 真实复制并重新授权 staging、检查空间和审计链，但不切换或消费；执行使用同一高水位 OS 租约和原子目录切换，一次性消费证据与 previous/self SHA-256 审计链可由 `verify-audit` 离线复核。持久事务 journal 覆盖目录切换、高水位、消费和审计边界；中断时以实际高水位决定提交前回滚或提交后前向完成。
- 项目配置协同：新增独立 `project config preflight` 无副作用参与者预演和自校验证据；`apply` 可绑定并复核证据但仍重新预检。journal v3 增加 SHA-256 自校验、持久原子写、锁内重读及事务私有计划/候选快照；任一未恢复事务会阻止新提交，避免多人并发时旧回滚覆盖新配置。按 JSON Pointer 高风险路径触发短期 Ed25519 M-of-N 审批，独立校验必需角色、发起人分离、策略 pin、密钥有效期/吊销和不同人员/密钥。每个终态还写入带强制 actor、previous-record SHA-256、持久 head 和 journal 双向绑定的审计链，可由 `verify-audit` 离线检查篡改与尾部截断；可移植 Ed25519 签名检查点还能在链继续增长后验证历史前缀，并在检查点外部保存时发现本机日志/head 回滚。
- 配置事务交接：新增只读 `project config status [--check]`，聚合活动/陈旧锁、发起人、运行中及待恢复 journal、审计链健康与 `canApply`，让 CI 和接手人员在下一次提交前使用同一机器可读门禁。
- 制品来源：发布清单签名现在同时绑定 SPDX SBOM 与 Builder/Profile/artifact-set 来源；Bundle attestation 进一步绑定发布清单、SBOM、版本和 Git commit，并贯穿 Runtime/Launcher 事务、高水位、LKG 与恢复检查。
- 多人协作：新增框架组件 Owner/依赖/Target/CTest label 契约和 fail-closed change-impact/gate 工具；共享、未知或含糊路径强制全量测试，局部改动沿消费者依赖传播；逻辑 Owner 进一步映射到真实 GitHub Reviewer，并由 CI 强制校验生成的 CODEOWNERS 无漂移；full-stack CTest 生成与影响计划 SHA-256 绑定的执行证据，计划与测试结果不再是两个孤立报告。
- Service 团队解耦：将原先单一的 `services` 逻辑组件拆为治理服务、设备/协议网关和通用服务三个独立 Owner 边界；变更影响、CODEOWNERS、源码头文件门禁、CMake 链接门禁和故障恢复矩阵统一使用 27 组件依赖图。新增 `PDRGovernanceServices`、`PDRGatewayServices` 和 `PDRUtilityServices` 三个可独立构建聚合 Target，配套门禁根据 CMake 实际目标图阻断漏收和跨团队误收。
- 构建执行证据：affected-only 与 full-stack 构建将变更报告 SHA-256、源修订/文件、CMakeCache、Target 图、聚合组、依赖清单及规范化命令绑定；输入在构建期间变化、构建失败、证据篡改或换用其他修订均不能通过独立 gate，同一输入集还会生成稳定的团队缓存 key。
- 组件封装：源码门禁禁止通过相对路径或仓库路径包含其他组件的私有头文件，CMake 门禁禁止向 target 注入其他组件的源码根、`src/` 或内部 include directory；所有命名 Profile 对未解析 include 表达式 fail-closed，避免多人并行开发时绕过公共 SDK 和显式依赖契约。
- 组件契约测试：安装包新增 `pdr_add_component_contract_test()`、`pdr component contract-test` 与证据重算验证，Consumer 可在不启动 Runtime 的独立 CTest 中固定 Provider 团队的真实 `service-contracts.json`，验证必需/可选依赖、语义版本范围、最小 Provider 数量并生成跨检出路径稳定的输入摘要绑定证据；Bundle/Plugin 模板 v7 默认接入 Service 门禁，v8 进一步接入事务配置参与者门禁。
- 生产 Service 契约图：新增 `pdr service-contract graph/verify/baseline-snapshot`，扫描全部生产 Bundle 契约和真实 `.bndlspec` Owner，固定已发布 Provider 基线并在 CI 阻止同主版本改名、版本倒退、Consumer 未迁移、全局 Service 名冲突与必需依赖环；当前生产图为 11 个 Bundle、11 个 Provider、8 个已满足的必需 Requirement。
- SDK 兼容性：新增基于实际安装树的公共头文件 token、导出 `PocoDDS::` target 与 Windows DLL 导出符号门禁；同主版本破坏自动阻断，Linux 二进制 ABI 明确保留为独立 CI 验收边界。
- SDK 头文件质量：完整 Server SDK 的全部已安装公共头文件逐个作为独立 C++17 翻译单元编译，阻断传递 include、宏和未导出 usage requirement 造成的外部消费回归。
- 安全：管理写操作支持共享身份、最小权限主体、环境变量或文件密钥及热轮换；升级包、插件、外部验收报告和证据包支持 Ed25519 验证。
- 运维：健康、指标、业务追踪、结构化故障、告警和 Web 诊断形成统一入口；新增可恢复发行流水线、资格判定、外部验收和离线证据包。
- 设备与协议：参考设备覆盖 Modbus、串口、GNSS、Linux sysfs GPIO/LED、XBee、CAN 和模拟设备；网关覆盖 MQTT、ROS bridge 和 UDP。

## 兼容性

- 当前项目版本仍为 `0.1.0`，兼容基线见 `contracts/compatibility/0.1.0.json`。
- 旧单实例设备键继续兼容；新部署应使用 `pdr.<family>.count` 和索引键。
- 旧的单一管理 token 仍作为全权限兼容主体；生产部署应迁移到显式 principals。
- 外部原生 OSP 插件仍是进程内代码；隔离宿主是推荐的新部署方式。

## 发布前剩余门禁

最终源码状态必须重新运行完整 Release 测试与资格判定，并完成 PetaLinux 目标、真实协议、生产身份、现场网络和 24/72 小时长稳验收。只有资格报告给出 `RELEASE_CANDIDATE_APPROVED` 才能进入生产发布审批。

迁移步骤见 [0.1.0 开发候选迁移指南](../migration/0.1.0-development.md)，运维命令见 [运行手册](../operations/runbook.md)。
