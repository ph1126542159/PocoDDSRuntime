# 框架故障注入与恢复矩阵

`contracts/framework-recovery-matrix.json` 把恢复能力从分散的测试名称提升为可审计的框架契约。每个场景必须明确组件、逻辑 Owner、Host/Runtime/Process/Bundle/Service/Transport/Persistence 作用域、故障注入方法、恢复策略、CTest 名称、必需标签、超时和可观察断言。

## 为什么需要矩阵

单个测试通过只能证明该测试执行成功，不能证明框架的关键层级都覆盖，也不能回答某个恢复场景由谁维护。矩阵解决以下多人协作问题：

- 场景 Owner 必须与 `framework-components.json` 的组件 Owner 一致，不能在文档中另造责任人。
- `requiredScopes` 中每个层级必须至少有一个场景，删除场景导致覆盖缺口时直接失败。
- 每个场景绑定唯一 CTest；测试未注册、标签不完整、超时、非零退出或缺少任一 PASS marker 都不能形成通过证据。
- v2 执行报告绑定矩阵、组件目录、选中 CTest 的命令/属性/测试程序摘要，以及 Profile `bin/` 和 CTest `PATH=path_list_prepend` 目录中的共享运行库集合摘要；源码重新构建、测试命令变化、工程 DLL/SO 或统一依赖前缀变化后，旧报告不能挪用。
- 每个断言同时记录机器可检查 marker 和工程不变量，避免只看一个笼统的 `PASS`。

## 当前 Server 基线

矩阵 v1 覆盖七个层级：

| 层级 | 代表故障 | 恢复门禁 |
|---|---|---|
| Host | 依赖中断、重复投递、队列压力 | 有界重试、去重、背压和确定性关闭 |
| Runtime | Owner 资源耗尽 | 隔离、排队/执行/排空超时和熔断 |
| Process | 子进程永久崩溃 | 滚动重启预算耗尽后 fail-closed |
| Bundle | 部署 Owner 崩溃 | 排他租约拒绝并发写，崩溃后释放租约 |
| Service | 配置参与者部分提交 | 两阶段预检、逆序回滚、恢复和幂等重放 |
| Transport | Modbus Peer 断线、MQTT Broker 非预期断线、Fast DDS Participant 重建 | 新会话重连、恢复订阅/Reader，并验证断线或重建前后的完整业务值 |
| Persistence | 维护操作中断 | 重开、恢复意图、完整性、备份和只读检查 |

当前矩阵包含七个必需层级和十二个场景，其中 Process 层分别验证外部 Launcher 的 Runtime 看护预算，以及 Runtime 内 `ProcessManagement` 对普通受管子进程的有限恢复、启动 Readiness、新鲜文件防伪、心跳丢失、显式依赖 DAG、依赖故障传播、循环检测、反向关闭及版本化依赖观察 API；两层不能互相替代。Transport 层同时验证 Modbus、MQTT 与 Fast DDS。MQTT 场景明确区分两层责任：Transport 观察连接丢失并保存订阅意图，上层协调器再次调用 `start()` 后建立新会话；它不宣称 Transport 内部存在隐藏的无限自动重连线程。Fast DDS 场景销毁并重建 Subscriber Participant/DataReader，保留原逻辑 Subscription 和持续运行的 Publisher；通过依赖 DDS discovery 恢复，不伪装成 Broker 式重连。

这些是本机构建中的故障注入/模拟协议/进程测试证据，不等同于真实机器人、真实现场总线、断电掉电、硬件看门狗或 24/72 小时长稳验收。真实设备与环境仍必须进入独立的 SIL/HIL/外部验收证据。

## 执行

静态契约检查：

```powershell
python tools/framework_recovery_matrix.py validate `
  --matrix contracts/framework-recovery-matrix.json `
  --catalog contracts/framework-components.json
```

Server Profile 的正式 CTest：

```powershell
ctest --test-dir build/profiles/server -C Release `
  -R "^framework-recovery-matrix-(contract|execution)$" `
  --output-on-failure
```

执行证据写入 `build/profiles/server/reports/framework-recovery-evidence.json`。报告中的每个 preflight 记录 CTest command 与命令文件集合摘要，根级记录所有已声明运行库搜索目录的 DLL/SO 数量和集合摘要；每个 result 包含退出码、超时状态、耗时、完整输出摘要和逐断言 marker 观察结果，失败时额外保留诊断尾部。共享运行库集合是保守绑定，可能包含场景未直接加载的 DLL/SO，但覆盖 Profile 与测试显式声明的动态依赖目录。

## 新增场景流程

1. 在目标组件中实现可重复、无外部破坏性的故障注入测试，并输出描述恢复不变量的稳定 marker。
2. 给 CTest 添加组件目录可选择的 label，以及 `fault-injection` 或 `recovery` label。
3. 按 ID 顺序新增矩阵项；Owner 必须取自组件目录，不能绕过所有权映射。
4. 先运行静态校验，再运行完整矩阵执行门禁；不能用手工构造 JSON 代替实际 CTest。
5. 若场景涉及真实设备、现场网络或长稳，把本矩阵结果作为自动化前置条件，而不是最终验收结论。
