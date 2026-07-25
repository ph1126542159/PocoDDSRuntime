# 故障排查

- 配置错误：依据启动错误中的 key 修复，端口范围为 1–65535，DDS Domain 为 0–232。
- `/health/live` 失败：确认进程和 Web Bundle 是否运行、9080 是否监听。
- `/health/ready` 返回 503：读取 `/health/detail`，检查 Bundle 和子进程贡献者。
- DDS 无数据：确认 Domain ID 一致、Topic 与 `contracts/asyncapi/runtime.yaml` 一致。
- 子进程未启动：检查 `pdr-subprocesses.properties`、可执行文件路径和进程日志。
- Trace 缺失：检查 Observability 构建开关、历史目录权限和 OTLP endpoint。
