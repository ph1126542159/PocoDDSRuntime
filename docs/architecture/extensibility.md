# 可扩展框架边界

PocoDDSRuntime 的稳定性来自固定依赖方向，而不是把所有能力放进主进程。框架代码与项目代码按以下边界组织：

```text
项目入口 / Web / DDS / Bundle
            │
            ▼
       Application 用例
            │
            ▼
     Service / Module 接口
            │
            ▼
 Platform / Protocol / Device Adapter

独立子进程 ── 只通过 DDS、HTTP 或公开协议通信
```

## 四种扩展单元

| 单元 | 适用场景 | 允许依赖 | 禁止事项 |
| --- | --- | --- | --- |
| Module | 算法、策略、领域模型、可复用库 | 优先 `PocoDDS::RuntimeCore` 或更小的公开组件 | 直接依赖 Runtime 主程序 |
| Service | 稳定业务接口和用例实现 | RuntimeCore、Module、Application、公开 Port | 在接口层绑定 Qt、Fast DDS、ROS 2 或设备实现 |
| Bundle | 运行时发现、OSP 生命周期和服务注册 | Service 与 `PocoDDS::Plugins` | 在 Activator 中实现业务流程 |
| Subprocess | 原生崩溃隔离、独立资源/生命周期 | SDK、DDS、HTTP、公开协议 | 访问主进程内 Service Registry |

Bundle 是部署适配器，Service 是业务能力；两者不能合并成一个巨型 Activator。只有确实需要故障隔离、资源边界或不同技术栈时才使用 Subprocess。

## 目录所有权

```text
PocoDDSRuntime/
├─ application/       # 与传输无关的用例和工作流
├─ platform/          # 通用基础能力、协议、设备适配器
├─ services/          # 框架内置服务及其 OSP Bundle
├─ SubSystem/         # 独立进程实现
├─ webui/             # 每个页面一个 Bundle
├─ server/            # 薄主入口，只负责组合和启动
└─ tools/             # 脚手架、验证、发布和运维工具
```

特定客户或产品的代码优先放在独立产品仓库，通过安装后的 `PocoDDSRuntime` CMake Package 消费 SDK。这样框架升级与项目交付可以分别版本化。确实需要同仓开发时，项目目录也必须保持 `modules/`、`services/`、`bundles/`、`subprocesses/` 分开，并由项目自己的顶层 CMake 组合；不要把项目分支写进 `server/MacchinaServer.cpp`。

产品若实现独立进程治理控制面，可消费 `PocoDDS::ProcessGraph` 中的
`ProcessDesiredStateMaintenance.h`，用 ProcessGraph 观测到的代次执行 CAS 重新提交。该接口只提供
核心原语，不替产品实现认证、授权、审计和幂等；匿名 HTTP Bundle 不得直接转发该写操作。

## 快速新增

```powershell
./tools/pdr.ps1 project create WarehouseRobot --output E:/Products --profile robotics
./tools/pdr.ps1 new module TemperatureModel --output product/modules
./tools/pdr.ps1 new service TemperatureService --output product/services
./tools/pdr.ps1 new bundle TemperatureApi --output product/bundles
./tools/pdr.ps1 new subprocess VisionWorker --output product/subprocesses
./tools/pdr.ps1 new robot-module ChargingModule --output product/modules
./tools/pdr.ps1 new robot-hardware-adapter CanDrive --output product/adapters/hardware
```

项目创建、清单校验和源码摘要锁定的完整流程见[产品项目工作区](../development/project-workspaces.md)；新项目先按[框架模型选择与项目适配](framework-model-selection.md)选择 Profile、Host 和 Transport。

`bundle` 是受治理的外部 OSP Plugin Bundle 别名，仍使用 `pdr.plugin.*` 命名并经过 API/ABI、签名、隔离和回退门禁。生成器默认拒绝覆盖非空目录。

产品项目中的每个生成组件使用 `pdr-component.json` 声明 ID、Owner、公共 Target、隔离方式和
显式 `requires`。项目组合器按依赖拓扑加载组件，并在 CMake 配置期核对实际项目 Target 链接；
禁止依赖环、未声明链接以及 Module/Service/Bundle/Subprocess 反向依赖。

设备和协议实现通过 `PocoDDS::GatewayAPI` 中的 `DeviceFactoryService` 或
`ProtocolFactoryService` 注册到 OSP Service Registry。提供者 Bundle 必须早于对应 Gateway
启动，并在已创建实例的完整生命周期内保持激活。Gateway 只拥有枚举、公共配置、实例 ID、
健康、重连和关闭顺序；业务 Bundle 只拥有具体对象创建及该类型专属配置，禁止包含或链接
Gateway 的 `BundleActivator.cpp`。

框架内的 `services/`、`SubSystem/` 和 `webui/` 会自动发现包含 `CMakeLists.txt` 的直接子目录。新增组件无需再修改中央目录清单；组件自己的 CMake 负责源文件、测试、打包、安装和可选开关。

## 完成定义

新增扩展不能以“编译通过”作为唯一结论，至少分开验证：

1. `pdr verify`：独立配置、构建和 CTest 通过；
2. Bundle：生成真实 `.bndl`，通过预检并由 Runtime 成功加载、注册和停止；
3. Subprocess：主进程拉起、心跳、正常退出、崩溃重启与重启预算通过；
4. Service/Module：接口测试、错误路径、超时/取消和配置校验通过；
5. 安装包：从隔离安装目录启动，不能依赖源码树或构建目录中的偶然文件。

跨层依赖确有必要时先写 ADR，说明原因、替代方案、故障边界和退出计划。
