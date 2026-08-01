# 运行手册

1. 启动前先离线校验实际配置；该命令不会加载 Bundle、启动协议、绑定端口或创建子进程：

```powershell
build/install/bin/pdr.ps1 validate-config `
  build/install/bin/pdr-runtime.properties `
  site/production.properties `
  --prefix build/install `
  --report build/reports/production-config-validation.json
```

配置文件按命令行顺序分层，后面的文件覆盖前面的值，语义与 Runtime 的基础配置加现场覆盖一致。
成功输出 `CONFIG_VALIDATION_OK`；失败逐项输出 `key`、原因并返回非零状态。JSON 报告适合作为
发布证据，但不记录配置文件内容或秘密值。

编辑器、配置生成器和外部管理工具应使用 `contracts/schemas/runtime-config.schema.json`。
该 Schema 发布设备及 MQTT/ROS/UDP 索引配置的类型与范围；仓库中的
`configuration-contract` 会阻止必填项、全局数值范围和索引族与 C++ Validator 静默漂移。

发布包在 `bin/` 中同时携带 `pdr.py`、`pdr.ps1` 和 `pdr-config-check`。安装后的 CLI 会自动
把自身上级目录识别为默认 `--prefix`；现场验收不需要保留 PocoDDSRuntime 源码树。

2. 从安装目录 `bin/` 启动 `pdr-runtime`。启动时仍会执行同一个 C++ `ConfigurationValidator`，
   防止绕过离线检查。
3. 访问 `/health/live` 确认进程存活。
4. 访问 `/health/ready` 确认可接收业务；HTTP 503 表示降级或未就绪。
5. 访问 `/health/detail` 查看 Bundle 和子进程明细。
   Home WebUI 首页会聚合显示 LIVE、READY、组件明细和平台能力；黄色表示降级，需要展开健康详情定位。
6. 查看 `logs/pdr-runtime.log`，使用 traceId/requestId 关联业务记录。

## 安装包启动验收

发布前必须从一个新的安装前缀启动，不能只运行构建目录中的程序：

```powershell
python tools/runtime_smoke.py `
  --executable C:/deploy/PocoDDSRuntime/bin/pdr-runtime.exe `
  --working-directory C:/deploy/PocoDDSRuntime/bin `
  --path C:/deploy/PocoDDSRuntime/bin `
  --timeout 30 `
  --stability-window 2 `
  --endpoint /health/detail `
  --report build/reports/runtime-package-smoke.json
```

工具使用未占用的本机端口，依次要求 `/health/live` 和 `/health/ready` 返回 HTTP 200，并在成功或失败后终止 Runtime 及其子进程。JSON 报告和同名 `.log` 文件应作为发布证据保存。

交付验收时不得把构建目录、Qt SDK 或开发机依赖目录加入 `PATH`；否则无法证明包是自包含的。Edge/Test 安装规则会连同 Qt DLL、平台插件、渲染器和场景插件一起安装 Qt3D 子进程。

7. 停止时使用正常终止信号，等待子进程按配置超时退出。
# 长稳测试

长稳工具启动目标进程、定期采集 RSS 和句柄/文件描述符数量，并生成 JSON 趋势报告。
默认采集范围是 Runtime 及其全部后代进程，因此 Qt3D、渲染器和受管工具的资源增长也会计入阈值；
报告中的 `resourceScope=tree`、`processCount` 和 `peakProcessCount` 用于证明采样没有只覆盖父进程。
只有在明确诊断单个进程时才使用 `--resource-scope process`，这种报告不能替代发布长稳证据。
例如执行 24 小时 Runtime 长稳：

```powershell
python tools/soak_runner.py `
  --duration 86400 `
  --interval 30 `
  --warmup 10 `
  --max-rss-growth-mib 128 `
  --max-handle-growth 32 `
  --health-url http://127.0.0.1:9080/health/ready `
  --health-timeout 2 `
  --max-consecutive-health-failures 0 `
  --output build/reports/runtime-soak-24h.json `
  --cwd build/bin `
  -- ./pdr-runtime.exe
```

72 小时测试将 `--duration` 改为 `259200`。报告中的 `passed`、违规原因、首末资源差、
峰值和全部采样点必须与对应版本、配置及测试环境一起保存。主机长稳通过不能替代
PetaLinux 板端、真实设备和 HIL 长稳。

长稳工具在每个采样点（包括停止前最后一个样本）同时记录 HTTP 健康状态；任何连续健康失败超过阈值都会使报告失败。结束或异常时会清理整个进程树，避免 Runtime 的 Qt3D 等子进程污染后续轮次。

## 协议网关 24/72 小时恢复长稳

普通 `soak_runner.py` 证明 Runtime 持续存活和资源趋势；协议网关还应在同一进程内持续制造 MQTT/ROS 生命周期变化。以下命令运行约 24 小时：首次 MQTT 连接由测试 Broker 主动断开一次，此后 MQTT 和 ROS 每 5 分钟交替执行一次在线重启，共各 144 次。

```powershell
python tools/runtime_protocol_gateway_integration.py `
  --runtime-smoke tools/runtime_smoke.py `
  --executable build-verify/bin/pdr-runtime.exe `
  --working-directory build-verify/bin `
  --config config/pdr-runtime.properties `
  --install-bin build/install/bin `
  --cycles 144 `
  --cycle-action-delay 300 `
  --health-sample-interval 30 `
  --stability-window 30 `
  --max-rss-growth-mib 128 `
  --max-handle-growth 32 `
  --report build-verify/reports/runtime-protocol-gateway-soak-24h.json
```

工具会根据周期、动作间隔和最终观察窗口自动计算总超时；若显式传入 `--timeout`，小于所需时间会直接拒绝启动。72 小时将 `--cycles` 改为 `432`。通过条件包括：Runtime 全程可就绪、每次 POST 均成功、最终两个必需协议均为 `open=true`、MQTT 至少 `cycles + 2` 次连接、ROS 至少 `cycles + 1` 次连接、测试服务端无协议错误，以及 RSS/句柄增长不超过阈值。报告、Runtime 日志、版本号和测试机环境信息必须一起归档。

资源增长基线取 MQTT 和 ROS 各完成第一次受控重启之后，排除 HTTP/协议线程首次使用时的一次性惰性初始化；报告仍保留启动以来的全部样本，并用 `resourceBaselineStage` 明示实际判定起点。后续所有循环和最终稳定窗口都参与增长判定，不能通过提高阈值掩盖持续泄漏。

## 外部协议实例验收

连接真实 broker、rosbridge 或跨主机 UDP 对端后，使用 `tools/protocol_acceptance.py` 对每个必需实例分别采样。不要只检查最终在线；必须让业务工装持续制造双向流量，并按验收计划注入断连。工具会拒绝计数倒退、超限错误/超时、持续关闭、最终关闭或 `desiredOpen=false`。

生产 API 使用 HTTPS 时可配置 `--ca-file`；需要 mTLS 时再配置 `--client-certificate` 和 `--private-key`。Authorization 通过 `--authorization-environment` 指定环境变量名，受口令保护的私钥通过 `--private-key-password-environment` 指定环境变量名。命令行和报告都不应出现秘密值。完整命令见[验收矩阵](acceptance-matrix.md)。
