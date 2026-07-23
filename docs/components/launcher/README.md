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
