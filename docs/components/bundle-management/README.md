# BundleManagement 组件

## 职责

`platform/BundleManagement` 监视当前进程的 Bundle 仓库，使新增、删除和原子替换的 `.bndl` 在运行时生效。

## 实现过程

`BundleManager` 周期性采集路径、修改时间和大小。变化连续两次扫描一致后，执行完整 OSP 生命周期：停止、卸载、重新扫描仓库、解析依赖、重新启动。稳定扫描用于避免加载复制到一半的文件。

## 用法

在运行配置中启用监视并设置扫描周期，然后把 Bundle 原子替换到 `bundles/`。推荐先写入临时文件，再重命名到最终名称。验证日志中 reload 成功且目标 Bundle 回到 active 状态。

本组件只管理所属进程的 Bundle 目录，不跨进程管理 `processes/*/bundles/`。

## API 与内部状态

公共入口为 `BundleManager`：

```cpp
PocoDDS::BundleManagement::BundleManagerOptions options;
options.repositories = configuration->getString("osp.bundleRepository");
options.intervalMilliseconds = 1000;
options.stableScanCount = 2;

PocoDDS::BundleManagement::BundleManager manager(
    ospSubsystem, logger, options);
manager.start();
manager.reloadNow(); // 可选：管理员显式要求立即重载
// 进程退出前
manager.stop();
```

后台线程把仓库目录中的路径、文件大小和最后修改时间组成快照。检测到变化后并不立即重载，而是等下一次扫描得到相同快照；这样部署端仍在写 `.bndl` 时不会加载半包。

稳定后执行：

```text
stopAllBundles
→ unloadAllBundles
→ BundleRepository::loadBundles
→ resolveAllBundles
→ startAllBundles
```

任一步骤异常都会记录失败并保留下一轮重试机会。

可用 `running()`、`successfulReloads()` 和 `failedReloads()` 读取状态指标。

## 配置

```properties
osp.bundleRepository = ${application.dir}bundles/
osp.bundleMonitor.enabled = true
osp.bundleMonitor.intervalMilliseconds = 1000
```

多个仓库的分隔格式必须与 Poco OSP 当前配置约定一致。仓库目录推荐以 `/` 结尾，避免被 Glob 当成精确文件模式。

## 安全部署示例

```powershell
Copy-Item .\pdr.service.demo_1.0.1.bndl .\build\bin\bundles\demo.bndl.new
Move-Item .\build\bin\bundles\demo.bndl.new `
  .\build\bin\bundles\pdr.service.demo_1.0.1.bndl
```

替换旧版本时先确认 Bundle symbolic name 和版本依赖。验收不仅要看到文件存在，还要在日志中确认重载完成、依赖解析成功且 Bundle 回到 active。
