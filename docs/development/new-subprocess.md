# 新增子进程

```powershell
./tools/pdr.ps1 new subprocess VisionWorker --output SubSystem
```

生成结果包含独立可执行文件、`--self-test`、标准 READY/HEARTBEAT/STOPPED 标记、文件式健康信号、有限恢复策略、安装规则和配置片段。

1. 可执行文件输出到统一 `build/bin/processes/<name>`。
2. 将生成的 `config/pdr-subprocess-entry.properties` 合并到部署配置，使用下一个连续编号；不要复制硬编码槽位。
   若该进程依赖另一个受管进程，设置 `dependency.count` 和 `dependency.M`；不要依赖槽位编号表达启动顺序。
3. 保留生成的 `--health-file` 参数，并在业务初始化完成后首次写入；不要在只获得 PID 时提前报告 Ready。
4. 实现正常终止、超时退出、重复启动保护和有界重启预算。启动 Readiness 与持续 Heartbeat 使用同一新鲜文件门禁，但业务依赖可用性仍应由进程自己的健康接口表达。
5. 接入结构化日志、健康状态和业务 Trace；心跳只证明进程仍能执行健康循环，不等于完整业务闭环成功。
6. 子进程通过 DDS、HTTP 或公开协议通信，不得访问主进程内的 OSP Service Registry。
7. `SubSystem/` 会自动发现新直接子目录；项目特有的启用开关应放在组件自己的 CMake 中。
8. 分别验证自检、`waiting-dependency → starting → running`、正常退出、Readiness 超时、心跳丢失、依赖丢失、崩溃重启、反向关闭、重启预算和安装包运行。
