# 安全基线

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
权限列表，并可用 `identity.manage`、`audit.read`、`task.read`、`task.cancel` 分别授予身份轮换、审计查询、任务
查询和排队取消能力；`*` 表示全部八项权限。旧
`tokenEnvironment` 继续映射为 `legacy-admin` 全权限
身份，便于兼容已有部署，但新生产部署应优先使用职责分离的 Principal。认证成功但权限
不足返回 403，认证失败仍返回 401。Principal ID 会进入配置事务审计，令牌不会进入响应、
日志或报告。

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
