# 公共 SDK 与模块脚手架

## SDK 边界

外部产品通过安装后的 CMake Package 使用框架：

```cmake
find_package(PocoDDSRuntime 0.1 CONFIG REQUIRED COMPONENTS SDK)
target_link_libraries(my_application PRIVATE PocoDDS::SDK)
```

不写 `COMPONENTS` 时默认只加载 `SDK`，兼容已有项目，也不会要求安装或查找 Paho MQTT。

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

协议 SDK 与基础 `PocoDDS::SDK` 分开。应用只选实际使用的协议目标，确实需要完整集合时才使用聚合目标：

```cmake
find_package(PocoDDSRuntime CONFIG REQUIRED COMPONENTS SDK MQTT UDP)
target_link_libraries(my_application PRIVATE PocoDDS::MQTT PocoDDS::UDP)
# 完整集合：BtLE/CAN/Modbus/MQTT/ROS/Serial/UDP/WebTunnel/XBee
find_package(PocoDDSRuntime CONFIG REQUIRED COMPONENTS SDK Protocols)
target_link_libraries(my_application PRIVATE PocoDDS::Protocols)
```

以上目标均从安装后的 `PocoDDSRuntimeConfig.cmake` 导出。Package Config 只按请求组件查找依赖：MQTT/Protocols 才加载 Paho，ROS/WebTunnel 才加载 Poco NetSSL；业务项目不需要手工填写 `.lib` 文件名。未知组件会在 `find_package` 阶段明确拒绝。

## 安装后消费验证

`sdk-external-consumer` 测试执行三个步骤：

1. 将当前构建安装到隔离目录；
2. 分别执行只请求 `SDK` 和请求 `SDK Protocols` 的独立 `find_package`；
3. 在禁用 Paho 查找的条件下编译运行基础 SDK Consumer；
4. 编译并运行链接已安装 `PocoDDS::Protocols` 的完整协议 Consumer；
5. 确认未知组件会被拒绝。

这项测试用于防止出现“仓库内可以构建，但安装包无法被其他项目使用”的回归。

## 开发者命令

Windows PowerShell：

```powershell
./tools/pdr.ps1 doctor --prefix build/install `
  --report build/reports/developer-doctor.json
./tools/pdr.ps1 validate-config config/pdr-runtime.properties `
  --executable build-verify/bin/pdr-config-check.exe `
  --report build/reports/config-validation.json
./tools/pdr.ps1 new service TemperatureService --output services
./tools/pdr.ps1 new device CanTemperatureSensor --output platform/devices
./tools/pdr.ps1 new workflow BoardPowerOnTest --output application/workflows
./tools/pdr.ps1 verify platform/devices/CanTemperatureSensor `
  --prefix build/install `
  --config Release --report build/reports/can-temperature-sensor-verify.json
```

Linux 或直接使用 Python：

```bash
python3 tools/pdr.py doctor --prefix build/install \
  --report build/reports/developer-doctor.json
python3 tools/pdr.py validate-config config/pdr-runtime.properties \
  --prefix build/install --report build/reports/config-validation.json
python3 tools/pdr.py new service TemperatureService --output services
python3 tools/pdr.py verify services/TemperatureService \
  --prefix build/install --config Release \
  --report build/reports/temperature-verify.json
```

名称必须采用 PascalCase。脚手架生成公共头文件、实现、CMake Target、冒烟测试和
集成说明。目标目录已有内容时命令默认拒绝覆盖；只有明确传入 `--force` 才会覆盖。

`doctor` 验证源码根目录、Python 3.9+、CMake 3.24+、CTest，以及指定安装前缀中的
`PocoDDSRuntimeConfig.cmake`、真实导出的 `PocoDDS::SDK` Target 和 `PocoConfig.cmake`。
失败项会给出修复建议；`--report` 生成适合 CI 和客户问题单归档的 JSON。默认安装前缀为
`<root>/build/install`，其他构建或部署布局必须显式传 `--prefix`，不再依赖写死的构建目录。
安装后的 `bin/pdr.py`/`bin/pdr.ps1` 会识别自身所在安装前缀，因此统一 SDK 安装包内可省略
`--prefix`；源码树运行仍默认使用 `<root>/build/install`。

`validate-config` 调用安装包中的 `pdr-config-check`，直接复用 Runtime 的 C++ 校验器；它不会
启动 OSP、网络监听、协议连接或子进程。可以依次传入基础配置和多个覆盖文件，后传入者优先。
退出码 0 表示通过，1 表示配置规则错误，2 表示文件、解析器或工具不可用。

`new device` 生成的不是占位类，而是可编译的 `PocoDDS::Devices::Device` 和
`DiagnosticDevice` 实现，包含唯一 ID、启动/停止状态、快照、命令入口、回调、
成功操作诊断以及索引式多实例配置示例。模板默认
提供 `ping` 命令作为最小闭环；接入实际硬件时替换命令和快照逻辑即可。

`verify` 在临时目录中依次执行 CMake configure、build 和 CTest，结束后不在模块源码旁留下
构建文件。它消费安装后的 `PocoDDSRuntimeConfig.cmake`，用于发现“仓库内部能编译、安装后
SDK 不能被客户模块消费”的问题。`--prefix` 可以重复传入框架和依赖安装前缀；统一安装
前缀中的 `<prefix>/cmake/PocoConfig.cmake` 会自动识别，非标准 Poco 布局可再传
`--poco-dir`。JSON 报告保存每一阶段的命令、退出码和完整输出，失败时
停止后续阶段并返回退出码 2。

## 新模块接入

生成完成后，在所属产品的 CMake 文件中加入：

```cmake
add_subdirectory(path/to/TemperatureService)
```

随后重新配置、构建并执行 CTest。生成模板只依赖 `PocoDDS::SDK`，具体协议、设备或
传输实现应由构造函数或适配器注入，避免业务模块重新耦合到底层实现。
