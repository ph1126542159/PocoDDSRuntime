# PocoDDSRuntime 组件文档

本目录按仓库当前 CMake 构建结构整理。每个正式组件都有独立 README，内容包括职责、实现过程、使用方法和限制。若代码、配置与文档不一致，以当前代码和 `config/*.properties` 为准。

## 阅读顺序

1. [运行时主程序](components/runtime/README.md)
2. [Fast DDS 通信层](components/dds/README.md)
3. [设备网关服务](components/services/device-gateway/README.md)
4. 按需阅读具体协议、设备或业务服务文档
5. 需要追踪业务链路时阅读[业务追踪](BUSINESS_TRACING.md)
6. 平台治理入口：[分层规则](architecture/layering-rules.md)、[部署 Profile](architecture/deployment-profiles.md)、[稳定性与设备验收矩阵](operations/acceptance-matrix.md)、[ADR](adr/README.md)
7. 运维入口：[运行手册](operations/runbook.md)、[故障排查](operations/troubleshooting.md)、[恢复手册](operations/recovery.md)
8. 基于框架开发新产品时阅读：[公共 SDK 与脚手架](development/sdk-and-scaffolding.md)
9. 生产部署和发布前阅读：[安全基线](security/README.md)

## 项目目录结构

```text
PocoDDSRuntime/
├─ CMakeLists.txt                 # 项目主构建入口，组织平台、服务、子系统和 WebUI
├─ README.md                      # 项目总体介绍、构建和运行说明
├─ cmake-variants.json            # VS Code CMake Tools 构建变体
├─ cmake/                         # 第三方依赖、交叉编译和安装规则
├─ config/                        # 运行时、子进程和追踪采集器配置
├─ docs/                          # 中文组件文档和专题说明
│  ├─ README.md                   # 本文档，文档总入口
│  ├─ BUSINESS_TRACING.md         # 业务追踪 API 与数据安全规则
│  └─ components/                 # 各组件独立 README
├─ platform/                      # 运行时基础库、协议层和设备层
│  ├─ DDS/                        # Fast DDS 封装、服务端点和设备桥接
│  ├─ observability/              # 业务追踪、存储和 OTLP 导出
│  ├─ BundleManagement/           # OSP Bundle 目录热更新
│  ├─ ProcessManagement/          # 外部子进程启动和停止管理
│  ├─ OSP/                        # Bundle 生命周期、本地服务注册及 Web 基础设施
│  ├─ protocols/                  # BtLE、CAN、Modbus、MQTT、ROS、串口等协议
│  ├─ devices/                    # 设备抽象及各种物理/仿真设备实现
│  ├─ CodeGeneration/             # C++ 代码生成基础库
│  ├─ Geo/                        # 角度和地理坐标工具
│  ├─ Serial/                     # Win32/POSIX 串口底层库
│  └─ WebTunnel/                  # Web 隧道及端口转发基础库
├─ services/                      # 独立打包的 OSP 业务服务
│  ├─ DeviceGateway/              # 设备创建、注册和 DDS 桥接
│  ├─ UnitsOfMeasure/             # UCUM 单位查询和换算
│  ├─ NetworkEnvironment/         # 网络接口查询和变化通知
│  ├─ DeviceStatus/               # 设备状态及状态消息管理
│  ├─ WebEvent/                   # Web 事件分发
│  └─ MobileConnection/           # 移动网络连接服务
├─ server/                        # pdr-runtime 主程序
├─ SubSystem/
│  └─ launcher/                   # 独立看门狗/进程拉起程序 pdr-launcher
├─ webui/                         # Vite/React 前端及 OSP Web Bundle
│  ├─ login/                      # 登录页面
│  ├─ home/                       # 运行时管理主页
│  └─ tracing/                    # 业务追踪流程图页面
├─ scripts/                       # Windows/Linux/PetaLinux 构建和测试脚本
├─ build/                         # CMake 生成物、依赖、可执行文件和安装树
├─ .github/                       # GitHub 工作流及仓库配置
└─ .vscode/                       # VS Code 工作区配置
```

### 目录之间的关系

1. `server/` 启动 OSP 容器，并加载由 `services/` 和 `webui/` 生成的 Bundle。
2. `services/DeviceGateway` 使用 `platform/devices` 创建设备；设备实现再调用 `platform/protocols` 与物理设备通信。
3. `platform/DDS` 负责不同进程或主机之间的请求、响应、事件和设备状态传递。
4. `SubSystem/launcher` 独立于 `pdr-runtime`，用于从外部监护和重新拉起目标进程。
5. `cmake/` 与 `scripts/` 共同完成依赖构建、本机编译和 PetaLinux 交叉编译，结果写入 `build/`。
6. `docs/components/` 与上述源码目录一一对应，用于记录各组件实现过程和使用方法。

> `build/` 是生成目录，不应在其中直接维护源码或文档；需要修改的配置模板位于 `config/`，构建后再复制到运行目录。

## 组件索引

### 运行时与基础设施

- [pdr-runtime](components/runtime/README.md)：OSP 容器、配置加载及子进程启动入口
- [OSP](components/osp/README.md)：Bundle 生命周期与本地服务注册
- [BundleManagement](components/bundle-management/README.md)：Bundle 目录热更新
- [ProcessManagement](components/process-management/README.md)：子进程编排
- [DDS](components/dds/README.md)：Fast DDS 进程间通信
- [Observability](components/observability/README.md)：业务链路追踪
- [平台辅助库总览](components/platform-support/README.md)
- [CodeGeneration](components/platform-support/code-generation/README.md)
- [Geo](components/platform-support/geo/README.md)
- [Serial 底层库](components/platform-support/serial/README.md)
- [WebTunnel 底层库](components/platform-support/web-tunnel/README.md)
- [pdr-launcher](components/launcher/README.md)：独立看门狗/拉起程序

### 物理协议

- [协议组件总览](components/protocols/README.md)
- [BtLE](components/protocols/btle/README.md)
- [CAN](components/protocols/can/README.md)
- [Modbus TCP](components/protocols/modbus/README.md)
- [MQTT](components/protocols/mqtt/README.md)
- [ROS Bridge](components/protocols/ros/README.md)
- [Serial](components/protocols/serial/README.md)
- [UDP](components/protocols/udp/README.md)
- [WebTunnel](components/protocols/web-tunnel/README.md)
- [XBee](components/protocols/xbee/README.md)

### 设备模型与设备实现

- [设备组件总览](components/devices/README.md)
- [设备基础模型](components/devices/core/README.md)
- [CAN 信号传感器](components/devices/can/README.md)
- [GNSS](components/devices/gnss/README.md)
- [Linux GPIO/LED](components/devices/linux/README.md)
- [Modbus 寄存器设备](components/devices/modbus/README.md)
- [串口设备](components/devices/serial/README.md)
- [仿真设备](components/devices/simulation/README.md)
- [XBee 模拟量传感器](components/devices/xbee-sensor/README.md)

### OSP 业务服务

- [服务组件总览](components/services/README.md)
- [DeviceGateway](components/services/device-gateway/README.md)
- [UnitsOfMeasure](components/services/units-of-measure/README.md)
- [NetworkEnvironment](components/services/network-environment/README.md)
- [DeviceStatus](components/services/device-status/README.md)
- [WebEvent](components/services/web-event/README.md)
- [MobileConnection](components/services/mobile-connection/README.md)

### WebUI

- [WebUI 总览](components/webui/README.md)
- [登录页](components/webui/login/README.md)
- [主页与管理界面](components/webui/home/README.md)
- [业务追踪页](components/webui/tracing/README.md)

## 通用构建与运行

```powershell
cmake -S . -B build -G "Visual Studio 17 2022" -A x64
cmake --build build --config Release --parallel 2
ctest --test-dir build -C Release --output-on-failure
Set-Location build/bin
./pdr-runtime.exe
```

Linux 与 PetaLinux SDK 构建入口分别为 `scripts/build-host.sh` 和 `scripts/build-petalinux.sh`。
