# pdr-plugin-host 组件

`pdr-plugin-host` 为高风险或第三方 OSP 插件提供独立进程边界。宿主只加载一个
`pdr.plugin.*` 目标、`osp.core` 和配置中显式允许的依赖；仓库中其他 Bundle 即使存在也会被过滤。
插件原生崩溃、内存破坏或卡死因此不会直接破坏主 Runtime。

## 配置

| 配置项 | 要求 | 说明 |
| --- | --- | --- |
| `pluginHost.pluginId` | 必填 | 精确的 `pdr.plugin.*` symbolic name，不支持通配符 |
| `pluginHost.allowedBundles` | 可选 | 逗号分隔的显式依赖；`osp.core` 自动加入 |
| `pluginHost.heartbeatFile` | 必填 | launcher 监督的心跳文件 |
| `pluginHost.stateFile` | 必填 | 跨进程状态快照；标准文件名为 `pdr-process-status.json` |
| `pluginHost.heartbeatIntervalMilliseconds` | `1000` | 心跳/状态刷新周期，最小 10 ms |

配置可通过 `/config-file=...`、`--config-file=...` 或 `PDR_PLUGIN_HOST_CONFIG` 传入。生产多实例
优先使用各 launcher 的 `childArgument.N`，避免共享环境变量。

## 推荐部署

每个插件使用独立目录、Bundle 仓库、codeCache、data、宿主配置和 launcher 配置：

```powershell
./pdr.ps1 plugin scaffold-isolated build/plugin-dist/pdr.plugin.acme_1.0.0.bndl `
  --runtime-root C:/PocoDDSRuntime/bin --instance-name acme-isolated `
  --dependency-bundle C:/PocoDDSRuntime/bin/bundles/osp.core_1.7.0.bndl `
  --approval-report build/reports/plugin-preflight.json `
  --memory-bytes 268435456 --active-process-limit 1 --cpu-rate-percent 25
```

命令拒绝覆盖已有实例，要求提供插件 Manifest 中的全部直接依赖，并将成功的发布者 preflight/install
报告与插件 SHA-256 绑定。未验证发布者默认拒绝；诊断旁路只能显式授权且会写入报告。输出包含最小 Bundle 仓库、
宿主/launcher 配置、部署文件摘要、可由生命周期命令登记的编号占位片段和 JSON 报告。Linux
数值限制必须同时传入由 systemd 或部署层预先创建并授权的 `--linux-cgroup-path`。

Runtime 停止后，用受管生命周期命令登记、查询和解除登记：

```powershell
./pdr.ps1 plugin apply-isolated acme-isolated `
  --runtime-root C:/PocoDDSRuntime/bin --confirm-runtime-stopped
./pdr.ps1 plugin list-isolated --runtime-root C:/PocoDDSRuntime/bin
./pdr.ps1 plugin remove-isolated acme-isolated `
  --runtime-root C:/PocoDDSRuntime/bin --confirm-runtime-stopped
```

`apply-isolated` 会重新校验脚手架报告绑定的配置和 Bundle 摘要，然后在独占锁内原子更新配置；
重复执行是幂等的，未受管同名子进程会导致拒绝。`remove-isolated` 默认只解除登记并保留文件，便于恢复；
显式增加 `--purge` 才会在解除登记成功后删除实例目录。三条命令都支持 `--configuration` 指定
Runtime 根目录内的其他配置文件和 `--report` 输出机器可读证据。配置变更不会热加载，下一次启动生效。
进程异常退出遗留的锁仅在记录的 PID 已不存在时自动回收；活跃或无法安全识别的锁会继续阻止修改。

```properties
pluginHost.pluginId = pdr.plugin.acme
pluginHost.allowedBundles = pdr.protocol.gateway
pluginHost.heartbeatFile = ${application.dir}plugin-host.heartbeat
pluginHost.stateFile = ${application.dir}pdr-process-status.json
osp.bundleRepository = ${application.dir}bundles
osp.codeCache = ${application.dir}codeCache
osp.data = ${application.dir}data
```

```properties
relaunchDelay = 1000
restartBudget.maxRestarts = 5
restartBudget.windowMilliseconds = 60000
watchdog.file = E:/runtime/processes/acme/plugin-host.heartbeat
watchdog.timeout = 5000
watchdog.interval = 500
watchdog.startupGraceMilliseconds = 10000
watchdog.requireFile = true
childArgument.count = 1
childArgument.0 = /config-file=E:/runtime/processes/acme/plugin-host.properties
osp.bundleMonitor.enabled = false
```

主 Runtime 的 `pdr-subprocesses.properties` 启动该 launcher。工作目录名称与
`subprocess.N.name` 保持一致，SystemMonitoring 即可读取 `pdr-process-status.json`，现有 Web
进程详情会展示宿主中的插件并标记 `isolation=process`。

状态文件遵循 `contracts/schemas/plugin-host-state.schema.json`。launcher 负责心跳超时、崩溃重启
和滑动时间窗预算。业务通信使用 DDS 或已声明协议，不能依赖主 Runtime 的进程内 ServiceRegistry。
这是进程隔离而非容器安全沙箱；账户、文件、网络和操作系统资源限制仍由部署层负责。
