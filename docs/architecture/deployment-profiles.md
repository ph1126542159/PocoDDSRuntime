# 部署 Profile

框架提供七种有明确能力边界的交付档位。不要通过复制构建目录裁剪产品；应选择对应 Preset，使编译目标、安装内容和 Profile 清单保持一致。详细选型见[框架模型选择与项目适配](framework-model-selection.md)。

| Profile | CMake Preset | Host | Legacy/OSP | Robotics | Web UI | 典型用途 |
| --- | --- | --- | ---: | ---: | ---: | --- |
| Desktop Lite | `desktop-lite` | static | 关 | 关 | 关 | 普通单进程桌面应用 |
| Desktop Distributed | `desktop-distributed` | desktop | 关 | 关 | 关 | 内置本机 IPC、项目自带 HTTP Adapter 的桌面应用 |
| Embedded | `embedded` | service | 开 | 关 | 关 | PetaLinux、资源受限设备 |
| Edge Industrial | `edge-industrial` | osp | 开 | 关 | 开 | 工业网关、边缘控制器 |
| Edge/Test | `edge-test` | osp | 开 | 关 | 开 | 测试台、现场上位机 |
| Server | `server` | osp | 开 | 关 | 开 | 后台服务、集中部署 |
| Robotics | `robotics` | robotics | 关 | 开 | 关 | 机器人 Core 与仿真；ROS 2 外置 |

## 构建与安装

```powershell
cmake --preset embedded
cmake --build build/profiles/embedded --config Release
cmake --install build/profiles/embedded --config Release --prefix build/install/embedded
```

将 `embedded` 替换为上表任一 Preset 即可构建其他档位。命名交付 Profile 默认不包含 Qt3D；兼容的 `default` Preset 会启用 Qt3D Demo，用于原有完整 Runtime 的本机多进程验证。不同 CPU 架构和 Profile 必须使用独立构建、安装目录，不能混用二进制依赖。

## 可审计能力清单

每次安装都会生成 `share/PocoDDSRuntime/pdr-profile.json`。部署、升级和问题报告应同时保存该文件；它记录版本、Profile 名称以及最终实际构建出的功能，而不是仅记录用户请求的开关。

每次 CMake 配置还会生成 `pdr-framework-model.json`，并安装到
`share/PocoDDSRuntime/pdr-framework-model.json`。启用 Home WebUI 时，同一文件会被复制到
Web Bundle 的 `/home/framework-model.json`。WebUI 只显示清单中 `navigation` 声明且对应
`capabilities` 为真的页面，因此切换 `PDR_PROFILE`、`PDR_HOST_MODEL`、`PDR_TRANSPORTS`、
`PDR_BUILD_LEGACY_RUNTIME` 或 `PDR_BUILD_ROBOTICS_RUNTIME` 后不需要修改 React 菜单。

框架族由实际构建目标解析：仅 Legacy/OSP 为 `generic`，仅机器人核心为 `robotics`，
同时构建两者为 `hybrid`，仅 transport-neutral Runtime Core 为 `core`。纯 Core Profile
没有 HTTP Host，因此保留可审计清单但不发布管理页面；机器人独立 Web 服务通过
`GET /framework-model.json` 暴露相同契约。

OSP Profile 包含独立的 `pdr.platform.health` 轻量 Bundle，并统一提供 `/health/live`、`/health/ready` 和 `/health/detail`。纯 Core 与 Robotics Profile 不带 HTTP Host，其健康状态由产品入口或机器人控制面暴露。
DiagnosticTerminal 依赖指标与 TraceStore，仅在 `PDR_ENABLE_OBSERVABILITY=ON` 的 Profile 中构建；
`embedded` 关闭该模块时，框架能力清单中的 `diagnosticTerminal` 必须为 `false`。

仓库测试 `deployment-profiles` 会校验 Preset 与能力矩阵。每个 Profile 还应在自己的构建目录运行：

```powershell
ctest --test-dir build/profiles/embedded -C Release --output-on-failure
```

Desktop Lite 安装只应包含 RuntimeCore；Desktop Distributed 应包含 RuntimeCore 与
LocalIpc；Embedded 包中不应出现 `pdr.webui.*.bndl` 或 Qt3D 子进程；Edge/Test 应包含
Web UI Bundle，但不包含 Qt3D Demo；Server 应包含 Web UI 和数据模块；Robotics 应包含
RuntimeCore 与 Robotics Runtime，不应包含 OSP Bundle。

全新安装包必须能够直接启动，且 `bin/logs`、`bin/data`、`bin/codeCache` 三个可写目录必须存在。可用随机端口执行真实运行验证：

```powershell
python bin/runtime_smoke.py `
  --executable build/install/embedded/bin/pdr-runtime.exe `
  --working-directory build/install/embedded/bin `
  --path build/install/embedded/bin `
  --report build/reports/runtime-smoke-embedded.json
```

CTest 中的 `runtime-package-smoke` 会先安装到隔离目录，再启动交付包并验证 liveness/readiness，避免构建目录中的文件掩盖安装缺失。
