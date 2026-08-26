# ProcessManagement 组件

## 职责

`platform/ProcessManagement` 根据属性文件启动、监督并停止外部子进程。

## 实现过程

`SubprocessManager` 先完整解析 `subprocess.count` 和各编号项，再验证显式依赖 DAG。启动顺序采用稳定拓扑序，依赖通过 Ready 门禁后才启动下游；关闭采用反向拓扑序。未知依赖、自依赖、重复边和循环图会在任何子进程启动前失败。独立监督线程负责检测异常退出，并按每个进程自己的有限预算和退避策略恢复。相对路径以运行时工作目录为基准。

## 用法

```properties
subprocess.count = 1
subprocess.supervisionIntervalMilliseconds = 100
subprocess.desiredStatePersistence.enabled = true
subprocess.desiredStatePersistence.path = data/process-desired-state.json
subprocess.desiredStatePersistence.scrubIntervalMilliseconds = 60000
subprocess.0.enabled = true
subprocess.0.name = worker
subprocess.0.dependency.count = 0
subprocess.0.path = processes/worker/worker.exe
subprocess.0.workingDirectory = processes/worker
subprocess.0.restartPolicy = on-failure
subprocess.0.restartMaximumAttempts = 5
subprocess.0.restartInitialBackoffMilliseconds = 250
subprocess.0.restartMaximumBackoffMilliseconds = 30000
subprocess.0.restartBackoffMultiplier = 2.0
subprocess.0.restartResetAfterMilliseconds = 60000
subprocess.0.readinessFile = processes/worker/worker.heartbeat
subprocess.0.readinessTimeoutMilliseconds = 10000
subprocess.0.heartbeatTimeoutMilliseconds = 5000
subprocess.0.argument.count = 1
subprocess.0.argument.0 = --health-file=worker.heartbeat
```

配置保存到 `pdr-subprocesses.properties` 后重启 `pdr-runtime`。不要把 `pdr-launcher` 配置成由 `pdr-runtime` 启动且反过来启动 `pdr-runtime`，这会形成父子循环。

隔离插件的槽位由 `pdr plugin apply-isolated/list-isolated/remove-isolated` 管理。工具使用
`subprocess.N.pdrManaged` 和 `subprocess.N.pdrInstanceManifest` 识别受管条目，在独占锁内原子重写并
保持编号连续；ProcessManagement 会忽略这两个管理元数据。不要手工修改受管条目。

## 配置项

| 配置项 | 必填 | 默认值/作用 |
| --- | --- | --- |
| `subprocess.count` | 是 | 子进程槽位数量，`0` 表示不启动 |
| `subprocess.supervisionIntervalMilliseconds` | 否 | `100`；退出检测周期，范围 10..60000 ms |
| `subprocess.desiredStatePersistence.enabled` | 否 | `false`；启用后，人工启停授权与终止恢复决策跨 Runtime 重启保持 |
| `subprocess.desiredStatePersistence.path` | 条件必填 | `data/process-desired-state.json`；Runtime 根目录内的相对路径 |
| `subprocess.desiredStatePersistence.scrubIntervalMilliseconds` | 否 | `60000`；在线校验主/上一代快照的周期，范围 10..86400000 ms |
| `subprocess.N.enabled` | 否 | `true`；可临时禁用槽位 |
| `subprocess.N.name` | 否 | 默认取可执行文件基本名，仅用于日志 |
| `subprocess.N.dependency.count` | 否 | `0`；该进程依赖的本地受管进程数量 |
| `subprocess.N.dependency.M` | 按数量 | 依赖进程的唯一名称；可以引用配置中较后的槽位 |
| `subprocess.N.path` | 是 | 可执行文件路径；相对运行时根目录 |
| `subprocess.N.workingDirectory` | 否 | 工作目录；相对运行时根目录 |
| `subprocess.N.argument.count` | 否 | 参数数量，默认 `0` |
| `subprocess.N.argument.M` | 按数量 | 第 M 个参数，原样传给目标程序 |
| `subprocess.N.restartPolicy` | 否 | `never`；可选 `never`、`on-failure`、`always` |
| `subprocess.N.restartMaximumAttempts` | 否 | 启用恢复时默认 `5`；单次连续故障最多重启次数，耗尽后 fail-closed |
| `subprocess.N.restartInitialBackoffMilliseconds` | 否 | `250`；第一次恢复前等待时间，范围 10..3600000 ms |
| `subprocess.N.restartMaximumBackoffMilliseconds` | 否 | `30000`；退避上限，不得小于初始值 |
| `subprocess.N.restartBackoffMultiplier` | 否 | `2.0`；每次失败后的退避倍率，范围 1..100 |
| `subprocess.N.restartResetAfterMilliseconds` | 否 | `60000`；连续稳定运行达到该时间后重置连续重启预算 |
| `subprocess.N.readinessFile` | 否 | 启动健康信号文件；必须是 Runtime 根目录内的相对路径，空表示仅检查 OS 进程存活 |
| `subprocess.N.readinessTimeoutMilliseconds` | 条件必填 | 配置 readiness 文件时默认 `10000`；新启动必须在该时间内改写为非空内容 |
| `subprocess.N.heartbeatTimeoutMilliseconds` | 否 | `0` 表示只做启动 Readiness；正值要求文件持续变化，且至少是监督扫描周期的两倍 |

主进程另外读取：

```properties
pdr.subprocess.configuration = ${application.dir}pdr-subprocesses.properties
pdr.subprocess.shutdownTimeoutMilliseconds = 5000
```

## 实现细节

`SubprocessManager::startFromConfiguration(configurationPath, processRootDirectory)` 顺序解析 `[0, count)` 并跳过 `enabled=false` 项，但不在解析阶段启动。完整配置通过引用和无环校验后，管理器生成稳定拓扑序，使用 `Poco::Process::launch()` 启动所有依赖已经 Ready 的根或下游进程。它保存 PID、名称和进程句柄，并返回本轮立即启动的数量；仍在等待依赖的进程随后由监督线程启动。初始启动失败会停止已经启动的进程并抛出异常，避免系统进入半启动状态。

`stopAll()` 按反向拓扑序停止，保证下游先于基础依赖退出。超时后会进入强制终止路径，因此子进程应响应正常终止信号并及时刷新文件。

期望状态持久化默认关闭，保持旧部署的启动语义。启用后，人工 `start(name)`、`stop(name)`、
`restart(name)` 先提交版本化期望状态，再执行进程动作；提交失败时撤销内存变更且不执行启停。
Runtime 正常关闭调用的 `stopAll()` 只停止 OS 进程，不覆盖持久化授权，因此人工停止和人工启动都能
跨 Runtime 重启保持。恢复预算耗尽、不可恢复启动失败和终止退出也持久化为非运行授权，重启不能
绕过 crash-loop 限制。

存储格式由 `contracts/schemas/process-desired-state.schema.json` 固定，内容使用按进程名排序的
SHA-256 完整性摘要。写入先生成、强制刷盘并回读校验 `.new`，再以同文件系统原子替换切换
`.previous` 和当前文件。Windows 使用 `FlushFileBuffers` 与 `MOVEFILE_WRITE_THROUGH`；POSIX 使用
`fsync(file)`、原子 `rename` 和 `fsync(parent directory)`，使数据与目录项提交顺序都有明确边界。主文件损坏
或在切换窗口缺失时，从有效的 `.previous` 恢复并重写规范快照；`.new` 只表示尚未提交的写入，
永远不能恢复为运维授权。主文件与 `.previous` 都无效时 Runtime 在启动任何受管进程前
fail-closed。未知旧进程名会在配置加载时清理，新配置
中的本地进程默认继承“运行”并写入新代次。不要让外部工具直接编辑这三个文件。

完整 DAG 校验后、读取任何快照前，管理器还会在同路径的 `.lock` 上取得进程生命周期级 OS
独占租约。Windows 使用不共享写入的文件句柄，Linux/POSIX 使用非阻塞 `flock`；第二个 Runtime
不能共用同一状态路径，并会在启动任何受管进程前失败。锁文件只按
`contracts/schemas/process-desired-state-lease.schema.json` 记录 Owner PID 和获取时间，真正的排他性
来自仍存活的 OS 句柄而不是文件是否存在，因此不得用删除 `.lock` 判断或解除锁。POSIX 租约描述符
强制设置 close-on-exec，受管子进程不会在 Runtime 退出后意外继承并长期占用写锁。

监督线程还按 `scrubIntervalMilliseconds` 在线校验主快照是否与内存中的当前代次和授权完全一致，
并在 `.previous` 存在时单独验证其 Schema、摘要及代次必须更旧。损坏不会触发旧状态自动覆盖，
也不会直接终止仍健康的业务进程；ProcessGraph 立即进入 `primary-invalid` 或
`previous-invalid`，`/health/detail` 发布
`PDR-HEALTH-PROCESS-DESIRED-STATE-INTEGRITY`，readiness 返回 503。下一次经授权的生命周期提交
会按当前内存授权生成新代次，成功回读后恢复健康。

框架还通过新增的独立公共头
`PocoDDS/ProcessManagement/ProcessDesiredStateMaintenance.h` 提供
`recommitActiveProcessDesiredState(expectedGeneration)`。它在管理器锁内重新巡检，只有调用方读取的
代次仍等于当前代次且存储确实降级时，才把当前内存授权提交为一个新代次；整个过程不调用
`start`、`stop` 或 `restart`。过期代次返回 `generation-conflict`，健康状态返回
`already-healthy`，均不写盘；未初始化和未启用分别返回 `manager-unavailable`、
`persistence-disabled`。I/O 提交失败仍抛出异常并保持 degraded。

该原语不自行提供 HTTP 路由、身份认证或审计。产品控制面必须先执行自己的权限、幂等和审计策略，
并把 ProcessGraph 刚读取的代次作为 CAS 参数；不得把它直接暴露为匿名写接口。

```cpp
#include <PocoDDS/ProcessManagement/ProcessDesiredStateMaintenance.h>

const auto result =
    PocoDDS::ProcessManagement::recommitActiveProcessDesiredState(
        observedGeneration);
if (!result.accepted || !result.healthy)
    // Map result.code or the thrown I/O exception into the governed control plane.
```

`on-failure` 仅在退出码非零时恢复，`always` 对正常退出也恢复，`never` 保持原有行为。人工 `stop()` 或 Runtime 正常关闭会先清除 `desiredRunning`，监督线程不得重新拉起目标。重启预算只限制一段连续故障；进程稳定运行达到 `restartResetAfterMilliseconds` 后重新获得完整预算。预算耗尽时状态固定为 `failed`，不会形成无限 crash loop，必须由操作员修复原因后调用 `start()`/`restart()` 重新授权。

`processes()` 继续使用既有清单 ABI，并以 `waiting-dependency`、`dependency-failed`、`starting`、`running`、`restart-pending`、`exited`、`failed`、`stopped` 表示状态。每次退出、依赖丢失、退避计划和预算耗尽都写入 Runtime 日志；依赖合同不增加 `PDRProcessManagement.dll` 的公共 ABI 面。

依赖只有处于 `running` 才满足门禁；配置 Readiness 的依赖必须先通过新鲜文件确认。依赖处于启动或恢复过程时，下游为 `waiting-dependency`；依赖已经人工停止、正常退出或耗尽恢复预算时，下游为 `dependency-failed`。运行中的下游在依赖丢失时会先被优雅停止，但保留自己的期望运行状态；操作员修复并重新启动依赖后，下游自动按拓扑序恢复，不消耗自身崩溃预算。人工停止某个依赖时，其传递下游先按反向拓扑序停止。

调用 `start(name)` 启动下游时，管理器会重新授权并启动该进程的传递依赖闭包；调用 `stop(name)` 停止基础依赖时不会清除下游的期望运行状态，下游保持 `dependency-failed`，便于修复后自动恢复。该规则避免不同团队通过管理 API 绕过配置声明的生命周期边界。

## 依赖图可观测接口

`GET /api/v1/process-dependencies` 由独立的
`pdr.platform.processGraph` Bundle 提供，ProcessManagement 只发布不可变 DTO，
不依赖 OSP、HTTP 或 WebUI。响应固定为 schema v1，包含：

- `nodes`：进程状态、期望状态、直接依赖、直接下游和结构化 `blockedBy`；
- `edges`：从基础依赖到下游的 `satisfied`、`waiting` 或 `failed` 状态；
- `startupOrder` 与 `shutdownOrder`：当前配置代次的权威拓扑顺序；
- `generation` 和 `summary`：配置代次及运行、等待、阻塞数量。
- `desiredStatePersistence`：是否启用、健康状态、单写者租约、是否从上一快照恢复、独立状态代次、
  主/上一代校验结果、稳定完整性状态和最近巡检时间。

该接口是 Runtime Process 范围的只读观察合同，不接受生命周期操作，也不返回可执行文件路径、参数或健康文件路径。状态来自管理器锁内的同一快照，调用方不得再次解析 `pdr-subprocesses.properties` 推测运行状态。

`GET /api/v1/process-dependencies/impact?target=...&action=start|stop|restart`
基于同一代不可变快照生成无副作用的操作计划。启动计划列出传递依赖闭包，停止计划列出传递下游和反向拓扑停止顺序，重启计划同时给出停止与恢复/就绪顺序。未知、远程或不可管理目标返回明确的拒绝决策；重复或非法查询参数返回 HTTP 400。该接口只负责预检，不宣称冻结快照；真正执行仍由 `SubprocessManager` 在锁内依据提交时的实际 DAG 完成。

配置 `readinessFile` 后，`Poco::Process::launch()` 成功只进入 `starting`，不能计为业务可用。监督器在每次 launch 前记录旧文件指纹；只有子进程启动后重新写入非空内容，状态才变成 `running`，因此旧 PID 遗留文件不能伪造 Ready。启动超时或心跳停止会终止进程，并消耗同一有限恢复预算。对 `required=true` 的进程，既有 HealthEndpoint 会自然把 `starting`、`restart-pending`、`failed` 判为 readiness 未满足。

重启预算的稳定期从首次 Ready 开始计算，而不是从获得 PID 开始。未通过 Readiness 的进程即使长时间存活，也不能重置 crash-loop 预算。心跳文件建议写入单调序号或时间戳；监督器比较大小、修改时间和有界内容样本，不依赖文件名存在本身。

```cpp
PocoDDS::ProcessManagement::SubprocessManagerOptions options;
options.shutdownTimeoutMilliseconds = 5000;
PocoDDS::ProcessManagement::SubprocessManager manager(logger, options);
auto count = manager.startFromConfiguration(
    "pdr-subprocesses.properties", "E:/deploy/bin");
manager.stopAll();
```

组件级故障测试 `subprocess-manager-desired-state-smoke` 覆盖损坏、回退和事务写失败；独立的
`process-desired-state-store-durability-smoke` 会在 `.new` 刷盘、上一代提交和新主版本提交三个
检查点立即终止真实写进程，验证每个崩溃窗口只恢复完整代次且后续重试收敛；
`runtime-process-desired-state-integration` 另外启动两个连续的隔离 `pdr-runtime` 实例，通过真实
`/api/v1/process-lifecycle` 停止本地测试子进程，并从 `/api/v1/process-dependencies` 确认第二个
Runtime 未重新启动它。两者都不复用正在运行的开发 Runtime。

## 两个子进程示例

```properties
subprocess.count = 2
subprocess.0.name = analytics
subprocess.0.dependency.count = 1
subprocess.0.dependency.0 = acquisition
subprocess.0.path = processes/analytics/analytics.exe
subprocess.0.workingDirectory = processes/analytics
subprocess.0.argument.count = 0

subprocess.1.name = acquisition
subprocess.1.dependency.count = 0
subprocess.1.path = processes/acquisition/acquisition.exe
subprocess.1.workingDirectory = processes/acquisition
subprocess.1.argument.count = 1
subprocess.1.argument.0 = /config-file=acquisition.properties
```

虽然 analytics 声明在槽位 0，但显式依赖保证 acquisition 先 Ready、analytics 后启动；关闭时 analytics 先退出。槽位编号只用于配置寻址，不再承担生命周期语义。
