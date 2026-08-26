# 产品项目工作区

PocoDDSRuntime 框架与具体机器人产品分别版本化。产品仓库通过安装后的
`PDRRoboticsRuntime` Package 使用框架，不修改 `robotics/src`、`server` 或平台基础库。

## 创建项目

```powershell
./tools/pdr.ps1 project create WarehouseRobot `
  --output E:/Products --profile robotics --runtime-version 0.1.x
Set-Location E:/Products/WarehouseRobot
$env:PDR_SDK_PREFIX = "E:/PocoDDSRuntime/build/install"
```

生成目录将业务模块、服务、硬件/仿真/ROS 2适配器、Bundle、独立进程、配置、测试和部署文件分开。
顶层 CMake 只加载清单生成的 `pdr-project.components.cmake`，不扫描目录。生成命令位于项目
目录内时会自动登记组件；未登记的试验目录不会进入产品构建。机器人业务动态库仍只能通过明确的
`business_plugins` 路径加载。生成的 CMake Target 带组件类别命名空间；即使 Module 和
Service 使用相同业务名称，也不会发生 Target 或构建输出目录冲突。

默认构建只组合机器人核心组件。需要 OSP 管理面时显式启用：

```powershell
cmake -S . -B build-management `
  -DPDR_PROJECT_BUILD_MANAGEMENT=ON
```

该开关才会加载 `PocoDDSRuntime` 的 `SDK`、`Plugins` 组件并加入 `services/`、`bundles/`，
避免控制核心无意绑定管理面依赖。

## 项目清单

`pdr-project.yaml` 是产品组合的唯一权威入口。生成文件使用 JSON 兼容的 YAML 1.2语法，因此
基础 CLI 不依赖第三方 YAML 库；安装 PyYAML 后也可以使用常规 YAML 写法。

顶层 `version` 是产品自身的具体 SemVer；`runtime.version` 是可消费的框架版本或 patch 范围，
两者不能混用。交付前用 `project version pdr-project.yaml <version>` 更新产品版本并重新生成锁。

清单固定描述：

- Runtime Profile 与兼容版本；
- 机器人型号、Backend 与控制周期；
- Module、Service、Adapter、Bundle、Process 和 Web Bundle 路径；
- base、robot、site 配置层，以及组件配置所有权和热更新能力清单；
- Unit、SIL、HIL 和长稳要求。

组件日常操作：

```powershell
./tools/pdr.ps1 project list pdr-project.yaml
./tools/pdr.ps1 project add pdr-project.yaml service services/Diagnostics
./tools/pdr.ps1 project remove pdr-project.yaml service services/Diagnostics
./tools/pdr.ps1 project sync pdr-project.yaml
```

`remove` 只解除登记，不删除源码。直接编辑清单后必须执行 `sync`；组合文件记录 Manifest
SHA-256，清单与组合文件不一致时 CMake 会拒绝配置，防止构建到错误的组件集合。

每个当前模板组件还带有产品所有的 `pdr-component.json`。多人协作时，每个组件 Owner 只在
自己的目录内维护源码、公共 Target 和 `requires`；`project sync` 会按依赖拓扑生成组合顺序。
如果 CMake 实际链接另一个项目组件却没有在 `requires` 声明，配置阶段直接失败。Subprocess
不能通过链接进程内 Service 绕过进程边界，应通过 DDS、HTTP 或其他版本化公开协议协作。

```powershell
pdr component dependency add services/InventoryService shared-model
pdr component dependency list services/InventoryService
pdr project sync pdr-project.yaml
```

Pull Request 或 CI 可以把改动文件映射到直接受影响组件、所有下游依赖组件、Owner 和
可独立构建 Target：

```powershell
pdr project impact pdr-project.yaml `
  modules/SharedModel/include/Model.h services/InventoryService/src/Service.cpp `
  --output build/change-impact.json
```

输出 JSON 可直接作为 CI matrix 输入。组件目录外的公共构建、配置或契约改动按
framework-wide 处理，会选择全部组件，避免共享修改漏测其他团队的代码。

路径必须在项目根目录内、不能重复，且清单中引用的目录必须真实存在。CMake 组件必须含
`CMakeLists.txt`，ROS 2适配器必须同时含 `CMakeLists.txt` 与 `package.xml`，Web Bundle
必须含 `CMakeLists.txt` 或 `package.json`：

```powershell
./tools/pdr.ps1 project validate pdr-project.yaml `
  --report build/reports/project-validation.json
```

## 可复现解析

发布或 CI 前生成绑定清单和源码树摘要的锁文件：

```powershell
./tools/pdr.ps1 project resolve pdr-project.yaml `
  --output pdr-project.lock.json
```

锁文件记录规范化后的组合、Manifest SHA-256、源码树 SHA-256 和文件数量。锁文件本身不参与
源码摘要，因此同一源码重复解析结果稳定；时间字段只表示本次解析时间。

配置层解析、环境变量秘密引用、声明式迁移和可恢复配置事务见
[产品配置治理](project-configuration.md)。
框架升级后的脚手架状态检查、旧项目采用和冲突安全升级见
[项目模板升级](project-templates.md)。
每个生成组件的结构版本、业务源码所有权和独立升级流程见
[组件模板升级](component-templates.md)。

## 机器人专用扩展

```powershell
./tools/pdr.ps1 new robot-module ChargingModule --output modules
./tools/pdr.ps1 new robot-hardware-adapter CanDrive --output adapters/hardware
./tools/pdr.ps1 new robot-simulation-adapter WarehouseWorld --output adapters/simulation
./tools/pdr.ps1 new robot-process VisionWorker --output processes
./tools/pdr.ps1 new ros2-node MissionGateway --output adapters/ros2
```

前四类可以使用 `pdr verify` 对安装后的机器人 SDK 做隔离构建与 CTest。ROS 2节点使用
`colcon build/test`，不能用普通 CMake 测试替代 ROS 2工作区验收。

## 推荐流水线

1. `project validate`；
2. `project resolve` 并保存锁文件；
3. CMake 构建产品内机器人组件；
4. `colcon build/test` 构建 ROS 2适配器；
5. Unit 和确定性 SIL；
6. Gazebo SIL；
7. HIL、真实机器人和长稳验收；
8. 按[产品项目打包与验包](project-delivery.md)生成带版本、摘要、SBOM 和签名的交付包。

Build、SIL、HIL 和真实机器人验收必须分别报告，不能互相替代。

上述自动步骤可由[产品项目统一资格流水线](project-pipelines.md)生成并断点续跑。流水线会按
Manifest 自动加入 ROS 2阶段，并把 SIL、HIL 和长稳保留为明确的外部证据门禁。
