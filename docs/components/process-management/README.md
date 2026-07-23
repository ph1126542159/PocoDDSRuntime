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
