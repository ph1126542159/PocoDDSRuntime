# 稳定性与设备验收矩阵

本页定义从“仓库测试通过”到“可以用于现场”的证据边界。未取得对应环境的报告时，状态必须保持 `未验证`，不能用 Windows 主机结果代替板端或真实设备结果。

| 层级 | 环境 | 最低时长/轮次 | 必须通过 | 证据 |
| --- | --- | ---: | --- | --- |
| L0 | CI/开发机 | 每次提交 | 构建、CTest、隔离安装、自包含启动 | CTest XML、`runtime-package-smoke.json` |
| L1 | Windows Edge/Test | 24 h | readiness 全程通过、RSS/句柄增长在阈值内、Qt3D 1/1 | `runtime-soak-24h.json`、Runtime/Qt3D 日志、Profile 清单 |
| L2 | Linux Server | 24 h | readiness 全程通过、数据持久化、重启恢复 | Soak 报告、SQLite/日志、重启前后哈希 |
| L3 | PetaLinux Embedded | 24 h 后 72 h | 设备启动、网络恢复、磁盘空间、FD/RSS、看门狗恢复 | 板端 Soak、`journalctl`、`df -h`、`df -ih`、Profile 清单 |
| L4 | 真实协议/HIL | 每协议至少 1000 轮及断连注入 | 实际串口/CAN/Modbus/XBee/GNSS 读写、断线重连、错误边界 | 仪器/设备日志、请求响应计数、注入时间线 |
| L5 | 升级/回滚 | 每目标平台至少 20 轮 | 正常升级、坏包拒绝、健康失败自动回滚、断电恢复 | 升级审计 JSONL、版本/哈希、启动日志 |

L4 的统一采集入口是 `tools/device_acceptance.py`。测试期间由协议测试程序或人工工装持续产生真实读写流量，采集器负责从 `/api/v1/devices` 保存状态和诊断计数，并强制成功增量、失败上限、重连增量、连续失败上限与最终状态。

```powershell
python tools/device_acceptance.py `
  --url http://127.0.0.1:9080/api/v1/devices `
  --device-id cabinet-a --duration 3600 --interval 1 `
  --minimum-success-delta 1000 --minimum-reconnect-delta 1 `
  --maximum-failed-delta 2 --maximum-consecutive-failures 1 `
  --report reports/cabinet-a-hil.json
```

`minimumReconnectDelta=1` 适用于明确安排过断线注入的轮次；未注入断线的基线轮次设为 0。报告只有 `passed=true` 才能作为该轮证据，且仍需同时保存设备/总线侧日志来证明请求确实到达物理端。

CAN 的 L4 验收还必须覆盖标准帧与扩展帧过滤、经典 CAN 与 CAN FD、总线静默导致的 stale、error frame、bus-off 以及接口恢复。Linux 侧至少同时保存以下证据；接口名、bitrate 和恢复策略必须替换为产品实际值：

```sh
ip -details -statistics link show can0
candump -L -e can0
# 在隔离测试总线上执行受控 bus-off/断连注入
ip -details -statistics link show can0
curl -fsS http://127.0.0.1:9080/api/v1/devices
```

仓库的 `can-device-recovery` 和 `runtime-can-reference-smoke` 只验证软件状态机及 Bundle/API 闭环；Windows loopback 不证明 Linux 内核错误计数、物理收发器或终端电阻。

GNSS 的 `nmea-gnss-device-recovery` 覆盖 checksum、回调隔离、断线重连和定位陈旧；`runtime-gnss-reference-smoke` 覆盖 loopback Bundle/API/诊断闭环。两者都不替代真实模块、天线、卫星环境、首次定位时间和长时间漂移的目标机 HIL。

XBee 的 `xbee-smoke` 覆盖分片保留、转义长度和连续多帧，`xbee-sensor-recovery` 覆盖地址过滤、checksum、回调隔离、重连和陈旧样本，`runtime-xbee-reference-smoke` 覆盖 Bundle/API/诊断闭环。这些软件证据不替代真实串口、AP 模式、射频链路、远端采样周期和长期丢包 HIL。

GPIO/LED 的 `linux-sysfs-recovery` 覆盖临时节点消失与恢复、GPIO export 所有权和回调隔离；`runtime-linux-sysfs-reference-smoke` 覆盖可移植的 Bundle/API/诊断闭环。它不证明目标 Linux 内核启用了旧 sysfs ABI，也不证明权限、pinmux、电平或物理 LED。

## 通用通过条件

- `/health/live` 和 `/health/ready` 在稳定窗口及长稳采样中均为 HTTP 200。
- `/health/detail` 中所有必须组件为 `UP`；配置为启用的子进程必须全部运行。
- 所有 `required=true` 的设备必须为 `ready`；可选设备应显式配置 `required=false`，不能为了让发布门禁变绿而临时降低真实必需设备的等级。
- 进程不得提前退出，测试结束后不得残留 Runtime 或子进程。
- RSS、句柄/文件描述符增长不超过项目为该平台批准的阈值；阈值、初值、峰值和末值必须同时记录。
- 日志中不得出现未解释的 crash、fatal、重复重启或持续连接失败。
- 交付包必须在不引用源码构建目录、开发机 Qt SDK或依赖缓存的环境中启动。

## 建议执行顺序

1. 保存 `pdr-profile.json`、版本号、提交 ID、配置文件哈希和机器信息。
2. 执行 `runtime-package-smoke`，确认干净安装包可启动。
3. 执行 30 分钟预长稳，调整仅与目标平台资源容量有关的阈值。
4. 执行 24 小时长稳；失败必须从头重跑，不能只从失败点续计。
5. 对 Embedded 和 Server 候选版本执行 72 小时长稳。
6. 在长稳期间注入网络断开、设备断开和受控子进程崩溃，记录恢复时间。
7. 完成升级/回滚轮次后，将报告、日志、清单和审计记录归档到同一版本目录。

## PetaLinux 现场命令基线

先确认目标安装路径和服务名，再执行；不要把下面的占位名直接用于生产设备。

```sh
cat share/PocoDDSRuntime/pdr-profile.json
df -h
df -ih
ulimit -n
systemctl status pdr-runtime
journalctl -u pdr-runtime --since "24 hours ago" --no-pager
curl -fsS http://127.0.0.1:9080/health/detail
```

板端运行长稳时使用与主机相同的 `tools/soak_runner.py`，并设置 `--health-url`。如果目标镜像没有 Python，应由外部测试机定时探测健康接口，同时在板端通过 systemd/cgroup 采集资源；两份时间线必须使用同步时钟。

## 尚不能由本机替代的验收

真实 PetaLinux 镜像、板卡电源循环、物理协议设备、生产证书/OIDC、现场网络和 24/72 小时持续时间均需要外部环境。仓库中的自动测试只提供统一入口和判定格式，不构成这些项目已经通过的声明。
