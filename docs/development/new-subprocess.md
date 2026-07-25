# 新增子进程

1. 可执行文件输出到统一 `build/bin/processes/<name>`。
2. 在 `pdr-subprocesses.properties` 登记命令、参数和启动顺序。
3. 实现正常终止、超时退出和重复启动保护。
4. 接入心跳、健康状态、日志和业务 Trace。
5. 增加主子进程启动、崩溃、重启和关闭测试。
