# 组件模板版本与业务源码边界

`pdr new` 生成的 12 类组件都在根目录写入 `.pdr-component.json`。该状态记录组件类型、
名称、模板版本、结构受管文件基线和业务所有文件的初始模板摘要。当前组件模板版本为 8，
历史 v1 的渲染指纹冻结在 `contracts/component-templates/v1.json`，CI 会阻止旧模板被静默改写。

版本 4 开始生成产品所有的 `pdr-component.json` 协作契约。它声明稳定组件 ID、类型、
所属平面、公共 CMake Target、Owner、隔离方式和 `requires` 组件依赖。该文件属于产品业务，
框架升级不会覆盖；项目校验会拒绝重复 ID/Target、依赖环、未登记依赖和以下越层方向：

- Module 只能依赖 Module；
- Service 只能依赖 Module；
- Bundle/Plugin 可以依赖 Module 和 Service；
- Subprocess 只能链接共享 Module，不能链接进程内 Service 或 Bundle；跨进程调用必须走公开协议。

版本 5 为 `device` 额外生成独立工厂 Bundle。工厂在 run level 090 注册
`DeviceFactoryService`，DeviceGateway 在 run level 100 发现并创建实例；新增业务设备不再
要求修改框架 Gateway。设备类和工厂 Bundle 仍属于同一产品组件、同一 Owner，但具有独立
部署和启动边界。

版本 6 为 `workflow` 额外生成独立定义提供者 Bundle。提供者在 run level 110 注册
`WorkflowDefinitionService`，持久化 Workflow Runtime 动态发现它；新增或升级业务流程不再
要求修改框架 Core。兼容适配器默认把已有 Application Workflow 暴露为一个持久步骤，团队可在
产品所有的 `WorkflowBundleActivator.cpp` 中扩展多步骤、等待、重试和反向补偿。

版本 7 为 `bundle` 和 `plugin` 默认生成 Bundle 本地 `service-contracts.json`、Service Owner/
Readiness 注册属性，以及无需启动 Runtime 的组件契约 CTest。Consumer 可以直接固定 Provider
团队发布的真实契约，提前阻断版本范围或最小 Provider 数量不兼容；详细流程见
[组件 Service 契约独立测试](component-contract-testing.md)。

从 v1-v6 升级的既有 Bundle/Plugin 不会改写产品所有的 Activator，因此迁移只创建不声明
Provider/Requirement 的安全空契约。组件 Owner 应审查真实注册行为，补齐 `pdr.bundle` 与
`pdr.service.readiness` 属性后，再显式填写 Service 声明；模板升级不会代替这一业务决定。

版本 8 为新建 `bundle` 和 `plugin` 增加真实事务配置参与者、本地
`configuration-participants.json` 以及独立配置契约 CTest。默认只拥有自身
`pdr.plugin.<name>` 前缀，commit/rollback 只保存该前缀内的值。构建期会联合显式传入的其他团队
声明检查重复 ID、Service 名、前缀覆盖和依赖环。既有 v1-v7 组件升级仍不改写产品 Activator，
因此只生成 `participants: []` 的非声明占位；Owner 完成参与者实现和注册后才能显式认领前缀。
发布后的组件可在生成的 CTest 中显式传入 `BASELINE`，绑定已发布 Participant 的 ID、Service、
Bundle Owner、前缀范围和排序依赖；新增声明以及扩大前缀保持兼容，缩窄/转移前缀或删除排序保证会
在组件合并前失败。

版本 9 为 Bundle/Plugin 增加产品所有的 `bundle/configuration-key-lifecycle.json` 和独立生命周期
CTest。默认 `entries: []` 不声明任何弃用；团队只有在自己的 Participant 前缀内才能登记 rename/remove，
且最早移除版本必须位于首次弃用版本之后的主版本。项目迁移文件可作为 `MIGRATIONS` 输入，任何没有
匹配 Owner 生命周期的 rename/remove 都会失败。从旧模板升级只增加安全空文件，不修改业务源码。

使用 CLI 修改依赖可以避免手工 JSON 拼写错误；修改后在项目根目录重新同步并校验完整依赖图：

```powershell
pdr component dependency add services/DiagnosticsService common-model
pdr project sync pdr-project.yaml
pdr project validate pdr-project.yaml
```

适用类型包括 `module`、`service`、`device`、`workflow`、`bundle`、`plugin`、
`subprocess`、`robot-module`、两类机器人 Adapter、`robot-process` 和 `ros2-node`。

## 所有权边界

框架只治理组件结构契约：

- 所有 `CMakeLists.txt`；
- `README.md`；
- ROS 2 `package.xml`；
- OSP `*.bndlspec`。

`src/`、`include/`、`tests/`、`launch/`、`config/` 和 `pdr-component.json` 中的业务实现及
协作声明归产品所有。模板升级会记录
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
