# 框架模型选择与项目适配

本文是新项目选型入口。先按生命周期和故障边界选择 Host，再按实际拓扑选择
Transport。ROS 2、Fast DDS、MQTT 都是可选适配器，不是业务模块的基础依赖。

## 一分钟选择

| 项目类型                       | Profile / Preset      | Host       | 默认传输策略                                     | 默认框架部分                        |
| -------------------------- | --------------------- | ---------- | ------------------------------------------ | ----------------------------- |
| 单机 Qt/Win32/CLI、配置器、离线算法   | `desktop-lite`        | `static`   | `inproc`                                   | `RuntimeCore`                 |
| 桌面多进程、局域网协作、HTTP/WebSocket | `desktop-distributed` | `desktop`  | `inproc` + 项目 IPC/HTTP/WebSocket Adapter   | `RuntimeCore`                 |
| 嵌入式 Linux、PetaLinux、设备守护进程 | `embedded`            | `service`  | `inproc` + Fast DDS/现场总线 Adapter           | 裁剪后的完整 Runtime                |
| 工业网关、边缘控制器、协议汇聚            | `edge-industrial`     | `osp`      | `inproc`、HTTP、MQTT、Fast DDS、现场总线           | OSP 管理面与可观测性                  |
| 测试台、桌面运维站、集成验证平台           | `edge-test`           | `osp`      | `inproc`、HTTP/WebSocket、MQTT、Fast DDS、现场总线 | 完整管理与测试能力                     |
| 中心服务、数据与追踪平台               | `server`              | `osp`      | `inproc`、HTTP/WebSocket、MQTT、Fast DDS      | 完整 Runtime 与数据模块              |
| 机器人控制、仿真、ROS 2 接入          | `robotics`            | `robotics` | Core `inproc`；ROS 2 外部 Adapter             | `RuntimeCore` + Robotics Core |

直接结论：普通桌面程序选 `desktop-lite`，不需要安装 ROS 2，也不依赖 Fast DDS、
Poco/OSP 或 WebUI。只有进程拓扑、跨机通信或生态接口确实需要时才增加相应 Adapter。

## 三个正交维度

框架不再用一个全局通信后端决定整个程序，而是拆成三个维度：

1. **Core**：稳定消息契约、订阅生命周期和进程内调度。业务代码只依赖
   `PocoDDS::RuntimeCore`。
2. **Host**：决定组件如何启动、停止、发现与隔离，可选 `static`、`desktop`、
   `service`、`osp`、`robotics`。
3. **Transport Adapter**：把 Core 契约映射到 IPC、HTTP、MQTT、Fast DDS、ROS 2、
   Modbus、CAN 或串口。Adapter 位于项目边缘，不能反向污染业务接口。

```text
UI / CLI / Bundle / Process Host
                |
       Application Service
                |
   PocoDDS::RuntimeCore Ports
                |
       IMessageTransport
        /       |       \
    inproc   project IPC   ROS 2 / Fast DDS / MQTT
   built-in    adapter          adapter
```

`PDR_TRANSPORTS` 是项目允许并计划组合的传输集合，不等于所有 Adapter 都已随 CMake
生成。配置产生的 `pdr-framework-model.json` 会进一步记录：

- `transportResolution.builtIn`：本次构建已有实现；轻量 Core 提供 `inproc`，原有完整
  Runtime 保留兼容的 Fast DDS 路径；
- `transportResolution.externalAdapters`：必须由项目或外部工作区构建、部署并验收；
- `capabilities`：只有本次构建可以证明的运行能力才为 `true`。仅把 `ros2` 写入
  `PDR_TRANSPORTS`，不会伪造“ROS 2 已构建”的证据。

## 各模型使用方法

### `desktop-lite`：普通桌面应用默认模型

适用于单进程 Qt Widgets/Qt Quick、Win32、CLI、离线数据处理、设备配置器和小型上位机。

- 只构建 `RuntimeCore` 和同步 `InProcessTransport`；
- 支持普通 `module`、`service`；
- 不启动 OSP，不加载 Bundle，不拉起受管子进程；
- Core 不依赖 ROS 2、Fast DDS、Poco、Qt 或设备 SDK；
- 设备驱动放在产品 Adapter，通过自有 Port 注入 Service。

```powershell
cmake --preset desktop-lite
cmake --build --preset desktop-lite
ctest --preset desktop-lite -C Release --output-on-failure
cmake --install build/profiles/desktop-lite --config Release `
  --prefix build/install/desktop-lite

./tools/pdr.ps1 project create Configurator `
  --output E:/Products --profile desktop-lite
./tools/pdr.ps1 new module DomainModel --output E:/Products/Configurator/modules
./tools/pdr.ps1 new service DeviceApplication --output E:/Products/Configurator/services
```

`desktop-lite` 清单会拒绝 Device、Workflow、Bundle 和受管 Subprocess，防止轻量项目
悄悄重新引入完整 Runtime。需要这些能力时应显式升级 Profile。

### `desktop-distributed`：桌面多进程/联网模型

当桌面应用需要渲染进程、算法进程、插件沙箱或局域网访问时使用。Core 仍保持轻量，
IPC/HTTP/WebSocket 由产品 Adapter 实现并通过 `IMessageTransport` 或业务 Port 注入。

```powershell
cmake --preset desktop-distributed
cmake --build --preset desktop-distributed
./tools/pdr.ps1 project create InspectionStation `
  --output E:/Products --profile desktop-distributed
```

该 Preset 声明允许的 IPC/HTTP/WebSocket 边界，但仓库当前只内置 `inproc` 实现。项目需
自行提供 Adapter 构建、协议版本、重连、背压、鉴权和端到端验收证据。若需 Runtime
统一监管多个 Bundle/子进程，直接选 `edge-test`，不要在 Desktop Host 中复制 OSP。

### `embedded`：资源受限服务模型

适用于无桌面 UI 的设备进程。保留现有 Fast DDS 兼容路径和 Launcher，关闭 WebUI、
数据模块、Qt3D 与完整可观测性。现场协议属于 Adapter，不能进入 Application/Service 接口。

```powershell
cmake --preset embedded
cmake --build --preset embedded
```

### `edge-industrial` / `edge-test`：大型工业应用模型

需要动态 Bundle、设备注册、子进程看护、运行治理、WebUI、指标和业务追踪时选择 OSP
Host。`edge-industrial` 面向交付设备，`edge-test` 面向测试台和桌面集成环境。

```text
Host -> Runtime -> Process -> Bundle -> Service
```

Host 拥有操作系统进程；Runtime 负责 Process 和 Bundle 生命周期；Bundle 只做服务注册；
Service 拥有业务能力。业务流程不能堆进 Bundle Activator，Subprocess 不能访问主进程的
Service Registry。

### `server`：集中服务模型

适合长时间运行的数据服务、集中运维和多项目接入。默认包含数据与可观测模块。若服务只是
小型 REST 后端且不需要动态 Bundle/子进程治理，应使用 Core 加项目 HTTP Host，避免因为
“服务端”三个字自动引入整套 OSP。

### `robotics`：机器人模型

机器人 Core 依赖 `RuntimeCore`，但不直接包含 ROS 2 头文件。生命周期、Action、行为编排
和仿真属于 `PDRRoboticsRuntime`；ROS 2 位于 `robotics/ros2_ws` Adapter 层，使用
`colcon` 单独构建。

```powershell
cmake --preset robotics
cmake --build --preset robotics
ctest --preset robotics -C Release --output-on-failure

./tools/pdr.ps1 project create WarehouseRobot `
  --output E:/Products --profile robotics
```

只有 ROS 2 工作区构建、节点启动、Topic/Action 双向通信和目标机器人验收全部通过后，
才能宣称 ROS 2 路径完成；Core 仿真通过不能替代真实机器人验收。

## 项目清单与组合开关

新项目显式记录 Profile、Host 与允许的 Transport，不再从目录猜测：

```json
{
  "runtime": {
    "profile": "desktop-lite",
    "version": "0.1.x",
    "host": "static",
    "transports": ["inproc"]
  }
}
```

变更后执行：

```powershell
./tools/pdr.ps1 project validate E:/Products/Configurator/pdr-project.yaml
./tools/pdr.ps1 project sync E:/Products/Configurator/pdr-project.yaml
./tools/pdr.ps1 project resolve E:/Products/Configurator/pdr-project.yaml `
  --output E:/Products/Configurator/pdr-project.lock.json
```

生成的 `pdr-project.components.cmake` 按三个平面组合：

- `PDR_PROJECT_BUILD_APPLICATION`：传输无关的 Module/Service，默认开启；
- `PDR_PROJECT_BUILD_MANAGEMENT`：Device/Workflow/Bundle/Subprocess，仅管理模型默认开启；
- `PDR_PROJECT_BUILD_ROBOTICS`：机器人模块、进程和硬件/仿真 Adapter，仅机器人模型开启。

## 模型升级

推荐迁移顺序：

1. 修改 `runtime.profile`、`host`、`transports`；
2. 执行 `project validate` 和 `project sync`；
3. 保持业务 Module/Service 不变；
4. 新增 Host 和 Transport Adapter；
5. 分别完成单元、进程内、跨进程、跨机和实际设备验收；
6. 保存框架模型清单、项目锁文件和测试报告作为交付证据。

常见路径是 `desktop-lite -> desktop-distributed -> edge-test/edge-industrial`，或
`desktop-lite -> robotics`。如果升级时必须修改大量业务接口，说明 Transport 或 Host
已经越过 Adapter 边界，应先修复依赖方向。

## 新增 Transport 的完成定义

1. 实现 `IMessageTransport` 或清晰的业务 Port Adapter；
2. Core 与业务头文件中不出现第三方中间件头文件；
3. 明确消息类型、Schema 版本、QoS、超时、取消、重连和背压；
4. 提供进程内单测、跨进程集成测试和故障注入；
5. 分开报告构建、Adapter 启动、消息闭环和目标环境验收；
6. 在项目清单登记 Transport，并让框架模型反映真实 built-in/external 状态。

`tools/check_architecture.py` 会扫描 `runtime-core` 与 `robotics`，禁止稳定 Core 直接包含
Poco/OSP、Fast DDS、ROS 2 或 Qt 头文件。确需越界应先写 ADR，不能直接关闭测试。
