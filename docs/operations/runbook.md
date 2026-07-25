# 运行手册

1. 从安装目录 `bin/` 启动 `pdr-runtime`。
2. 启动失败先检查配置校验错误；错误会列出具体 key 和范围。
3. 访问 `/health/live` 确认进程存活。
4. 访问 `/health/ready` 确认可接收业务；HTTP 503 表示降级或未就绪。
5. 访问 `/health/detail` 查看 Bundle 和子进程明细。
   Home WebUI 首页会聚合显示 LIVE、READY、组件明细和平台能力；黄色表示降级，需要展开健康详情定位。
6. 查看 `logs/pdr-runtime.log`，使用 traceId/requestId 关联业务记录。
7. 停止时使用正常终止信号，等待子进程按配置超时退出。
