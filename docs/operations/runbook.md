# 运行手册

1. 从安装目录 `bin/` 启动 `pdr-runtime`。
2. 启动失败先检查配置校验错误；错误会列出具体 key 和范围。
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

长稳工具在每个采样点同时记录 HTTP 健康状态；任何连续健康失败超过阈值都会使报告失败。结束或异常时会清理整个进程树，避免 Runtime 的 Qt3D 等子进程污染后续轮次。
