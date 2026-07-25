# 部署 Profile

| Profile | CMake Preset | 用途 | 默认边界 |
| --- | --- | --- | --- |
| Embedded | `embedded` | PetaLinux/设备端 | 关闭完整 Observability 和数据模块 |
| Edge/Test | `edge-test` | Qt 端测与现场上位机 | 开启 Observability，使用本地数据 |
| Server | `server` | 后台服务 | 开启 Observability 和数据模块 |

配置命令：`cmake --preset edge-test`。不同 CPU 架构必须使用独立安装目录，不能复用二进制依赖。
