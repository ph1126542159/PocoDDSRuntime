# pdr-launcher 组件

## 职责

`SubSystem/launcher` 是与 OSP 服务器分离的看门狗/服务包装程序，用来启动并在需要时重新拉起指定命令。

## 实现过程

`RuntimeLauncher.cpp` 基于 `ServerApplication` 读取配置，建立日志通道，启动目标进程并处理退出/重启。它独立安装到 `processes/pdr-launcher/`，不嵌入 `pdr-runtime`。

## 用法

在 `pdr-launcher.properties` 中设置目标命令及日志，然后直接启动：

```powershell
Set-Location build/bin/processes/pdr-launcher
./pdr-launcher.exe
```

默认子进程配置不启用它。若用它监护 `pdr-runtime`，应由系统服务或外部入口启动 launcher。

## 工作流程

1. 加载可执行文件同目录配置，并在部署环境尝试 `/etc/pdr-launcher.properties`。
2. 依次执行受约束的 `preflight.N`；任一步失败或超时都不会启动目标进程。
3. 启动命令行参数指定的目标进程。
4. 若配置了 `watchdog.file`，按固定周期检查心跳文件更新时间。
5. 若启用跨进程 Bundle 部署，发现子 Runtime 的 `restartRequired` 后取得 OS 独占租约，复算仓库 SHA-256，并在停止旧进程前重新验证候选发布者授权，再保存独立回退快照和受控停止旧进程。
6. 新进程必须再次核对候选 SHA-256 和签名 `rolloutSequence`，并用同一事务 ID/指纹写入 `activationReady`；持续通过可选 Readiness 文件门禁和 probation 后进入 `committing`，推进耐久高水位后才提交该代次。
7. 候选预检、启动、Readiness 或 probation 失败时，在停机边界原子恢复 LKG，再启动旧代次。
8. 目标异常退出或心跳超时后等待 `relaunchDelay`，再重新启动；launcher 收到退出信号时停止目标进程并退出。

## 配置项

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `relaunchDelay` | `1000` | 异常退出后重新启动等待时间，毫秒 |
| `restartBudget.maxRestarts` | `5` | 滑动时间窗内允许的重启次数；`0` 表示不重启 |
| `restartBudget.windowMilliseconds` | `60000` | 重启预算滑动时间窗，毫秒 |
| `childArgument.count` | `0` | 追加给被监督程序的参数数量 |
| `childArgument.N` | 无 | 第 N 个参数，按原值传递，不经 shell 解释 |
| `childWorkingDirectory` | 空 | 子进程初始工作目录；空表示继承 Launcher，Runtime 部署应显式设为其 `bin`/应用目录 |
| `childEnvironment.count` | `0` | 预检与子进程共享的环境覆盖数量，范围 0..64 |
| `childEnvironment.N.name` | 无 | 环境变量名，最长 128 字符，不含 `=`；Windows 按大小写不敏感判重 |
| `childEnvironment.N.value` | 空 | 环境变量值，可使用配置展开，最长 32768 字符且不写入日志 |
| `preflight.count` | `0` | 每次子进程启动前按索引执行的预检数量，范围 0..16 |
| `preflight.N.name` | `preflight-N` | 日志中的稳定步骤名，不包含参数或敏感数据 |
| `preflight.N.executable` | 无 | 必填的绝对可执行文件路径；直接启动，不经 shell/PATH 解析 |
| `preflight.N.argument.count` | `0` | 参数数量，范围 0..64 |
| `preflight.N.argument.M` | 无 | 原样参数，可使用配置展开，不写入 Launcher 日志 |
| `preflight.N.workingDirectory` | 空 | 可选的绝对工作目录，必须已存在 |
| `preflight.N.timeoutMilliseconds` | `10000` | 单步超时，范围 1..300000；超时进程会被终止 |
| `resourceLimits.killProcessTreeOnExit` | `true` | Windows Job 关闭时终止全部后代进程 |
| `resourceLimits.memoryBytes` | `0` | 单个宿主进程内存硬上限；0 不限制 |
| `resourceLimits.activeProcessLimit` | `0` | Job 内活动进程上限；0 不限制 |
| `resourceLimits.cpuRatePercent` | `0` | Windows CPU hard cap，1..100；0 不限制 |
| `resourceLimits.linuxCgroupPath` | 空 | Linux 已创建并授权的 cgroup v2 绝对目录 |
| `watchdog.file` | 空 | 心跳文件路径；空表示不启用心跳监视 |
| `watchdog.timeout` | `600000` | 心跳超时，毫秒 |
| `watchdog.interval` | `60000` | 心跳检查周期，毫秒 |
| `watchdog.startupGraceMilliseconds` | `600000` | 每次启动后等待首个有效心跳的宽限期 |
| `watchdog.requireFile` | `false` | 为 `true` 时，宽限期后心跳文件缺失也判定不健康 |
| `osp.bundleMonitor.enabled` | `true` | launcher 自身 OSP Bundle 仓库监视与严格预检开关 |
| `osp.bundleMonitor.stableScanCount` | `2` | 进入预检前要求连续一致的扫描次数 |
| `osp.bundleMonitor.stateDirectory` | `${application.dir}data/bundle-manager/` | 事务日志与 LKG 目录 |
| `osp.bundleMonitor.inProcessReloadEnabled` | `false` | 原生 Bundle 不做进程内全卸载；变化记为 `restartRequired` |
| `osp.bundleRepository` | `${application.dir}bundles/` | launcher 自己的 Bundle 仓库 |
| `deployment.enabled` | `false` | 启用被监督 Runtime 的跨进程 Bundle 激活事务 |
| `deployment.repository` | `../runtime/bundles/` | 子 Runtime 的单一 Bundle 仓库目录；不得指向 launcher 自身仓库 |
| `deployment.stateDirectory` | `../runtime/data/bundle-manager/` | 子 Runtime 的 BundleManager 状态目录 |
| `deployment.pollMilliseconds` | `250` | 部署事务与子进程状态检查周期 |
| `deployment.stopTimeoutMilliseconds` | `30000` | 受控停止超时，之后强制终止候选/旧进程 |
| `deployment.startupTimeoutMilliseconds` | `120000` | 等待同事务 `activationReady` 和 Readiness 的最长时间 |
| `deployment.probationMilliseconds` | `10000` | Readiness 连续稳定后才提交的观察时间 |
| `deployment.readiness.file` | 空 | 可选的子进程业务 Readiness/心跳文件；空时仍要求 BundleManager 精确事务应答 |
| `deployment.readiness.requireTransactionId` | `false` | 要求 Readiness 文件正文包含当前事务 ID |
| `deployment.authorization.required` | `false` | 要求子 Runtime 候选仓库具有摘要绑定的发布者授权；生产必须启用 |
| `deployment.authorization.repositoryId` | 空 | 被监督仓库的稳定身份，必须与子 Runtime 一致 |
| `deployment.authorization.evidenceDirectory` | 空 | 仓库外的 `<digest>.attestation.json` 与 `<digest>.sig.json` 目录 |
| `deployment.authorization.trustPolicyFile` | 空 | 由当前可信安装提供的发布者信任策略 |
| `deployment.authorization.expectedTrustPolicyId` | 空 | 固定的信任策略 ID |
| `deployment.authorization.expectedTrustPolicySha256` | 空 | 固定的策略 SHA-256，小写 64 位十六进制 |
| `deployment.authorization.trustedKeysDirectory` | 空 | 仓库外的 Ed25519 公钥目录，文件名为 `<keyId>.pem` |

预算耗尽后 launcher 不再制造崩溃重启风暴，而是记录 critical 日志并以非零状态退出，由上一级服务
管理器告警或按更长退避策略处置。心跳超时导致的强制终止也计入同一预算。

初始启动的预检失败属于配置/部署错误，不消耗重启预算，也不会形成失败循环；Launcher 直接以非零
状态退出。Bundle 候选切换期间的预检失败复用现有事务回滚路径，恢复 LKG 后再执行相同预检。预检
可执行文件必须来自可信安装目录，禁止指向候选仓库、临时下载目录或可被低权限用户替换的位置。

Fast DDS 生产配置可这样接入，而不在 Launcher 内硬编码 DDS 逻辑：

```properties
childEnvironment.count = 2
childEnvironment.0.name = PDR_FASTDDS_PROFILE
childEnvironment.0.value = C:/PocoDDSRuntime/config/fastdds-deployment.properties
childEnvironment.1.name = PDR_FASTDDS_PROFILE_SHA256
childEnvironment.1.value = <Get-FileHash -Algorithm SHA256 的小写结果>

preflight.count = 1
preflight.0.name = fastdds-profile
preflight.0.executable = C:/PocoDDSRuntime/bin/pdr-fastdds-profile-check.exe
preflight.0.argument.count = 0
preflight.0.workingDirectory = C:/PocoDDSRuntime/bin
preflight.0.timeoutMilliseconds = 10000
```

Launcher 先复制自己的完整环境，再应用 `childEnvironment.N` 覆盖，并把同一份环境快照同时传给预检
与子 Runtime。上例中的 checker 和 Runtime 因此必然读取同一个 Profile 路径和预期 SHA-256；路径
相同但文件在预检后被替换也会拒绝，不会出现“验证内容 A、实际运行内容 B”。

部署切换是计划内重启，不消耗异常重启预算。`deployment.repository` 与
`deployment.stateDirectory` 必须和子 Runtime 的 `osp.bundleRepository`、
`osp.bundleMonitor.stateDirectory` 一致，且子 Runtime 必须启用 `osp.bundleMonitor.enabled=true` 才能产生
`restartRequired` 并在重启后应答 `activationReady`。Launcher 只在子进程停止后恢复仓库；它不解析业务 Bundle，
包和依赖是否合法仍由 Runtime 的 BundleManager 严格预检与启动拓扑门禁决定。

`deployment.authorization.*` 必须逐项镜像被监督 Runtime 的
`osp.bundleMonitor.authorization.*`。Launcher 在停旧进程前验签，Runtime 在 OSP 初始化和 Bundle
解析前再次验签，probation 期间 Coordinator 还会核对事务内的发布者、密钥、策略和证明摘要；任一
证据变化都会 fail-closed。Launcher 自己的 `osp.bundleMonitor.authorization.*` 只治理 Launcher
自身仓库，与 `deployment.authorization.*` 的子 Runtime 所有权不同，不能混用。

`deployment.stateDirectory` 还拥有 `repository-rollout-high-water.properties`。候选处于
`activating` 时失败可恢复旧 LKG，因为高水位尚未推进；一旦状态为 `committing`，高水位可能已经
写入，Launcher 重启只能幂等完成提交，禁止自动回退。发布流水线必须为同一 `repositoryId` 串行
分配正 63 位 `rolloutSequence`；低序号或同序号不同摘要都会在停旧进程前拒绝。

Launcher 与 Runtime 安装在不同目录时必须设置 `childWorkingDirectory`。默认安装布局中 Launcher 位于
`bin/processes/pdr-launcher/`、Runtime 位于 `bin/`，可配置为：

```properties
childWorkingDirectory = ${application.dir}../../
```

该目录同时决定子 Runtime 的相对配置、动态库搜索和运行期相对路径边界；不要依赖启动 Launcher 的
交互式 shell 当前目录。

生产配置应使用单一、明确、绝对的子 Runtime Bundle 目录。自动部署不会接受 glob、多仓库列表、
缺少 `candidateDigest` 的旧事务或指纹已变化的仓库。`deployment.lock` 是保留的租约载体，不是需要
清理的临时文件；第二个 Launcher 会被明确拒绝，持锁进程崩溃后操作系统自动释放租约。

## 启动示例

```powershell
Set-Location build\bin\processes\pdr-launcher
.\pdr-launcher.exe ..\..\pdr-runtime.exe
```

部署为 Windows 服务或 systemd 服务时，服务入口应指向 launcher，目标参数指向 `pdr-runtime`。确认两者工作目录和配置路径均为绝对路径或从 launcher 目录正确解析。
