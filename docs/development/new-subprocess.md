# 新增子进程

```powershell
./tools/pdr.ps1 new subprocess VisionWorker --output SubSystem
```

生成结果包含独立可执行文件、`--self-test`、标准 READY/HEARTBEAT/STOPPED 标记、安装规则和配置片段。

1. 可执行文件输出到统一 `build/bin/processes/<name>`。
2. 将生成的 `config/pdr-subprocess-entry.properties` 合并到部署配置，使用下一个连续编号；不要复制硬编码槽位。
3. 实现正常终止、超时退出、重复启动保护和有界重启预算。
4. 接入结构化日志、健康状态和业务 Trace；心跳只证明进程活着，不等于业务就绪。
5. 子进程通过 DDS、HTTP 或公开协议通信，不得访问主进程内的 OSP Service Registry。
6. `SubSystem/` 会自动发现新直接子目录；项目特有的启用开关应放在组件自己的 CMake 中。
7. 分别验证自检、主进程拉起、正常退出、崩溃重启、重启预算和安装包运行。
