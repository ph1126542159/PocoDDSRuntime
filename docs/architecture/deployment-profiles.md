# 部署 Profile

框架提供三种有明确能力边界的交付档位。不要通过复制构建目录裁剪产品；应选择对应 Preset，使编译目标、安装内容和 Profile 清单保持一致。

| Profile | CMake Preset | Observability | Data | Web UI | Launcher | Qt3D | 典型用途 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| Embedded | `embedded` | 关 | 关 | 关 | 开 | 关 | PetaLinux、资源受限设备 |
| Edge/Test | `edge-test` | 开 | 关 | 开 | 开 | 开 | Qt 端测、现场上位机 |
| Server | `server` | 开 | 开 | 开 | 开 | 关 | 后台服务、集中部署 |

## 构建与安装

```powershell
cmake --preset embedded
cmake --build build/profiles/embedded --config Release
cmake --install build/profiles/embedded --config Release --prefix build/install/embedded
```

将 `embedded` 替换为 `edge-test` 或 `server` 即可构建其他档位。Edge/Test 要求 Qt3D；如果 CMake 无法自动定位 Qt，可设置 `Qt6_DIR`。不同 CPU 架构和 Profile 必须使用独立构建、安装目录，不能混用二进制依赖。

## 可审计能力清单

每次安装都会生成 `share/PocoDDSRuntime/pdr-profile.json`。部署、升级和问题报告应同时保存该文件；它记录版本、Profile 名称以及最终实际构建出的功能，而不是仅记录用户请求的开关。

三个 Profile 都包含独立的 `pdr.platform.health` 轻量 Bundle，并统一提供 `/health/live`、`/health/ready` 和 `/health/detail`。健康探针不依赖完整 Observability，因此 Embedded 交付也能直接接入 systemd、容器编排和升级回滚检查。

仓库测试 `deployment-profiles` 会校验 Preset 与能力矩阵。每个 Profile 还应在自己的构建目录运行：

```powershell
ctest --test-dir build/profiles/embedded -C Release --output-on-failure
```

Embedded 包中不应出现 `pdr.webui.*.bndl` 或 Qt3D 子进程；Edge/Test 应同时包含三项 Web UI Bundle 和 Qt3D 子进程；Server 应包含 Web UI 和数据模块，但不包含 Qt3D 子进程。

全新安装包必须能够直接启动，且 `bin/logs`、`bin/data`、`bin/codeCache` 三个可写目录必须存在。可用随机端口执行真实运行验证：

```powershell
python bin/runtime_smoke.py `
  --executable build/install/embedded/bin/pdr-runtime.exe `
  --working-directory build/install/embedded/bin `
  --path build/install/embedded/bin `
  --report build/reports/runtime-smoke-embedded.json
```

CTest 中的 `runtime-package-smoke` 会先安装到隔离目录，再启动交付包并验证 liveness/readiness，避免构建目录中的文件掩盖安装缺失。
