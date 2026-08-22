# 性能预算

## RuntimeCore 进程内消息基线

通用模型使用 `pdr-runtime-core-inproc-performance` 对 Inline Executor、单订阅者、256 字节
Payload 执行 2000 次预热和 100000 次测量。开发/CI 默认预算为平均不超过 50 us、p99 不超过
200 us，并输出吞吐、最大延迟和完整预算。可按目标硬件覆盖：

```powershell
cmake --preset desktop-lite `
  -DPDR_RUNTIME_CORE_INPROC_AVERAGE_BUDGET_US=50 `
  -DPDR_RUNTIME_CORE_INPROC_P99_BUDGET_US=200
cmake --build --preset desktop-lite
ctest --preset desktop-lite -C Release -R runtime-core-inproc-performance-budget -V
```

该基线用于发现进程内分发性能回退，不代表 IPC、MQTT、Fast DDS、磁盘、网络或 UI 端到端
性能。跨边界 Adapter 必须按目标拓扑另设 Payload 大小、并发度、吞吐、p99/p999、丢包恢复和
资源占用预算。

## 机器人性能预算

“使用 C++”或“测试运行很快”不能证明框架高性能。机器人路径使用可重复的性能门禁记录热路径
平均延迟、p99、最大值和吞吐量，并明确它不是硬实时或真实机器人时序证明。

## 当前门禁

`pdr-robotics-performance` 对确定性 `InMemorySimulator` 下的 `RobotRuntime::step()` 预热后执行
5000次测量。默认开发/CI预算为：

| 指标 | 默认预算 |
| --- | ---: |
| 平均单步延迟 | 不超过 500 us |
| p99单步延迟 | 不超过 2000 us |

预算可在配置时覆盖：

```powershell
cmake --preset robotics `
  -DPDR_ROBOTICS_STEP_AVERAGE_BUDGET_US=500 `
  -DPDR_ROBOTICS_STEP_P99_BUDGET_US=2000
cmake --build --preset robotics
ctest --preset robotics -C Release -R robotics-performance-budget -V
```

结果包含 `PDR_ROBOTICS_PERFORMANCE_RESULT` 和明确预算；超出平均值或 p99预算会返回非零。

## 证据边界

该门禁用于发现代码回退，只证明当前主机、编译器和进程内模拟 Backend 的软件热路径。它不证明：

- 500 Hz–2 kHz电机控制环；
- ROS 2网络端到端延迟或特定 RMW QoS；
- CAN、EtherCAT、串口或厂商 SDK 时序；
- 操作系统调度抖动和最坏执行时间；
- HIL 或真实机器人性能。

产品必须另行制定 ROS 2 Command→Feedback、设备总线、动作调度、资源消耗、子进程恢复以及
24/72小时长稳预算。生产阈值应按目标硬件记录基线，不能直接沿用开发机数据。
