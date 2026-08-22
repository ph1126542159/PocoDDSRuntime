# 下一版本发布说明（未发布）

状态：**开发候选，尚未批准发布**。

当前 Windows Release 基线已完成多 Profile 构建、契约、安装消费者与 CTest 验证；精确结果以候选提交对应的 CI 和资格报告为准。这些证据仍只覆盖本地构建、工具和模拟运行路径。PetaLinux 目标、真实协议设备、生产身份、现场网络以及 24/72 小时长稳证据尚未全部签署，因此不得把本说明当作生产放行记录。

## 本轮变化

- 多模型框架：形成 `desktop-lite`、`desktop-distributed`、`embedded`、`edge-industrial`、`edge-test`、`server` 与 `robotics` Profile；构建清单明确 Host、Runtime、WebUI、能力和内置/外部 Transport，不再让普通桌面程序隐式依赖 ROS 2。
- RuntimeCore：新增稳定的 Host/Component、消息契约、`PDRM/1` 编解码、同步/有界异步 Executor、依赖排序与失败回滚、Transport Registry 和一致性测试边界。
- 传输适配：新增进程内、本机 IPC、MQTT 与 Fast DDS 的统一 `IMessageTransport` 实现；Windows Named Pipe、Linux Unix Domain Socket、MQTT Broker 和 Fast DDS Participant 均复用同一消息帧契约。
- 进程模型：`desktop-distributed` 新增 Native Process Supervisor；Windows 使用 Job Object，Linux 使用 Process Group，并提供根目录约束、依赖排序、优雅停止、进程树回收和有限重启预算。
- 工程化：新增安装后 Transport/IPC 消费者、架构与兼容面检查、跨平台 CI、部署模型文档和进程内性能预算；ROS 2 保持为机器人工作区的外部 Adapter，不伪装成通用底层通信。
- 通用开发：提供可安装 CMake package、公共 SDK、版本信息和插件脚手架；默认配置不主动连接物理设备或外部协议。
- 插件治理：增加 API/ABI 与依赖检查、发布者签名和信任策略、隔离宿主、资源边界、隔离部署以及事务回滚/恢复。
- 稳定性：管理任务、幂等请求、审计、告警历史和插件隔离状态可持久化；设备与协议具备重连、超时、退避、诊断和 readiness 联动。
- 安全：管理写操作支持共享身份、最小权限主体、环境变量或文件密钥及热轮换；升级包、插件、外部验收报告和证据包支持 Ed25519 验证。
- 运维：健康、指标、业务追踪、结构化故障、告警和 Web 诊断形成统一入口；新增可恢复发行流水线、资格判定、外部验收和离线证据包。
- 设备与协议：参考设备覆盖 Modbus、串口、GNSS、Linux sysfs GPIO/LED、XBee、CAN 和模拟设备；网关覆盖 MQTT、ROS bridge 和 UDP。

## 兼容性

- 当前项目版本仍为 `0.1.0`，兼容基线见 `contracts/compatibility/0.1.0.json`。
- 旧单实例设备键继续兼容；新部署应使用 `pdr.<family>.count` 和索引键。
- 旧的单一管理 token 仍作为全权限兼容主体；生产部署应迁移到显式 principals。
- 外部原生 OSP 插件仍是进程内代码；隔离宿主是推荐的新部署方式。

## 发布前剩余门禁

最终源码状态必须重新运行完整 Release 测试与资格判定，并完成 PetaLinux 目标、真实协议、生产身份、现场网络和 24/72 小时长稳验收。只有资格报告给出 `RELEASE_CANDIDATE_APPROVED` 才能进入生产发布审批。

迁移步骤见 [0.1.0 开发候选迁移指南](../migration/0.1.0-development.md)，运维命令见 [运行手册](../operations/runbook.md)。
