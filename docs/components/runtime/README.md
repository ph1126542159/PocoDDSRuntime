# pdr-runtime 主程序

## 职责

`server/src/MacchinaServer.cpp` 是单一 OSP 服务器入口。它初始化日志和 OSP 子系统，启动 Bundle 管理器，再按 `pdr-subprocesses.properties` 的编号顺序启动子进程。

## 实现过程

1. 由 `Poco::Util::ServerApplication` 完成命令行和配置加载。
2. 建立 OSP Bundle 仓库、加载器及服务注册表。
3. 启动 `BundleManager`，监视本进程 `bundles/`。
4. 启动 OSP Bundles。
5. 创建 `SubprocessManager`，按配置启动外部进程。
6. 退出时逆序停止子进程，再停止 OSP。

## 用法

```powershell
Set-Location build/bin
./pdr-runtime.exe
```

Windows 使用 `/option=value`，Unix 使用 `--option=value`。默认配置来自同目录的 `pdr-runtime.properties` 和 `pdr-subprocesses.properties`。

## 验证

检查控制台/`logs/` 中的 Bundle 启动信息，并执行：

```powershell
ctest --test-dir build -C Release --output-on-failure
```
