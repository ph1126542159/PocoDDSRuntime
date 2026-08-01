# 公共 SDK 与模块脚手架

## SDK 边界

外部产品通过安装后的 CMake Package 使用框架：

```cmake
find_package(PocoDDSRuntime 0.1 CONFIG REQUIRED)
target_link_libraries(my_application PRIVATE PocoDDS::SDK)
```

`PocoDDS::SDK` 是稳定基础能力聚合入口，目前包括：

- `PocoDDS::Application`：命令上下文、Result/Error 和 Workflow；
- `PocoDDS::Configuration`：类型、范围和必填配置校验；
- `PocoDDS::DeviceCore`：稳定的 Device、DeviceSnapshot 和生命周期接口；
- `PocoDDS::Reliability`：超时、重试、熔断、背压和关闭协作；
- `PocoDDS::Health`：统一健康状态与贡献者；
- `PocoDDS::Persistence`：Repository、事务和迁移模型；
- `PocoDDS::SDK::versionString`：编译期 SDK 版本。

业务代码不应通过聚合入口直接依赖 Qt、Fast DDS、OSP、SQLite 或
OpenTelemetry 的实现类型。这些实现通过产品适配器或更细粒度组件接入。

## 安装后消费验证

`sdk-external-consumer` 测试执行三个步骤：

1. 将当前构建安装到隔离目录；
2. 在 `tests/sdk-consumer` 中执行独立的 `find_package`；
3. 编译并运行只依赖 `PocoDDS::SDK` 的外部程序。

这项测试用于防止出现“仓库内可以构建，但安装包无法被其他项目使用”的回归。

## 开发者命令

Windows PowerShell：

```powershell
./tools/pdr.ps1 doctor
./tools/pdr.ps1 new service TemperatureService --output services
./tools/pdr.ps1 new device CanTemperatureSensor --output platform/devices
./tools/pdr.ps1 new workflow BoardPowerOnTest --output application/workflows
```

Linux 或直接使用 Python：

```bash
python3 tools/pdr.py doctor
python3 tools/pdr.py new service TemperatureService --output services
```

名称必须采用 PascalCase。脚手架生成公共头文件、实现、CMake Target、冒烟测试和
集成说明。目标目录已有内容时命令默认拒绝覆盖；只有明确传入 `--force` 才会覆盖。

`new device` 生成的不是占位类，而是可编译的 `PocoDDS::Devices::Device` 和
`DiagnosticDevice` 实现，包含唯一 ID、启动/停止状态、快照、命令入口、回调、
成功操作诊断以及索引式多实例配置示例。模板默认
提供 `ping` 命令作为最小闭环；接入实际硬件时替换命令和快照逻辑即可。

## 新模块接入

生成完成后，在所属产品的 CMake 文件中加入：

```cmake
add_subdirectory(path/to/TemperatureService)
```

随后重新配置、构建并执行 CTest。生成模板只依赖 `PocoDDS::SDK`，具体协议、设备或
传输实现应由构造函数或适配器注入，避免业务模块重新耦合到底层实现。
