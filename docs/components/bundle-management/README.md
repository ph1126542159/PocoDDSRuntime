# BundleManagement 组件

## 职责

`platform/BundleManagement` 监视当前进程的 Bundle 仓库，使新增、删除和原子替换的 `.bndl` 在运行时生效。

## 实现过程

`BundleManager` 周期性采集路径、修改时间和大小。变化连续两次扫描一致后，执行完整 OSP 生命周期：停止、卸载、重新扫描仓库、解析依赖、重新启动。稳定扫描用于避免加载复制到一半的文件。

## 用法

在运行配置中启用监视并设置扫描周期，然后把 Bundle 原子替换到 `bundles/`。推荐先写入临时文件，再重命名到最终名称。验证日志中 reload 成功且目标 Bundle 回到 active 状态。

本组件只管理所属进程的 Bundle 目录，不跨进程管理 `processes/*/bundles/`。
