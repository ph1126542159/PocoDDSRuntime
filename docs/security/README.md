# 安全基线

Bundle/组件内部资源访问使用独立的[Runtime Bundle 能力权限](runtime-capabilities.md)。管理 HTTP
权限回答“哪个已认证运维身份可以调用管理接口”，能力策略回答“哪个 Runtime 主体可以对哪个
Service/Topic/配置/设备/Schema 执行什么动作”，两者不能互相替代。

## 部署 Profile

`security.profile` 支持：

- `development`：允许本机回环地址上的无认证开发界面；绑定外部地址时必须同时配置认证和 TLS。
- `production`：必须启用 TLS、配置认证服务，并禁止兼容性 SimpleAuth。

Runtime 启动时通过 `ConfigurationValidator` 执行相同规则；仓库和部署配置还可以独立执行：

```powershell
python bin/security_gate.py bin/pdr-runtime.properties
```

配置文件中名称包含 `password`、`secret` 或 `token` 的非空值会被门禁拒绝。生产密钥应由
部署环境或后续 `SecretProvider` 适配器提供，不能提交进 properties、日志、Trace 或发布包。

旧 OSP WebEvent WebSocket `/webevent` 使用 OSP Web dispatcher 的 AuthService 门禁，Bundle
权限为 `*`，表示任何已认证身份都可订阅，但匿名请求必须返回 401。内置
`pdr.platform.managementAuth` Bridge 让它复用管理写接口的
`pdr.management.authentication.*` Principal：将 `osp.web.authServiceName` 设为
`pdr.auth.management`，并将 `osp.web.tokenValidatorName` 设为
`pdr.auth.management.tokens`。生产部署还必须使用 TLS/WSS；不要为了兼容旧客户端把 WebEvent
权限改为空，因为实时事件主题可能包含运行状态和业务数据。
OSP dispatcher 对失败的 Bearer 校验只能记录通用失败原因，不得把 Token、Authorization
头或凭据摘要写入日志；对应集成验收会用随机 Token 扫描标准输出、JSON 和 Runtime 日志。

Runtime 管理写接口另有独立 Bearer 门禁。开发配置可保持
`pdr.management.authentication.required=false` 以便仅在 loopback 上调试；生产配置必须
设为 `true`，并为每个身份配置 `tokenEnvironment` 或 `tokenFile`（二选一）。环境变量适合
启动时注入；受最小 ACL 保护的文件适合运行中原子轮换。令牌值不得写入 properties、命令行、报告或日志。该门禁统一保护协议实例、
子进程、Bundle 生命周期以及配置提交/回退；清单、健康和配置只读查询不要求该令牌。
共享的 ReloadablePrincipalStore 从环境或文件加载 Token、拒绝重复 ID/Token，并使用恒定
工作量比较；SystemMonitoring 与 OSP Bridge 使用同一个不可变快照。缺失或错误值返回 401。生产环境还必须使用 HTTPS，
避免 Bearer 令牌在链路上明文传输。`POST /api/v1/identity` 仅在候选配置完整有效时原子换代；
失败时旧快照继续有效，响应和审计均不包含身份清单或令牌。
身份状态还会报告文件型/环境型来源数量、文件权限检查是否完整，以及 ACL/Unix mode 过宽的
文件数量，但不会返回 Secret 路径。在 Windows 上会计算 Everyone、Authenticated Users、
Builtin Users 和 Guests 的有效权限；在 Unix 上要求 group/other 权限位为零。权限告警不会
自动改变文件 ACL，运维应收紧权限后再执行轮换。

需要最小权限时，使用 `pdr.management.authentication.principals.count` 和索引 Principal
配置。每个 Principal 包含非敏感 `id`、二选一的 `tokenEnvironment`/`tokenFile`，以及由
`protocol.manage`、`process.manage`、`bundle.manage`、`configuration.manage` 组成的
权限列表，并可用 `identity.manage`、`audit.read`、`task.read`、`task.cancel`、
`diagnostics.read`、`diagnostics.execute`、`capability.read`、`capability.manage`、`resource.read` 分别授予
身份轮换、审计查询、任务查询/取消、受控诊断、能力策略读取/换代以及资源治理状态读取；`*` 表示全部十三项权限。旧
`tokenEnvironment` 继续映射为 `legacy-admin` 全权限
身份，便于兼容已有部署，但新生产部署应优先使用职责分离的 Principal。认证成功但权限
不足返回 403，认证失败仍返回 401。Principal ID 会进入配置事务审计，令牌不会进入响应、
日志或报告。

诊断终端的 `GET/POST /api/v1/diagnostic-terminal` 使用独立的 `diagnostics.read` 权限。
它只执行编译进 Runtime 的白名单只读命令，不启动 PowerShell、cmd、bash，不接受任意文件路径、
网络目标或脚本。Bundle、Service、进程和日志输出可能包含内部部署信息，因此生产环境不能把
`diagnostics.read` 默认授予普通业务用户；终端命令只记录 Principal、命令名和退出码，不记录
Bearer Token，也不把完整命令参数写入 Runtime 日志。

异步任务查询和取消分别使用 `task.read`、`task.cancel`。取消只对尚未执行的 `queued`
任务生效；运行中的设备、协议、进程或 Bundle 操作不会被强行终止，因为中途杀死底层
操作可能留下未知硬件或进程状态。任务响应和审计同样不得包含令牌。
任务快照原子写入配置的本地路径，文件只包含非秘密任务元数据和结果。崩溃遗留任务会
标记为 `interrupted`，不得自动重放；应为快照设置仅服务账户和管理员可写的 ACL，并将
`persistence.healthy=false` 视为生产门禁故障。

统一管理审计默认启用，并由 `audit.read` 单独保护查询权限。JSONL 事件只记录 Principal、
请求 ID、操作、目标、结果、HTTP 状态、远端地址和耗时，不记录 Bearer Token 或请求体。
审计文件达到 `pdr.management.audit.maximumBytes` 后只保留一个 `.1` 归档；生产部署应再由
日志采集系统及时转存并设置文件 ACL，避免本机管理员之外的账户读取或篡改。

管理写接口还支持 `X-PDR-Request-Id` 幂等键。生产环境必须设置
`pdr.management.idempotency.requireRequestId=true`；缺少请求 ID 返回 428，同一 ID 和
相同请求内容重试时返回首次成功结果且不重复执行，同一 ID 被用于不同内容或请求仍在
执行时返回 409。请求 ID 只允许 1–128 个字母、数字、点、下划线、冒号或连字符；它是
审计关联标识，不得包含令牌或业务秘密。

幂等账本默认原子持久化到 `management-idempotency.json`，仅保存 SHA-256 请求指纹和非敏感
结果摘要。已完成请求可跨 Runtime 重启重放；崩溃时执行中的记录恢复为 `interrupted` 并拒绝
自动重试，防止结果未知时重复写设备或生命周期状态。生产门禁应同时要求
`idempotency.healthy=true`；账本文件应使用与审计和任务快照相同的服务账户 ACL。

持久化文件解析失败采用“诊断在线、写入关闭”的故障隔离策略。服务不会自动清空或覆盖损坏
账本；健康状态标记 `recoveryRequired=true`，并拒绝可能造成重复执行的新管理写操作。运维
人员必须保留原文件、核对目标真实状态并受控重启，不能把删除账本当作普通自动恢复动作。
Schema v2 还使用 `contentSha256` 检测保持 JSON 合法的静默内容变化。该摘要用于意外损坏
检测，不是数字签名或防恶意管理员篡改机制；生产环境仍必须依靠文件 ACL、只读备份和主机
完整性保护。
Runtime 维护的 `.previous` 只作为人工恢复证据，不是自动故障转移源。自动加载旧幂等账本
可能丢失最新去重记录，因此恢复操作必须离线进行，并结合审计日志与目标状态确认。
`pdr persistence backup` 生成的恢复点包含配置、任务元数据、请求指纹和管理审计，虽然不应
包含令牌原文，仍属于敏感运维数据。目标目录必须使用仅备份服务账户和管理员可读写的 ACL，
异地副本应加密并采用不可变保留策略。清单 SHA-256 只能发现意外变化；防恶意替换仍需外部
签名、独立保存清单摘要或受控不可变存储。
整套还原必须把操作审计写到被恢复文件集合之外，避免还原过程覆盖自身证据；审批时固定清单
摘要，还原前后保留恢复报告和 `pre-restore-evidence`。退出码 3 代表回滚或最终审计未完整
闭环，应按安全事件处理并禁止启动 Runtime。
恢复验收读取管理接口的令牌只能通过命名环境变量传入，禁止放在命令行、处置文件或报告中。
interrupted 处置必须记录复核人、复核时间、目标真实状态、证据引用以及是否使用新请求 ID
重试；验收器只做门禁判定，不会自动重放操作或自行开放管理写流量。
正常发布 smoke 必须验证优雅退出码 0；强制终止只能作为明确标记的故障注入。OSP Service
继承引用计数对象，Bundle Activator 必须使用 `Poco::AutoPtr`，不得再交给具有独立控制块的
`Poco::SharedPtr`，否则服务注销时可能形成双重释放。

当前 SimpleAuth 使用旧兼容哈希，只允许受控本地兼容场景。生产 OIDC、企业账户、证书签发
和私钥托管需要部署环境提供；仓库的安全门禁不把这些外部能力标记为已完成。

## 发布检查

每个发布物必须包含：

- `SHA256SUMS.json`：文件路径、大小和 SHA-256；
- `SHA256SUMS.sig.json`：Manifest 摘要、Ed25519/HMAC-SHA256 签名和轮换用 `keyId`；
- `pocoddsruntime.spdx.json`：SPDX 2.3 软件物料清单；
- Git commit、版本及工作区是否干净；
- 对应构建、测试和兼容性检查结果。

普通开发测试允许从未提交工作区生成验证制品；此时 Manifest 明确记录
`cleanRequired: false` 和实际 `dirty` 状态，不得据此宣称正式发布通过。

正式受控发布必须使用 `release` Preset：

```powershell
cmake --preset release
cmake --build --preset release
ctest --preset release
```

该 Preset 设置 `PDR_RELEASE_REQUIRE_CLEAN=ON`，`release-artifacts` 会向 Manifest 生成器传入
`--require-clean`；Git 工作区不干净时在生成 Manifest 前失败。成功生成的 Manifest 记录
`cleanRequired: true`。哈希校验发现文件缺失、替换、修改或未登记文件时也会失败。
代码签名证书和发布私钥不能存储在仓库中，应由受保护的发布流水线注入。
生产交付推荐 Ed25519：发布端可选 Python `cryptography` 仅负责私钥签名；目标包内安装
`pdr-signature-check`，直接使用已经随 Runtime 交付的 OpenSSL `libcrypto` 验签。升级端默认
要求签名，并同时固定预期 `keyId` 和公钥 SHA-256；私钥路径及可选口令只从命名环境变量
读取，工具不会输出或写入私钥。HMAC-SHA256 仅保留为共享密钥兼容模式，不具备公钥签名的
职责分离；组织级操作系统代码签名仍可作为外层供应链控制。

`release-trust-policy.schema.json` 是密钥生命周期契约。生产升级还会固定策略 `policyId` 和
SHA-256，并检查允许密钥、有效期及吊销列表。策略和验签器都不得来自尚未验证的新包；设备
镜像、当前可信安装或独立 bootstrap 必须提供初始信任根。

插件使用独立的 `plugin-trust-policy.schema.json`，不继承 Runtime 发布密钥权限。发布者通过
`pdr plugin sign` 生成 `PocoDDSRuntimePlugin` attestation 和 Ed25519 分离签名；策略按
`publisherId + keyId` 限制可签署的 `pdr.plugin.*` 命名范围，并固定公钥 SHA-256、有效期与
吊销状态。预检和安装默认要求该证据，同时把发布者、密钥和策略 ID 写入事务报告及追加审计。
诊断用 `--allow-unsigned-plugin` 会留下明确 bypass 证据，不能作为生产验收。

原生 Bundle 仓库再使用第三个、相互独立的信任域 `PocoDDSBundleRepository`。发布流水线通过
`bundle_repository_publisher.py` 对原生 `pdr-bundle-repository-check` 计算的确定性仓库摘要生成
Ed25519 分离证明；`bundle-repository-trust-policy.schema.json` 按
`publisherId + keyId + repositoryPatterns` 授权并固定公钥摘要、有效期和吊销状态。证明、策略和
公钥都位于候选仓库外，Runtime 在 OSP 初始化前验证，BundleManager 与 Launcher 在预检、激活和
probation 边界重复核对。生产配置必须启用该门禁；发布私钥只能由受保护流水线通过命名环境变量
提供。Release、Plugin、Bundle Repository 三种产品标识和策略不得共用授权权限。

仓库证明 schema v2 还签署正 63 位 `rolloutSequence`。BundleManagement 在候选解析前将其与仓库
专属耐久高水位比较：低序号拒绝、同序号仅允许同一摘要幂等重试；只有 Launcher probation 或人工
启动的完整 Runtime 门禁提交后才推进。高水位使用独立跨进程锁和 flush/原子替换，不来自候选仓库。
自动回退只发生在高水位推进前；`committing` 崩溃恢复必须继续提交。受控降级使用第四个独立信任域
`PocoDDSBundleRepositoryBreakGlass`：请求同时绑定源高水位文件摘要、完整源/目标授权、原因、工单、
UUID 和最长 24 小时有效期，审批策略按 approver/key/repository/action 授权，通过
`minimumApprovals` 设置最多 16 人的 M-of-N 门槛，并可设置更短 TTL、有效期和吊销。同一审批人或
同一密钥不能重复计数。执行端在同一高水位 OS 锁内重新验证发布者与全部审批者的 Ed25519 信任链、
原子切换并记录一次性消费。追加审计使用递增序号和 previous/self SHA-256 形成可离线验证的哈希链；
审批密钥不能复用 Bundle 发布密钥，生产运维仍不得删除或手工改写高水位。
执行前的 `preflight` 还要求当前实际 Bundle 仓库摘要等于审批绑定的源高水位，并在同一文件系统真实
复制和重新授权 staging、检查空间与审计链，但不切换仓库或消费审批；停机确认必须单独进入证据。
正式执行的每个持久边界写入带自身 SHA-256 的事务 journal。中断恢复重新读取实际高水位和目录摘要：
提交前只能回滚到 exact source，提交后只能前向补齐消费与审计，不能相信可编辑的状态名称反向降级。

项目配置审批使用第五个独立产品标识 `PocoDDSRuntimeProjectConfiguration`，不能复用 Release、
Plugin、Bundle Repository 或 BreakGlass 的授权策略。策略按 JSON Pointer 高风险路径分别要求
M-of-N、必需角色和发起人分离；请求精确绑定事务计划、策略、工单和短期有效期。应用端从受保护
来源固定策略 ID/SHA-256，使用项目外公钥目录和安装侧原生验签器，并在全局配置事务锁内再次验证。
未命中规则的普通配置不要求多人签名；配置了高风险规则后，缺少任何审批参数必须 fail-closed。
生产部署必须同时启用 `--require-approval-policy`，防止删除策略引用后重新规划造成降级绕过。
配置事务 journal v3 将计划和候选配置复制到事务私有状态文件，并把每个终态写入带强制 actor、
previous-record SHA-256 和持久 head 的审计链。离线验证同时检查链、head、尾部截断和 journal
双向绑定。独立审计身份应周期性生成 Ed25519 签名检查点，绑定 sequence、末记录、完整日志和
head 摘要；部署门禁固定 key ID 与公钥 SHA-256，并验证签名序列是当前日志的精确前缀。签名私钥、
检查点和信任 pin 必须位于配置事务状态之外，检查点还应上传 WORM 或远端审计系统。只有保存在
独立信任域中的检查点才能在本地日志与 head 一并删除或回滚后提供外部存在性证明。
新的事务 journal 和活动锁还记录发起人；只读 `project config status --check` 聚合锁、待恢复事务
与审计健康，供 CI 或接手人员在恢复/提交前 fail-closed。该状态报告不替代 journal、审计验签或
操作系统 ACL，也不会自动执行恢复。Windows 进程存活探测使用只读进程查询，不发送 signal；新锁
还绑定进程创建身份，以免 PID 复用造成错误的活动锁判断。

同一证明还必须绑定已签名发布清单和 SPDX 2.3 SBOM 的 SHA-256，以及 Runtime 版本、干净 Git
commit、Builder、构建 Profile 和完整 artifact-set 摘要。发布器逐文件确认 Bundle 仓库被发布清单
覆盖；Runtime 从候选仓库外重新读取并计算发布清单/SBOM 摘要，在 OSP 解析前复核版本和来源。
这些字段随高水位及 LKG 持久化，恢复时不允许把相同仓库摘要关联到不同来源证据。
