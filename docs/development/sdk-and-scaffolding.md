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
- `PocoDDS::Security`：环境注入 Principal、恒定时间 Bearer 认证和权限判断；
- `PocoDDS::DeviceCore`：稳定的 Device、DeviceSnapshot 和生命周期接口；
- `PocoDDS::Reliability`：超时、重试、熔断、背压和关闭协作；
- `PocoDDS::Health`：统一健康状态与贡献者；
- `PocoDDS::Persistence`：Repository、事务和迁移模型；
- `PocoDDS::SDK::versionString`：编译期 SDK 版本。

只需要身份能力的适配器也可以请求 `COMPONENTS Security` 并直接链接
`PocoDDS::Security`，无需引入完整 SDK。

业务代码不应通过聚合入口直接依赖 Qt、Fast DDS、OSP、SQLite 或
OpenTelemetry 的实现类型。这些实现通过产品适配器或更细粒度组件接入。

可部署插件使用单独的稳定入口：

```cmake
find_package(PocoDDSRuntime CONFIG REQUIRED COMPONENTS Plugins)
pdr_add_osp_bundle(MyPlugin
  SYMBOLIC_NAME pdr.plugin.myplugin
  BUNDLE_SPEC MyPlugin.bndlspec
  SOURCES src/BundleActivator.cpp)
```

外部插件只链接 `PocoDDS::Plugins` 并通过 OSP Service Registry 发布服务；不要直接链接
内部 `PocoDDS::OSP` Target。安装包提供 BundleCreator 和 `pdr_add_osp_bundle`，统一生成
带版本的 `.bndl`。交叉编译时必须通过 `PDR_BUNDLE_CREATOR_COMMAND` 指定可在构建主机运行的
BundleCreator 命令，防止误执行目标机二进制。

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
./tools/pdr.ps1 identity check config/pdr-runtime.properties config/site.properties `
  --prefix build/install --report build/reports/identity-check.json
./tools/pdr.ps1 project create WarehouseRobot --output E:/Products --profile robotics
./tools/pdr.ps1 new module TemperatureModel --output modules
./tools/pdr.ps1 new service TemperatureService --output services
./tools/pdr.ps1 new device CanTemperatureSensor --output platform/devices
./tools/pdr.ps1 new workflow BoardPowerOnTest --output application/workflows
./tools/pdr.ps1 new bundle AcmeDiagnostics --output bundles
./tools/pdr.ps1 new plugin AcmeDiagnostics --output plugins
./tools/pdr.ps1 new subprocess VisionWorker --output subprocesses
./tools/pdr.ps1 new robot-module ChargingModule --output modules
./tools/pdr.ps1 new robot-hardware-adapter CanDrive --output adapters/hardware
./tools/pdr.ps1 new robot-simulation-adapter WarehouseWorld --output adapters/simulation
./tools/pdr.ps1 new robot-process VisionWorker --output processes
./tools/pdr.ps1 new ros2-node MissionGateway --output adapters/ros2
./tools/pdr.ps1 verify platform/devices/CanTemperatureSensor `
  --prefix build/install `
  --config Release --report build/reports/can-temperature-sensor-verify.json
./tools/pdr.ps1 verify plugins/AcmeDiagnostics `
  --prefix build/install --config Release `
  --artifact-output build/plugin-dist `
  --report build/reports/acme-diagnostics-verify.json
```

Linux 或直接使用 Python：

```bash
python3 tools/pdr.py doctor --prefix build/install \
  --report build/reports/developer-doctor.json
python3 tools/pdr.py validate-config config/pdr-runtime.properties \
  --prefix build/install --report build/reports/config-validation.json
python3 tools/pdr.py identity check config/pdr-runtime.properties config/site.properties \
  --prefix build/install --report build/reports/identity-check.json
python3 tools/pdr.py persistence inspect build/bin/management-tasks.json \
  --kind tasks --report build/reports/tasks-inspect.json
python3 tools/pdr.py new service TemperatureService --output services
python3 tools/pdr.py component status services/TemperatureService --check
python3 tools/pdr.py verify services/TemperatureService \
  --prefix build/install --config Release \
  --report build/reports/temperature-verify.json
```

名称必须采用 PascalCase。`module/service/device/workflow` 脚手架生成公共头文件、实现、
CMake Target、冒烟测试和集成说明；`subprocess` 生成独立可执行文件、自检、安装规则和
`pdr-subprocesses.properties` 合并片段。目标目录已有内容时命令默认拒绝覆盖；只有明确传入
`--force` 才会覆盖。

所有生成类型都写入 `.pdr-component.json`，并把 CMake、README、`package.xml` 和
`.bndlspec` 作为版本化结构文件；业务源码仍由产品维护。模板状态、旧组件采用、冲突升级和
中断恢复的完整规则见[组件模板升级](component-templates.md)。

`new bundle` 是 `new plugin` 的用户侧别名，两者都生成 BundleActivator、Service、
`.bndlspec` 和打包规则，并使用受治理的 `pdr.plugin.*` 命名。`verify` 会要求
插件实际产出 `.bndl`，并在 JSON 中记录文件名、大小和 SHA-256；`--artifact-output` 将验证过的
Bundle 复制到发布目录。`generated-plugin-consumer` 回归测试还会把该 Bundle 放入隔离安装的
Runtime，只有日志确认插件启动后才通过。部署到生产目录前应停止 Runtime、保留旧 Bundle，
验证新包后再启动；加载失败时恢复旧包，而不是在线覆盖正在使用的文件。

## 插件发布事务

生产目录不要直接复制或覆盖 `.bndl`。先从 `pdr verify` 报告取得 SHA-256，再在 Runtime
停止后执行签名、预检和安装。私钥路径只通过环境变量传入，私钥不进入源码、报告或插件包：

```powershell
$env:PDR_PLUGIN_PRIVATE_KEY_PATH = "C:/secure/vendor-ed25519-private.pem"
./tools/pdr.ps1 plugin sign build/plugin-dist/pdr.plugin.acmediagnostics_1.0.0.bndl `
  --publisher-id acme --key-id acme-2026-q3 `
  --private-key-path-environment PDR_PLUGIN_PRIVATE_KEY_PATH `
  --attestation build/plugin-dist/acme.attestation.json `
  --signature build/plugin-dist/acme.signature.json
./tools/pdr.ps1 plugin preflight build/plugin-dist/pdr.plugin.acmediagnostics_1.0.0.bndl `
  --bundle-directory C:/PocoDDSRuntime/bin/bundles `
  --expected-sha256 <approved-sha256> `
  --attestation build/plugin-dist/acme.attestation.json `
  --signature build/plugin-dist/acme.signature.json --public-key C:/secure/acme-public.pem `
  --trust-policy C:/PocoDDSRuntime/policy/plugin-trust-policy.json `
  --expected-trust-policy-id plugin-publishers-2026-q3 `
  --expected-trust-policy-sha256 <approved-policy-sha256> `
  --report build/reports/plugin-preflight.json
./tools/pdr.ps1 plugin install build/plugin-dist/pdr.plugin.acmediagnostics_1.0.0.bndl `
  --bundle-directory C:/PocoDDSRuntime/bin/bundles `
  --expected-sha256 <approved-sha256> --confirm-runtime-stopped `
  --attestation build/plugin-dist/acme.attestation.json `
  --signature build/plugin-dist/acme.signature.json --public-key C:/secure/acme-public.pem `
  --trust-policy C:/PocoDDSRuntime/policy/plugin-trust-policy.json `
  --expected-trust-policy-id plugin-publishers-2026-q3 `
  --expected-trust-policy-sha256 <approved-policy-sha256> `
  --report build/reports/plugin-install.json
```

插件默认必须具有 Ed25519 签名。信任策略把 `publisherId + keyId` 绑定到允许的
`pdr.plugin.*` 命名范围、公钥摘要和有效期，并维护吊销列表；attestation 同时绑定插件文件
摘要、符号名、版本和 API/ABI 契约。`--allow-unsigned-plugin` 只用于隔离诊断，报告和审计会
明确记录 bypass，生产流程不得启用。

预检会限制归档大小和文件数、拒绝路径穿越/链接/重复路径、校验唯一 Manifest、限定
`pdr.plugin.*` 命名，并核对 `Require-Bundle` 的存在性和版本范围。它还读取 Runtime 旁的
`pdr-plugin-runtime.json`，逐项核对插件 Manifest 中的 API 版本、ABI 版本、ABI 指纹和
Runtime 版本范围；缺字段、旧格式插件、不同目标平台或不同编译器主版本都会 fail-closed。
安装使用排他锁、持久化
事务日志、同目录 staging 和原子改名；旧版本保存在 Runtime `bin/plugin-backups`，审计追加到
`plugin-transactions.audit.jsonl`。失败时自动恢复旧版本；若恢复不能被证明，事务日志会保留，
后续安装会 fail-closed。

若主机掉电或进程在事务日志落盘后中断，保持 Runtime 停止并先执行恢复，再重试安装：

```powershell
./tools/pdr.ps1 plugin recover `
  --bundle-directory C:/PocoDDSRuntime/bin/bundles `
  --confirm-runtime-stopped --report build/reports/plugin-recover.json
```

恢复命令只接受已知的安装事务状态并校验所有日志路径边界：尚未发布的 staging 会被丢弃；
旧包已备份时会恢复并核对其摘要；已提交的新包只有在摘要仍匹配时才完成事务。未知或证据不足的
状态保持 fail-closed，不会删除事务日志。

人工回退同时绑定当前版本和备份版本的摘要，避免回退错目标：

```powershell
./tools/pdr.ps1 plugin rollback pdr.plugin.acmediagnostics `
  --bundle-directory C:/PocoDDSRuntime/bin/bundles `
  --expected-current-sha256 <current-sha256> `
  --expected-backup-sha256 <backup-sha256> `
  --confirm-runtime-stopped --report build/reports/plugin-rollback.json
```

目录事务只负责发布和回退文件。重启 Runtime 后仍需在 Web“插件治理”页确认
`governanceStatus=ready`，且 `compatibilityIssues` 为空，再执行受认证的启动操作并检查业务
服务注册结果。Runtime 使用与离线预检相同的 Manifest 字段再次门禁，不能用手工复制绕过。

`pdr_add_osp_bundle` 会自动把安装 SDK 导出的兼容性常量写入 Bundle。它在配置阶段检查插件
编译器 ID 和主版本与 Runtime 一致，再生成 `PDR-Plugin-API`、`PDR-Plugin-ABI`、
`PDR-Plugin-ABI-Fingerprint` 和 `PDR-Runtime-Version`。不要手工伪造这些值；框架发生破坏性
ABI 变更时必须提升 ABI 版本/指纹并重新构建插件。

`doctor` 验证源码根目录、Python 3.9+、CMake 3.24+、CTest，以及指定安装前缀中的
`PocoDDSRuntimeConfig.cmake`、真实导出的 `PocoDDS::SDK` Target 和 `PocoConfig.cmake`。
失败项会给出修复建议；`--report` 生成适合 CI 和客户问题单归档的 JSON。默认安装前缀为
`<root>/build/install`，其他构建或部署布局必须显式传 `--prefix`，不再依赖写死的构建目录。
安装后的 `bin/pdr.py`/`bin/pdr.ps1` 会识别自身所在安装前缀，因此统一 SDK 安装包内可省略
`--prefix`；源码树运行仍默认使用 `<root>/build/install`。

`identity inspect` 适合开发诊断，始终输出身份总数、文件型/环境型来源数量、权限检查完整性和
宽权限文件数量，但不输出 Principal ID、路径或令牌。`identity check` 是 fail-closed 的生产
门禁：未启用强制认证、没有文件型身份、ACL/mode 无法确认或存在宽权限文件都会返回非零。
原生 `pdr-identity-check` 与 Runtime 共用 `PrincipalStore`，避免 Python 与运行时产生两套规则。

框架与第三方开发包分开安装时，`--prefix` 指向 PocoDDSRuntime，`--dependency-prefix` 指向
包含 `cmake/PocoConfig.cmake` 的 Poco 前缀。JSON 分别记录 `prefix` 和
`dependencyPrefix`，避免把合法的双前缀 SDK 布局误报为依赖缺失：

```powershell
bin/pdr.ps1 doctor --dependency-prefix C:/pdr-dependencies `
  --report doctor.json
```

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

## 插件启动失败与隔离

Runtime 对 `pdr.plugin.*` 记录启动失败预算。默认连续失败 3 次后进入隔离，状态原子写入
`data/plugin-quarantine.json`；下次启动时在外部插件 runlevel 之前加载，已隔离插件不会自动启动。
进程详情和 Web 插件治理页显示失败计数、最近错误和持久化健康状态。修复后向
`POST /api/v1/bundle-lifecycle` 提交 `{"id":"pdr.plugin.example","action":"reset-quarantine"}`。

隔离文件损坏时采用 fail-closed，阻止所有外部插件自动启动。恢复必须额外提交
`"confirmPersistenceRecovery":true`，这会重建快照，无法读取的旧记录可能丢失。该机制只处理 OSP
启动阶段抛出的异常；进程内原生崩溃、内存破坏和卡死仍必须由进程级监督处理。

需要原生故障边界的插件使用 `pdr plugin scaffold-isolated` 生成单插件宿主。该命令从 Bundle
Manifest 读取 symbolic name 和直接依赖，拒绝缺失依赖或覆盖已有实例，并同时生成 launcher 心跳、
重启预算和资源限制配置。Windows 限制由 Job Object 强制执行；Linux 数值限制要求部署层先委派
cgroup v2 目录。隔离插件通过 DDS 或公开协议通信，不能消费主 Runtime 的进程内 ServiceRegistry。

脚手架完成后不要手工复制编号槽位。停止 Runtime，再执行 `pdr plugin apply-isolated <实例名>
--runtime-root <bin> --confirm-runtime-stopped`；该命令校验部署摘要、保留既有子进程、连续重编号并原子
替换配置。使用 `list-isolated` 审计受管实例。使用 `remove-isolated` 解除登记；只有明确需要销毁可回滚
文件时才增加 `--purge`。配置变更在下次 Runtime 启动时生效。
