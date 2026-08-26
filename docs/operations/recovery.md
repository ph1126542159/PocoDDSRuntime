# 恢复手册

1. 保存日志、配置、健康详情和数据目录副本。
2. 停止 Runtime 和受管子进程。
3. 恢复上一份已验证配置；禁止删除未知来源的数据目录。
4. 重启并依次验证 live、ready、detail。
5. 执行协议、DDS、持久化和业务 Smoke Test。
6. 记录故障时间、影响、恢复版本和证据。

当前仓库尚未实现整个产品镜像的生产 OTA/A-B 回滚，本手册不替代板卡 bootloader 恢复流程。
原生 OSP Bundle 仓库已有 Launcher 级进程代次回退，但不覆盖 Runtime 可执行文件、配置、数据库或固件。

## Capability 策略数据库

`pdr.service.capabilityRuntime` 默认把权威策略、跨重启幂等记录和授权审计保存在 Bundle 的
`var/capabilities.sqlite`。恢复前必须停止 Runtime，同时保留主文件及同目录的 `-wal`、`-shm`
文件；不要只复制或删除其中一个文件。

离线检查命令：

```powershell
python tools/pdr.py capability store-check `
  --database <capabilities.sqlite> `
  --seed-policy contracts/capabilities/default-policy.json
```

退出码 0 表示 SQLite 完整性、策略文档和摘要一致；退出码 2/3 表示必须人工恢复。策略文件仅用于
空数据库 seed，已有数据库与文件不同会报告 `sourceDrift`，不会自动覆盖。恢复应从同一 generation
的受控备份还原三个 SQLite 文件，再启动并核对 generation、digest、审计数量及依赖 Bundle 状态。
检查和策略换代工具使用操作系统级独占租约，Runtime 未停止时会直接拒绝操作；`.lock` 文件可以
跨退出保留，是否占用以操作系统句柄为准，不要据文件存在与否判断。数据库错误触发
`recoveryRequired` 后不会自动恢复授权，必须先离线检查通过，再重启 Runtime。

受控离线换代命令如下；`request-id` 必须来自变更单，重试时保持完全相同，generation 必须取自
前一步 `store-check`：

```powershell
python tools/pdr.py capability store-apply `
  --database <capabilities.sqlite> `
  --seed-policy contracts/capabilities/default-policy.json `
  --candidate-policy <reviewed-policy.json> --actor operator `
  --request-id <change-id> --expected-generation <generation>
```

## Bundle 维护事务日志

Lifecycle Runtime 默认把排空/恢复计划、执行步骤和幂等响应保存在自身 Bundle 数据目录的
`maintenance.sqlite`；也可通过 `pdr.lifecycleRuntime.database` 指定绝对路径。启动时若发现
`draining` 或 `restoring`，会在 OSP 完成启动后恢复中断事务；已经完成的 `drained` 和
`restoreRolledBack` 是持久化停止意图，不会自动恢复。

先检查健康与待恢复计划：

```powershell
Invoke-RestMethod http://127.0.0.1:9080/health/detail
Invoke-RestMethod http://127.0.0.1:9080/api/v1/lifecycle-maintenance
```

出现 `PDR-HEALTH-LIFECYCLE-RECOVERY_PENDING` 时，先恢复计划中缺失或无法启动的 Provider /
Consumer，再使用一个来自变更单的新请求 ID 重试；同一重试必须保持相同 ID 和正文：

```powershell
$headers = @{ Authorization = 'Bearer <management-token>'; 'X-PDR-Request-Id' = '<change-id>' }
$body = @{ action = 'recover'; planId = 'maintenance-1' } | ConvertTo-Json -Compress
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:9080/api/v1/lifecycle-maintenance `
  -Headers $headers -ContentType application/json -Body $body
```

完整 Runtime 重启时，Lifecycle Runtime 会先于可管理业务 Bundle 恢复 desired-stopped 守卫。
旧 `drained` 计划继续保持 Provider 与 Consumer 闭包为 `RESOLVED`；不要直接启动其中某个 Bundle，
应使用新的变更单请求 ID 执行 `restore`。若健康报告
`PDR-HEALTH-LIFECYCLE-DESIRED-STATE-MISMATCH`，说明计划中的 Bundle 缺失或意外 Active，先核对
Bundle 包和计划拓扑，不能通过删除日志绕过。

若报告 `PDR-HEALTH-LIFECYCLE-DESIRED-STATE-UNAVAILABLE`，Runtime 已进入 fail-closed：Liveness
保留，但 Readiness 为 503，所有 `pdr.management.manageableBundles` 范围内的业务 Bundle 都不会
自动启动。停止 Runtime 后使用 `pdr.py lifecycle store-check/store-backup` 检查或恢复数据库；
在数据库重新通过完整性校验前，不要改小 manageable 范围规避保护。

离线检查会执行完整 SQLite、表索引和每条 JSON 负载的一致性校验，并输出有界计划历史：

```powershell
python tools/pdr.py lifecycle store-check `
  --database <maintenance.sqlite> --limit 256
```

一致性备份必须在 Runtime 停止后执行。工具通过 SQLite 快照生成单文件备份，再重新打开并校验
记录数和负载；目标必须不存在，工具不会覆盖已有备份：

```powershell
python tools/pdr.py lifecycle store-backup `
  --database <maintenance.sqlite> `
  --destination <maintenance-20260824.sqlite>
python tools/pdr.py lifecycle store-check `
  --database <maintenance-20260824.sqlite> --limit 256
```

不要在线只复制主文件，也不要手工编辑记录。数据库使用操作系统级独占租约，Runtime 或第二个
离线工具仍持有同一路径时会直接失败；`.lock` 文件可跨退出保留，占用状态以操作系统句柄为准。
需要还原时先停止 Runtime、保存故障现场，再用已通过 `store-check` 的受控备份整体替换源库；
启动时的 SQLite 完整性、数据库打开或写入失败均为 fail-fast。重启后核对计划终态、Readiness
与实际 Bundle 状态。

## Bundle 仓库离线恢复

原生 OSP Bundle 不在运行进程内做全量卸载/替换。仓库预检失败时事务为 `rejected`，Runtime 不变；
预检通过时事务为 `restartRequired`，必须由进程边界应用。先读取状态和 LKG 清单：

```powershell
python tools/bundle_repository_recovery.py status `
  --state-dir <runtime>\data\bundle-manager `
  --repository <runtime>\bundles
```

如果新仓库导致进程无法完成启动，停止 Runtime，保留日志与故障仓库，然后执行：

```powershell
python tools/bundle_repository_recovery.py restore `
  --state-dir <runtime>\data\bundle-manager `
  --repository <runtime>\bundles `
  --runtime-stopped --report <bundle-recovery-report.json>
```

工具要求显式确认停机，先校验每个 LKG archive/directory 的 manifest，再同卷切换；原故障仓库保留
为 `bundles.pdr-previous`。随后重启并检查 `transaction.properties` 为 `startup/committed`、
Readiness 为 200、Bundle 数量/版本和业务接口均符合预期。文件恢复、进程启动和端到端验收是三个
不同门禁。

若使用 `pdr-launcher` 且启用 `deployment.enabled`，正常流程会自动保留 `deployment-rollback/`，并在
候选进程无法写入同事务 `activationReady`、Readiness 超时或 probation 内退出时，先恢复旧仓库再
重启。Launcher 自身在 `activating`/`rollingBack` 状态崩溃后，下一次启动也会先恢复旧仓库。
此自动回退只对 Launcher 管理的单一 Bundle 仓库生效；`rollbackFailed`/fatal 日志必须按上面的
离线工具流程处理，禁止继续制造重启循环。

`transaction.properties`、`deployment.properties` 中的 `candidateDigest` 必须一致，并与当前仓库
重新计算的 SHA-256 相同。出现 digest mismatch 表示预检后仓库发生变化，不能通过改状态文件继续；
应保存现场，重新完整投放候选并产生新事务。`deployment.lock` 文件可以跨正常退出和崩溃保留，
占用由 Windows 独占文件句柄或 POSIX `flock` 决定；禁止据文件存在而删除，第二个 Launcher 报租约
冲突时应先确认原 Launcher/服务实例的实际进程状态。

### 团队契约 Registry 写者租约恢复

Registry 的 `.registry-write.lock` 和远程控制目录的 `.command.lock` 同样是 Owner 证据，不是需要
清理的互斥标志。先查询本地和远程状态：

```powershell
python <runtime>\bin\pdr.py contract-package registry-lease-status `
  --registry <contract-registry> --report <evidence>\registry-lease.json
python <runtime>\bin\pdr.py contract-package registry-remote-lease-status `
  --url https://<registry-host>:9443 --registry-id <registry-id> `
  --token-environment PDR_TEAM_REGISTRY_AUDITOR_TOKEN `
  --report <evidence>\registry-remote-leases.json
```

若报告 `active=true`，先核对 Owner 主机/PID 和进程监督器，不能删除文件绕过活动句柄。若 Owner 已
崩溃，操作系统已释放所有权，正常重启服务即可获取更高 epoch 并覆盖最近 Owner 元数据；无需也不得
执行“stale lock 删除”。若 `healthy=false`，保留 `.lock`、`.epoch.json`、Registry 当前 pointer、
远程 audit head 和进程日志。epoch 损坏或与 Owner 不一致会阻止新写入，必须从已验证恢复点恢复该
fencing 状态并重新执行 Registry/audit 验证，不能把 epoch 重置为 0。该流程只恢复单机单写者，不能
替代分布式协调器或把共享网络目录当成多节点共识。

若 Registry 数据目录整体丢失，不能从 Consumer 缓存、单个 channel resolution 或手工复制的最新
`registry.json` 拼装。使用 `registry-recovery-verify` 在目标主机独立复验已固定 SHA-256 的
`.pdrregistry`，确认其中外部 anchor 精确绑定恢复 revision；随后在旧写节点已隔离且目标路径不存在
的条件下执行 `registry-recovery-restore --confirm-source-unavailable`。恢复成功后先离线执行
`registry-verify` 与 `registry-anchor-verify`，再恢复远程 control/audit 状态并验证 request 幂等链接，
最后才启动远程服务。该恢复命令不会覆盖现有 Registry，也不会自动把恢复节点提升为分布式 Leader。

启用仓库发布者授权后，恢复还必须保留候选摘要对应的 `<digest>.attestation.json`、
`<digest>.sig.json`、信任策略和 `<keyId>.pem`。这些文件必须位于 Bundle 仓库外；不要把故障候选中的
策略或公钥复制为新信任根。若错误为缺少证明、未知发布者、公钥摘要不符、策略固定值不符或密钥已
撤销，应先保留现场并由发布流水线重新生成/批准证据，禁止编辑事务文件或临时关闭
`authorization.required` 绕过。密钥轮换应先发布同时允许旧、新密钥且摘要已固定的新策略，验证新
密钥候选，再撤销旧密钥。

`repository-rollout-high-water.properties` 与 `last-known-good.properties` 是恢复安全边界，不能删除、
回写或从候选仓库覆盖。恢复工具会重新计算 LKG 确定性摘要，并要求仓库身份、`rolloutSequence` 和
摘要与已接受高水位完全一致；较低序号、同序号不同内容、缺失授权元数据或旧式重命名快照都会在
仓库切换前拒绝。`activating`/`rollingBack` 可恢复旧代次；`committing` 表示高水位可能已写入，只能
由 Launcher 幂等完成提交，不得离线回退。确需降级必须走独立的 break-glass 审批流程，不能手工
修改高水位。该流程只允许在 Runtime/Launcher 已停止后执行，并把已接受高水位文件的 SHA-256、
原序号/摘要、目标发布者授权和完整来源、原因、工单、UUID 与过期时间绑定到同一审批请求。

先在恢复主机用目标仓库现有的发布者证明创建未签名请求；`pdr-bundle-repository-check authorize`
会重新验证目标仓库摘要、发布者 Ed25519 签名、固定策略、公钥、发布清单和 SBOM：

```powershell
$TargetAuth = @(
  '--target-repository', '<staged-old-release>\bundles',
  '--fingerprint-executable', '<runtime>\bin\pdr-bundle-repository-check.exe',
  '--repository-id', 'runtime-main',
  '--evidence-directory', '<staged-old-release>\bundle-evidence',
  '--publisher-trust-policy', '<trusted>\bundle-repository-policy.json',
  '--expected-publisher-trust-policy-id', 'bundle-policy-v1',
  '--expected-publisher-trust-policy-sha256', '<pinned-policy-sha256>',
  '--publisher-trusted-keys-directory', '<trusted>\bundle-publisher-keys'
)
python <runtime>\bin\bundle_repository_break_glass.py request `
  --state-dir <runtime>\data\bundle-manager --repository <runtime>\bundles @TargetAuth `
  --reason 'Production regression requires known-good rollback' `
  --ticket INC-2026-0042 --valid-for-minutes 30 `
  --output <transfer>\downgrade-request.json
```

把请求分别传给策略要求的独立审批人；审批私钥路径只通过命名环境变量注入，审批人不接触目标
主机写权限。下面示例由两个不同审批人在各自受控主机执行，生成两个签名：

```powershell
$env:PDR_BREAK_GLASS_KEY = '<secure>\recovery-officer.pem'
python bundle_repository_break_glass.py approve `
  --request <transfer>\downgrade-request.json `
  --approver-id recovery-officer --key-id recovery-officer-2026 `
  --private-key-path-environment PDR_BREAK_GLASS_KEY `
  --signature-output <transfer>\downgrade-request.sig.json
Remove-Item Env:PDR_BREAK_GLASS_KEY

$env:PDR_BREAK_GLASS_KEY = '<secure>\security-officer.pem'
python bundle_repository_break_glass.py approve `
  --request <transfer>\downgrade-request.json `
  --approver-id security-officer --key-id security-officer-2026 `
  --private-key-path-environment PDR_BREAK_GLASS_KEY `
  --signature-output <transfer>\downgrade-request.security.sig.json
Remove-Item Env:PDR_BREAK_GLASS_KEY
```

审批返回后先使用同一组 `$TargetAuth` 参数执行无切换、无消费的 `preflight`，并另外固定独立的
`PocoDDSBundleRepositoryBreakGlass` 审批策略 ID/SHA-256、公钥目录和当前可信验签器。
安装包的 `share/PocoDDSRuntime/examples/bundle-break-glass-trust-policy.example.json` 提供默认
`2-of-3` 模板；使用前必须替换全部审批身份、仓库范围和公钥 SHA-256，再把最终策略摘要固定到
站点配置或受控工单中，示例中的全零摘要只会 fail-closed。

```powershell
$Approval = @(
  '--request', '<transfer>\downgrade-request.json',
  '--signature', '<transfer>\downgrade-request.sig.json',
  '--signature', '<transfer>\downgrade-request.security.sig.json',
  '--approver-trust-policy', '<trusted>\break-glass-policy.json',
  '--expected-approver-trust-policy-id', 'break-glass-policy-v1',
  '--expected-approver-trust-policy-sha256', '<pinned-approver-policy-sha256>',
  '--approver-trusted-keys-directory', '<trusted>\break-glass-keys',
  '--signature-check-executable', '<runtime>\bin\pdr-signature-check.exe'
)
python <runtime>\bin\bundle_repository_break_glass.py preflight `
  --state-dir <runtime>\data\bundle-manager --repository <runtime>\bundles `
  @TargetAuth @Approval --report <evidence>\break-glass-preflight.json

# 停止 Runtime/Launcher 后再次预演；只有这次报告的 applyReady 才能为 true。
python <runtime>\bin\bundle_repository_break_glass.py preflight `
  --state-dir <runtime>\data\bundle-manager --repository <runtime>\bundles `
  @TargetAuth @Approval --runtime-stopped

python <runtime>\bin\bundle_repository_break_glass.py apply `
  --state-dir <runtime>\data\bundle-manager --repository <runtime>\bundles `
  @TargetAuth @Approval `
  --runtime-stopped
```

`preflight` 会验证源仓库实际摘要、高水位、M-of-N 签名、目标发布授权、审计链、可用空间，并真实
复制/复核临时 staging；它不切换仓库、不修改高水位、不消费审批，最终删除 staging。报告带
`evidenceSha256`，未确认停机时 `applyReady=false`。`apply` 在同一个高水位 OS 独占租约内重新执行
这些关键检查，再复制并复核 staging，然后
切换仓库和高水位；旧仓库保留为 `bundles.pdr-previous`。审批过期、签名/目标/源状态漂移、策略吊销、
审批人数不足、审批人或密钥重复、锁冲突、已有 previous/staging 或 UUID 已消费都会在切换前拒绝。
策略的 `minimumApprovals` 定义 M-of-N 门槛，同一个审批人使用多把密钥不能重复计数。一次性记录
保存在 `break-glass-consumed/`，审计在 `break-glass-audit.jsonl`；每条审计含递增序号、上一记录
SHA-256 和自身 SHA-256。完成后或取证时验证完整哈希链：

```powershell
python <runtime>\bin\bundle_repository_break_glass.py verify-audit `
  --state-dir <runtime>\data\bundle-manager `
  --report <evidence>\break-glass-audit-verification.json
```

验证报告中的 `headSha256` 应随工单证据导出到独立、只追加或 WORM 存储；本地哈希链能发现记录内容
及中间链路篡改，但本地文件本身不等同于外部不可变存储。

`apply` 还会在 `break-glass-transactions/<approvalId>.json` 持久化并自校验以下状态：
`prepared → authorized → previousSaved → activated → highWaterCommitted → consumed → completed`。
进程在任一步崩溃后，不要删除 journal、staging、previous 或消费记录，也不要直接启动 Runtime；先执行：

```powershell
python <runtime>\bin\bundle_repository_break_glass.py recover `
  --state-dir <runtime>\data\bundle-manager `
  --repository <runtime>\bundles `
  --fingerprint-executable <runtime>\bin\pdr-bundle-repository-check.exe `
  --approval-id <approval-uuid> --runtime-stopped `
  --report <evidence>\break-glass-recovery.json
```

恢复决策不依赖 journal 中声称的最后状态，而以锁内重新读取的耐久高水位为提交边界：高水位仍是
源代次时恢复 exact previous 并清理已验证的 staging；高水位已是目标代次时禁止回退，只能补齐消费、
审计和 `completed`。高水位既不匹配源也不匹配目标、目录摘要不符或 journal 自身哈希不符时全部
fail-closed，必须保留现场人工处置。`recover` 可对 `completed/rolledBack` 终态幂等复核。

文件切换成功只表示需要重启；仍须
分别验证启动、Readiness、目标 Bundle/业务接口及后续 LKG 提交。

高水位 schema v2 还要求 LKG 元数据中的发布清单、SPDX SBOM、artifact-set SHA-256、版本、Git
commit、Builder 和 Profile 全部一致。恢复工具先验证这些来源字段，再复制任何文件；来源缺失或
不一致时保持当前仓库不变并拒绝恢复。

## 受管进程期望状态恢复

只有显式配置 `subprocess.desiredStatePersistence.enabled=true` 的部署才使用该恢复路径。人工停止后
重启 Runtime，进程仍应显示为 `stopped`；正常 Runtime 关闭不是人工停止，不会清除原有运行授权。
快照默认位于 Runtime 根目录下 `data/process-desired-state.json`，同目录的 `.previous` 是上一完整
代次，`.new` 是尚未提交、不能作为授权恢复的原子切换暂存文件，`.lock` 是当前单写者的只读
Owner 元数据。锁由 OS 句柄持有；仅删除 `.lock` 既不能解除活跃锁，也会破坏取证。

提交顺序固定为：写入并刷盘 `.new`、原子替换 `.previous`、原子替换主文件。POSIX 在每次替换后
同步父目录，Windows 使用 write-through 文件和重命名标志。若主文件在第二步后暂时缺失，读取器
只能回退完整 `.previous`；无论何时都不得把残留 `.new` 当作已提交授权。

主快照损坏时，ProcessManagement 会自动验证并回退到一个有效候选，同时写出新的规范主快照。
若主文件和 `.previous` 都存在但无法通过 schema/摘要校验，Runtime 会在启动任何受管进程
前失败。此时不要删除或手改文件来强制启动；先保留三份文件和 Runtime 日志作为故障证据，再由
运维负责人根据最后一份已确认的人工启停记录决定恢复值。若确实没有可接受的历史状态，应在停机
窗口移走整个专用状态集合、记录审批，并让 Runtime 从配置默认值建立新代次；这属于人工恢复，
不是自动通过。

Runtime 在线期间，监督线程按配置周期重新校验当前主文件和存在的 `.previous`。在线发现损坏时
不会自动回退旧授权或停止仍正常运行的子进程，而是把 ProcessGraph 标记为 `primary-invalid`/
`previous-invalid`，并让 `/health/ready` 返回 503。先保存现场；若当前内存授权和实际进程状态
已由操作员核对，可通过正常、已授权的生命周期操作提交新代次。提交成功且回读通过后健康自动
恢复；集成独立治理控制面的产品也可以在完成身份、审计、幂等和现场核对后调用带当前代次 CAS
的无生命周期副作用重新提交原语。无法核对时必须停机走离线恢复，不能只为恢复 HTTP 200 而
覆盖证据。

可重复故障注入验证：

```powershell
ctest --test-dir build -C Release -R subprocess-manager-desired-state-smoke --output-on-failure
ctest --test-dir build -C Release -R process-desired-state-store-durability-smoke --output-on-failure
ctest --test-dir build -C Release -R runtime-process-desired-state-integration --output-on-failure
```

这些测试验证进程管理器、真实本地测试子进程，以及三个提交检查点的独立写进程突然终止；它们会
实际执行平台刷盘和元数据同步原语，但不等同于拔电、存储控制器断电保护验证、生产 Runtime 升级
或 24/72 小时长稳验收。

## 主机故障注入基线

以下命令执行可重复的依赖中断、重试退避、重复命令、队列背压和优雅关闭场景：

```powershell
ctest --test-dir build -C Release -L fault-injection --output-on-failure
```

它验证框架公共可靠性原语，不等同于真实网络、设备或 24/72 小时长稳。真实协议故障、
进程崩溃和板卡 HIL 应在后续分层测试中登记，并保留注入条件和恢复证据。
