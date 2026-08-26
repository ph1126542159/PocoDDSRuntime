# BundleManagement 组件

## 职责与边界

`platform/BundleManagement` 提供两层明确分离的能力：`BundleManager` 只治理所属进程的 OSP Bundle
仓库，负责稳定扫描、发布者授权、严格预检、启动拓扑验证、事务日志和 LKG；
`BundleDeploymentCoordinator` 提供给外部 Host/Launcher，负责原生 Bundle 的进程边界激活、代次应答、
提交和离线回退。两者共享耐久状态目录，但都不依赖 `SystemMonitoring.cpp`。部署事务使用仓库名称、
类型和文件内容的确定性 SHA-256 指纹绑定候选代次，不依赖时间戳或绝对路径。

原生 OSP Bundle 的动态库与进程生命周期绑定。生产默认不会在同一进程中执行“全部停止、卸载、
加载新动态库”；仓库变化通过预检后记为 `restartRequired`，当前 Runtime 保持服务，随后由受控
进程重启应用。这样避免 native library 卸载导致进程崩溃、使 C++ 异常回滚失效。

## 事务流程

后台线程把路径、文件大小和修改时间组成快照。变化必须连续达到 `stableScanCount` 次一致后才进入：

```text
仓库稳定
→ 连续两次计算确定性 candidateDigest 并要求一致
→ 从候选仓库外读取 <digest>.attestation.json 和 <digest>.sig.json
→ 使用当前可信策略、公钥和 Ed25519 验证发布者授权
→ 要求签名 rolloutSequence 不低于耐久高水位；同序号只能对应同一摘要
→ 严格解析每个 Bundle（不修改 BundleLoader）
→ 选择每个 symbolic name 的最高版本
→ 校验 Bundle 与 module 依赖
├─ 失败：rejected，在线 Runtime 不变
└─ 通过：restartRequired，在线 Runtime 不变
   → Launcher 重新计算 candidateDigest 并取得 OS 独占租约
   → 保存独立 deployment-rollback
   → 受控重启
   → Runtime 再次核对 candidateDigest
   → 启动拓扑与 active 状态门禁通过，写入同事务 activationReady
   → Readiness probation 通过：committing → 推进高水位 → committed
   └─ probation 前失败：高水位不变，停机恢复旧仓库并重启 LKG
```

严格预检与旧的 `BundleRepository::loadBundles()` 不同：坏包、缺 Bundle、版本不兼容或缺 module
会返回错误，不会只写日志后继续形成部分拓扑。相同的已拒绝快照不会每个扫描周期重复执行；文件
再次变化后才重新预检。

`stateDirectory` 中保存：

- `transaction.properties`：当前事务终态（`committed`、`rejected`、`restartRequired` 等）；
- `transactions.jsonl`：追加式部署审计；
- `last-known-good/`：保留原始相对路径和文件名的已提交 Bundle 仓库精确副本；
- `last-known-good.properties`：LKG 的摘要、授权和 rollout sequence；
- `repository-rollout-high-water.properties`：已接受仓库的单调发布序号、摘要和授权证据；
- `repository-rollout-high-water.lock`：高水位跨进程独占租约；文件存在不等于正在占用；
- `deployment.properties`：Launcher 激活终态（`activating`、`committed`、`rolledBack` 等）；
- `deployment-transactions.jsonl`：跨进程激活追加审计；
- `deployment-rollback/`：仅在候选 probation 期间保留的旧代次副本；
- `deployment.lock`：跨 Launcher 操作系统独占租约文件；文件可持久存在，占用状态以锁句柄为准；
- `recovery-audit.jsonl`：离线恢复审计。

## API

```cpp
PocoDDS::BundleManagement::BundleManagerOptions options;
options.repositories = configuration->getString("osp.bundleRepository");
options.stateDirectory = configuration->getString("osp.bundleMonitor.stateDirectory");
options.intervalMilliseconds = 1000;
options.stableScanCount = 2;
options.inProcessReloadEnabled = false;
options.authorization.required = true;
options.authorization.repositoryId = "runtime-main";
options.authorization.evidenceDirectory = "D:/PocoDDSRuntime/bundle-trust/evidence";
options.authorization.trustPolicyFile = "D:/PocoDDSRuntime/bundle-trust/policy.json";
options.authorization.expectedTrustPolicyId = "runtime-bundles-v1";
options.authorization.expectedTrustPolicySha256 = "<64 lowercase hex>";
options.authorization.trustedKeysDirectory = "D:/PocoDDSRuntime/bundle-trust/keys";

PocoDDS::BundleManagement::BundleManager manager(ospSubsystem, logger, options);
manager.start();
manager.reloadNow(); // 立即预检；生产默认不会原地卸载 native Bundle
manager.stop();
```

Launcher 侧使用独立协调器；`rollback()` 的调用前置条件是被监督 Runtime 已停止：

```cpp
PocoDDS::BundleManagement::BundleDeploymentCoordinator deployment({
    runtimeBundleDirectory, runtimeBundleStateDirectory});
if (deployment.activationRequested()) {
    const auto id = deployment.beginActivation();
    // stop old child, launch candidate, wait for activationReady/readiness
    deployment.commit(id);       // success
    // deployment.rollback(id, error); // candidate stopped and gate failed
}
```

可读取 `successfulReloads()`、`failedReloads()`、`rejectedReloads()`、
`restartRequiredReloads()`、`rolledBackReloads()` 和 `lastError()`。`successfulReloads()` 只表示显式
启用的进程内事务完成，不能代替进程重启验收。

`BundleRepositoryFingerprint::calculateDirectory()` 可供部署工具计算同一格式的 SHA-256。Coordinator
仅支持一个明确的目录；多仓库列表、glob 或单文件仓库仍可由 BundleManager 预检，但不会生成可供
跨进程自动激活的 `candidateDigest`，因此 Launcher 会 fail-closed 拒绝自动切换。
每次计算会连续读取两遍并要求摘要一致，同时校验读取前后文件长度；部署端仍应使用临时文件加
同卷原子重命名，不能把双读校验当作允许边写边部署。

## 配置

```properties
osp.bundleRepository = ${application.dir}bundles/
osp.bundleMonitor.enabled = false
osp.bundleMonitor.intervalMilliseconds = 1000
osp.bundleMonitor.stableScanCount = 2
osp.bundleMonitor.stateDirectory = ${application.dir}data/bundle-manager/
osp.bundleMonitor.inProcessReloadEnabled = false
osp.bundleMonitor.authorization.required = true
osp.bundleMonitor.authorization.repositoryId = runtime-main
osp.bundleMonitor.authorization.evidenceDirectory = D:/PocoDDSRuntime/bundle-trust/evidence/
osp.bundleMonitor.authorization.trustPolicyFile = D:/PocoDDSRuntime/bundle-trust/policy.json
osp.bundleMonitor.authorization.expectedTrustPolicyId = runtime-bundles-v1
osp.bundleMonitor.authorization.expectedTrustPolicySha256 = <64 lowercase hex>
osp.bundleMonitor.authorization.trustedKeysDirectory = D:/PocoDDSRuntime/bundle-trust/keys/
```

`inProcessReloadEnabled=true` 仅保留旧行为兼容和受控开发实验。包含原生 activator library 的生产
Runtime 不得开启。Runtime 默认关闭自动监视；需要部署预检时显式开启，仍保持进程内替换关闭。
开发配置默认允许关闭发布者授权；`security.profile=production` 会要求
`osp.bundleMonitor.authorization.required=true`，且所有信任策略固定项必须完整。信任策略、可信公钥
和摘要绑定的证明目录必须位于候选仓库外，并由当前可信安装、只读镜像或独立 bootstrap 提供，不能
由待验证候选覆盖。

发布流水线使用安装后的原生指纹工具产生与 Runtime 完全相同的摘要，再生成外置证明：

```powershell
$env:PDR_BUNDLE_SIGNING_KEY = 'D:\release-secrets\bundle-ed25519.pem'
python tools/bundle_repository_publisher.py sign `
  --repository D:\staging\runtime\bundles `
  --fingerprint-executable D:\PocoDDSRuntime\bin\pdr-bundle-repository-check.exe `
  --repository-id runtime-main --rollout-sequence 202608250001 `
  --publisher-id release-team --key-id bundle-2026-q3 `
  --private-key-path-environment PDR_BUNDLE_SIGNING_KEY `
  --release-manifest D:\staging\release\SHA256SUMS.json `
  --release-sbom D:\staging\release\pocoddsruntime.spdx.json `
  --release-artifacts-root D:\staging\runtime `
  --output-directory D:\staging\bundle-evidence
```

`rolloutSequence` 必须是 `1..2^63-1` 的正整数，并由每个 `repositoryId` 的发布流水线单调分配；不能
使用时间戳猜测、并行任务各自自增或重复序号签署不同内容。私钥路径和可选口令只从指定环境变量
读取。发布器拒绝 dirty 发布清单，并要求仓库位于显式的制品根中、每个仓库文件的大小和摘要都由
发布清单覆盖；清单本身必须绑定 SPDX 2.3 SBOM 和 Builder/Profile/artifact-set 来源。成功后会在
仓库外保存 `<digest>.release-manifest.json`、`<digest>.spdx.json`、attestation 和签名四份证据。

成功事务会把 `repositoryId`、`rolloutSequence`、`publisherId`、`signingKeyId`、`trustPolicyId`、
策略/attestation/发布清单/SBOM/artifact-set SHA-256、版本、Git commit、Builder 和 Profile 同候选
摘要一起写入事务、部署审计、高水位和 LKG 元数据；Launcher 和 Runtime 必须得到完全相同的授权
证据。策略可同时允许旧、新两把密钥完成轮换，再把旧密钥加入
`revokedKeys`；不要先撤销仍在运行代次所需的唯一密钥。

高水位只在 Runtime 写出精确 `activationReady` 且 Launcher 的 Readiness probation 通过后推进。
候选启动失败或 probation 内退出不会推进，因此自动回退仍能启动旧 LKG；高水位推进后，低序号
仓库即使签名仍有效也会在 OSP 初始化前拒绝。`committing` 是不可自动回退的持久边界：Launcher
崩溃后必须幂等完成高水位提交，不能恢复旧仓库。

从旧签名格式迁移时，先用新的 attestation schema v2 为**当前在线仓库**分配初始序号并启动一次
新 Runtime，确认 schema v2 高水位和精确 LKG 已生成，再投放更高序号候选。早期仅含序号的
schema v1 高水位可在同序号、同摘要的完整来源验证启动中原位升级为 schema v2；不要直接从旧的带
`0000_` 前缀 LKG 开始自动部署。

部署端应先写临时文件，再在同一卷原子重命名到最终 `.bndl` 名称。看到 `restartRequired` 后执行
受控停止和重启。启用 Launcher 部署协调时，新 Runtime 会针对精确事务 ID 写入
`activationReady`；只有 Readiness probation 通过且 `deployment.properties` 为 `committed` 才算进程
代次提交。未启用协调器的人工流程仍须核对 `startup/committed`、Readiness 200 和目标 Bundle
版本/状态。

从 `restartRequired` 到候选提交期间，任何文件增加、删除、改名或内容变化都会使 SHA-256 不一致：
Launcher 在停旧进程前拒绝，或新 Runtime 在启动拓扑变更前失败退出并触发 LKG 回退。两个 Launcher
同时指向同一 `stateDirectory` 时，只有持有 `deployment.lock` OS 锁的实例可以开始、提交或回退；
进程崩溃会释放锁，不能根据 `.lock` 文件是否存在判断占用，也不要人工删除它绕过互斥。

## 停机恢复

先停止 Runtime，再检查 LKG：

```powershell
python tools/bundle_repository_recovery.py status `
  --state-dir <runtime>\data\bundle-manager `
  --repository <runtime>\bundles
```

确认进程已停止后恢复：

```powershell
python tools/bundle_repository_recovery.py restore `
  --state-dir <runtime>\data\bundle-manager `
  --repository <runtime>\bundles `
  --runtime-stopped --report <change-evidence.json>
```

工具先完整校验 LKG，再构造同卷 staging，最后以目录重命名切换；旧仓库保留为
`bundles.pdr-previous`。恢复后仍必须重启并验证健康，不能把文件切换本身算作恢复成功。

若要回到低于 `repository-rollout-high-water.properties` 的已签名代次，普通恢复仍会默认拒绝。
使用安装包内的 `bundle_repository_break_glass.py request/approve/preflight/apply/recover` 完成独立
审批：目标首先由
`pdr-bundle-repository-check authorize` 复核发布者签名和 release/SBOM 来源，审批再由独立
`PocoDDSBundleRepositoryBreakGlass` 策略验证；策略可用 `minimumApprovals` 强制 M-of-N 多人审批，
同一审批人或密钥不重复计数。执行要求 Runtime 停止、同一高水位独占锁、未过期且未消费的精确
审批；`preflight` 还会证明当前仓库摘要等于源高水位、真实复制并重新授权临时 staging、检查磁盘
空间和审计链，但不切换或消费。正式执行保留 previous 仓库、一次性消费记录和 previous/self
SHA-256 哈希链审计。完整命令、
`verify-audit` 取证检查及重启验收门禁见
`docs/operations/recovery.md`；禁止直接编辑或删除高水位文件。
执行中断时保留 `break-glass-transactions/<approvalId>.json`，使用 `recover` 在同一高水位锁内判定：
源高水位执行目录回滚，目标高水位仅允许前向完成；journal 状态文字本身不是提交依据。
