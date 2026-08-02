# ProcessManagement 组件

## 职责

`platform/ProcessManagement` 根据属性文件启动、监督并停止外部子进程。

## 实现过程

`SubprocessManager` 解析 `subprocess.count` 和各编号项，按编号升序启动；启动中途失败时回滚已经启动的进程；正常退出时逆序停止。相对路径以运行时工作目录为基准。

## 用法

```properties
subprocess.count = 1
subprocess.0.enabled = true
subprocess.0.name = worker
subprocess.0.path = processes/worker/worker.exe
subprocess.0.workingDirectory = processes/worker
subprocess.0.argument.count = 1
subprocess.0.argument.0 = --config=worker.properties
```

配置保存到 `pdr-subprocesses.properties` 后重启 `pdr-runtime`。不要把 `pdr-launcher` 配置成由 `pdr-runtime` 启动且反过来启动 `pdr-runtime`，这会形成父子循环。

隔离插件的槽位由 `pdr plugin apply-isolated/list-isolated/remove-isolated` 管理。工具使用
`subprocess.N.pdrManaged` 和 `subprocess.N.pdrInstanceManifest` 识别受管条目，在独占锁内原子重写并
保持编号连续；ProcessManagement 会忽略这两个管理元数据。不要手工修改受管条目。

## 配置项

| 配置项 | 必填 | 默认值/作用 |
| --- | --- | --- |
| `subprocess.count` | 是 | 子进程槽位数量，`0` 表示不启动 |
| `subprocess.N.enabled` | 否 | `true`；可临时禁用槽位 |
| `subprocess.N.name` | 否 | 默认取可执行文件基本名，仅用于日志 |
| `subprocess.N.path` | 是 | 可执行文件路径；相对运行时根目录 |
| `subprocess.N.workingDirectory` | 否 | 工作目录；相对运行时根目录 |
| `subprocess.N.argument.count` | 否 | 参数数量，默认 `0` |
| `subprocess.N.argument.M` | 按数量 | 第 M 个参数，原样传给目标程序 |

主进程另外读取：

```properties
pdr.subprocess.configuration = ${application.dir}pdr-subprocesses.properties
pdr.subprocess.shutdownTimeoutMilliseconds = 5000
```

## 实现细节

`SubprocessManager::startFromConfiguration(configurationPath, processRootDirectory)` 顺序遍历 `[0, count)`，跳过 `enabled=false` 项，使用 `Poco::Process::launch()` 启动。它保存 PID、名称和进程句柄，并返回启动数量。如果第 N 个进程启动失败，已启动的 `0..N-1` 会被停止并抛出异常，避免系统进入半启动状态。

`stopAll()` 逆序停止。超时后会进入强制终止路径，因此子进程应响应正常终止信号并及时刷新文件。

```cpp
PocoDDS::ProcessManagement::SubprocessManagerOptions options;
options.shutdownTimeoutMilliseconds = 5000;
PocoDDS::ProcessManagement::SubprocessManager manager(logger, options);
auto count = manager.startFromConfiguration(
    "pdr-subprocesses.properties", "E:/deploy/bin");
manager.stopAll();
```

## 两个子进程示例

```properties
subprocess.count = 2
subprocess.0.name = acquisition
subprocess.0.path = processes/acquisition/acquisition.exe
subprocess.0.workingDirectory = processes/acquisition
subprocess.0.argument.count = 1
subprocess.0.argument.0 = /config-file=acquisition.properties

subprocess.1.name = analytics
subprocess.1.path = processes/analytics/analytics.exe
subprocess.1.workingDirectory = processes/analytics
subprocess.1.argument.count = 0
```

这里保证 acquisition 先启动，analytics 后启动；关闭时顺序相反。
