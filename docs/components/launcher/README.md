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
2. 启动命令行参数指定的目标进程。
3. 若配置了 `watchdog.file`，按固定周期检查心跳文件更新时间。
4. 目标异常退出或心跳超时后等待 `relaunchDelay`，再重新启动。
5. launcher 收到退出信号时停止目标进程并退出。

## 配置项

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `relaunchDelay` | `1000` | 异常退出后重新启动等待时间，毫秒 |
| `restartBudget.maxRestarts` | `5` | 滑动时间窗内允许的重启次数；`0` 表示不重启 |
| `restartBudget.windowMilliseconds` | `60000` | 重启预算滑动时间窗，毫秒 |
| `childArgument.count` | `0` | 追加给被监督程序的参数数量 |
| `childArgument.N` | 无 | 第 N 个参数，按原值传递，不经 shell 解释 |
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
| `osp.bundleMonitor.enabled` | `true` | launcher 自身 OSP Bundle 监视开关 |
| `osp.bundleRepository` | `${application.dir}bundles/` | launcher 自己的 Bundle 仓库 |

预算耗尽后 launcher 不再制造崩溃重启风暴，而是记录 critical 日志并以非零状态退出，由上一级服务
管理器告警或按更长退避策略处置。心跳超时导致的强制终止也计入同一预算。

## 启动示例

```powershell
Set-Location build\bin\processes\pdr-launcher
.\pdr-launcher.exe ..\..\pdr-runtime.exe
```

部署为 Windows 服务或 systemd 服务时，服务入口应指向 launcher，目标参数指向 `pdr-runtime`。确认两者工作目录和配置路径均为绝对路径或从 launcher 目录正确解析。
