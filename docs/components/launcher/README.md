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
| `watchdog.file` | 空 | 心跳文件路径；空表示不启用心跳监视 |
| `watchdog.timeout` | `600000` | 心跳超时，毫秒 |
| `watchdog.interval` | `60000` | 心跳检查周期，毫秒 |
| `osp.bundleMonitor.enabled` | `true` | launcher 自身 OSP Bundle 监视开关 |
| `osp.bundleRepository` | `${application.dir}bundles/` | launcher 自己的 Bundle 仓库 |

## 启动示例

```powershell
Set-Location build\bin\processes\pdr-launcher
.\pdr-launcher.exe ..\..\pdr-runtime.exe
```

部署为 Windows 服务或 systemd 服务时，服务入口应指向 launcher，目标参数指向 `pdr-runtime`。确认两者工作目录和配置路径均为绝对路径或从 launcher 目录正确解析。
