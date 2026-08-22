# Runtime 诊断终端操作手册

## 目标与边界

诊断终端用于在不开放 PowerShell、cmd、bash、任意文件路径或任意网络请求的前提下，快速
定位 Host → Runtime → Process → Bundle → Service 运行链中的大多数软件故障。硬件断线、
线缆、供电、射频、外部网络设备和跨主机 DDS 发现仍需现场证据，终端只能给出软件侧证据与
下一步检查项。

## 首轮诊断

```text
status
health tree
diagnose all --deep
metrics anomalies
protocol check <id> --deep
device check <id> --deep
dds discovery
trace list
logs runtime --tail 100 --grep ERR
support collect
```

`diagnose all --deep --format json` 适合自动化解析。每条 Finding 包含稳定错误码、严重度、
scope、target、证据、修复建议与可选 Trace ID。

## 进程与崩溃

```text
ps
agent status <进程>
agent threads <进程>
agent net <进程>
crash list
dump process <进程> --confirm
crash show <dump-id>
```

Agent 是单独的 `pdr-diagnostic-agent` 进程，目标限制为当前 Runtime 或其托管子进程。Windows
可采集 MiniDump；Linux 默认只报告外部 coredump 策略边界，不尝试提权。

## 实时日志与支持包

```text
logs runtime --follow
logs <子进程> --tail 100 --grep timeout --follow
support collect
```

Ctrl+C 终止日志流。支持包写入 `data/diagnostics`，包含 Bundle/Service/进程/配置/指标/Trace/
深度诊断和最近日志；敏感配置值及包含凭据关键词的日志行会替换为 `[REDACTED]`。

## 受控修复

```text
repair protocol <id> reconnect --confirm
repair process <id> restart --confirm
repair bundle <id> restart --confirm
jobs
job show <task-id>
cancel <task-id> --confirm
```

修复命令只在 Web 终端中转现有治理 API，仍要求对应 manage/task 权限，并继承幂等、执行超时、
资源互斥、任务持久化与审计。先保存诊断证据，再执行最小范围修复；核心 Bundle 不允许在线
生命周期操作。

## 验收

至少验证：Bundle active、GET/POST API、SSE 新日志到达、Ctrl+C 取消、JSON schema、支持包
下载与脱敏、只读身份拒绝写命令、Agent status/threads/net、任务查询/取消，以及浏览器控制台
无错误。仅 C++ 编译成功或页面静态资源生成不等于 Runtime 验收通过。
