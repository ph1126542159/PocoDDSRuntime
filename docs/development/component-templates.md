# 组件模板版本与业务源码边界

`pdr new` 生成的 12 类组件都在根目录写入 `.pdr-component.json`。该状态记录组件类型、
名称、模板版本、结构受管文件基线和业务所有文件的初始模板摘要。当前组件模板版本为 2，
历史 v1 的渲染指纹冻结在 `contracts/component-templates/v1.json`，CI 会阻止旧模板被静默改写。

适用类型包括 `module`、`service`、`device`、`workflow`、`bundle`、`plugin`、
`subprocess`、`robot-module`、两类机器人 Adapter、`robot-process` 和 `ros2-node`。

## 所有权边界

框架只治理组件结构契约：

- 所有 `CMakeLists.txt`；
- `README.md`；
- ROS 2 `package.xml`；
- OSP `*.bndlspec`。

`src/`、`include/`、`tests/`、`launch/` 和 `config/` 中的业务实现归产品所有。模板升级会记录
这些文件当前是初始模板还是产品已修改状态，但永不写入、删除或恢复它们。新增结构文件若将来
需要由框架治理，必须先提升组件模板版本，不能直接改变历史 v1 渲染结果。

## 生成与日常门禁

```powershell
pdr new service DiagnosticsService --output services
pdr component status services/DiagnosticsService --check `
  --report build/reports/diagnostics-template-status.json
pdr verify services/DiagnosticsService --prefix E:/PocoDDSRuntime/build/install
```

`status --check` 在模板过期、结构文件被修改/删除、状态漏记受管文件时返回 2。`verify` 在调用
CMake 前执行相同的 fail-closed 检查。已登记项目的 `project validate`、`project resolve` 和
`project package create` 也会检查所有带组件元数据的路径；手写或尚未采用模板的旧组件仍可存在，
但不会伪装成已治理组件。

## 旧组件采用与升级

采用时必须明确组件最接近的历史模板版本：

```powershell
pdr component adopt services/LegacyDiagnostics `
  --kind service --name LegacyDiagnostics --version 1
pdr component upgrade services/LegacyDiagnostics `
  --report build/reports/legacy-diagnostics-upgrade.json
```

只有与历史模板逐字节一致的结构文件会进入受管集合。缺失或预先定制的结构文件会登记到
`unmanagedFiles`，升级不会默认覆盖。未修改的受管文件自动升级；有冲突时整次操作在写入前拒绝：

```powershell
# 保留产品 CMake，后续不再由模板管理
pdr component upgrade services/LegacyDiagnostics `
  --keep-project CMakeLists.txt

# 明确放弃 README 定制，使用框架模板并保留旧文件备份
pdr component upgrade services/LegacyDiagnostics `
  --accept-template README.md
```

两个选项可重复，但只能选择当前冲突报告中的路径，同一路径不能同时选择。升级计划完成后、
实际写入前会重新核对状态和所有输入摘要，防止并发修改被覆盖。

## 中断恢复

采用和升级使用 `.pdr/template-backups/<transaction-id>/journal.json` 记录写前备份、已尝试
路径和事务状态。进程或主机中断后保持工作区不再修改并执行：

```powershell
pdr component recover services/LegacyDiagnostics `
  --journal .pdr/template-backups/<transaction-id>/journal.json
```

恢复只接受组件模板采用/升级事务，只回滚日志证明已尝试写入的路径，并校验根目录边界与备份摘要。
若外部原因造成 `rollback-failed`，修复外部原因后显式加 `--retry-rollback`。

## 版本演进规则

1. v1 renderer 只能修复生成器无法运行的缺陷，任何输出变化都必须先新增模板版本。
2. 新模板先增加新版本渲染、迁移测试和冻结契约，再提升 `CURRENT_TEMPLATE_VERSION`。
3. 自动迁移只修改受管结构文件；业务源码变化必须作为独立、可审查的产品改动。
4. 模板升级通过不等于构建、SIL、HIL 或真实设备验收；这些证据仍需分别产生。
