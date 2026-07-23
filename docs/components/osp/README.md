# OSP 组件

## 职责

`platform/OSP` 提供 Bundle 安装、依赖解析、启动、停止、卸载和本地服务注册表。它负责同一进程内的模块化，不负责跨进程通信；跨进程由 Fast DDS 完成。

## 实现过程

核心库汇总 Bundle、BundleLoader、BundleRepository、ServiceRegistry 和 OSPSubsystem。`Core`、`Web`、`WebServer`、`BundleAdmin` 等子目录构建标准 OSP Bundle 或工具；`BundleCreator` 把 `.bndlspec` 和资源打包为 `.bndl`。

## 用法

业务 Bundle 提供 `BundleActivator`，在 `start()` 中注册服务并在 `stop()` 中注销服务。通过 `.bndlspec` 声明名称、版本、依赖和打包内容，构建后将 `.bndl` 放入运行进程的 `bundles/`。

不要绕过 OSP 直接加载动态库；否则依赖解析、停止和卸载阶段不会完整执行。
