# PocoDDSRuntime 平台化开发计划

## 总体结论

当前 PocoDDSRuntime 已经具备不错的“运行时骨架”，包括 OSP Bundle、Fast DDS、设备/协议抽象、多进程管理、业务链路追踪、Web 管理界面和组件文档。

但要真正支撑以后更复杂的端测软件、后台服务和嵌入式程序，下一阶段不应继续横向堆协议或 UI，而应补齐“工程治理、契约、可靠性、安全、测试闭环”这五类平台能力。

## 当前已经具备的基础

从仓库现状看，以下能力可以继续保留并复用：

- `platform / services / SubSystem / server / webui` 的分层已经基本成立。
- OSP Bundle 提供本地插件、服务注册和生命周期管理。
- Fast DDS 承担跨进程、跨设备通信。
- Modbus、CAN、串口、MQTT、UDP、ROS Bridge 等协议已有抽象。
- Simulation、Linux、Modbus、CAN、GNSS 等设备实现已有基础。
- OpenTelemetry 已覆盖业务追踪、跨进程上下文传播和本地历史。
- 子进程启动、停止、重启和 Qt3D 多进程示例已经存在。
- 已有组件级中文文档体系，入口为 `docs/README.md`。
- 已有 Windows、Linux、PetaLinux 三类构建路径。

这意味着不需要推翻现有架构，也不建议重新引入一套大型微服务框架。

## 第一优先级：必须补齐

### 1. 统一应用层和业务流程模型

目前平台层、协议层和设备层比较清楚，但复杂业务容易直接写进 Bundle、Qt 界面或 DDS 回调中。建议增加明确的 `application/` 层：

```text
application/
├─ commands/       命令定义
├─ queries/        查询定义
├─ workflows/      业务流程编排
├─ statecharts/    状态机
├─ policies/       重试、超时、权限、互锁策略
└─ ports/          面向设备、存储、消息总线的抽象接口
```

需要形成以下约束：

- UI、REST、DDS 都只能调用 Application 用例。
- Application 不直接依赖 Qt、HTTP、Fast DDS 或具体串口设备。
- 设备回调只产生领域事件，不直接操作其他设备。
- 测试流程、后台任务、嵌入式控制逻辑统一采用“命令—状态—事件—结果”模型。

复杂端测软件尤其需要：

- 测试步骤定义；
- 前置条件和设备互锁；
- 超时、重试、取消；
- 补偿和安全复位；
- 断点续测；
- 测试结果与原始证据关联。

初期可以自行定义轻量 `WorkflowEngine` 接口；确定性单进程状态机可考虑 Boost.SML。不要一开始就把 Temporal 这类后台工作流平台塞进嵌入式运行时。

### 2. 建立统一通信契约

DDS Topic 名称已经存在，但还需要把以下内容变成正式契约：

- Topic、请求、响应、事件的 IDL；
- 字段含义、单位、有效范围和默认值；
- 消息版本和兼容规则；
- 错误码；
- 超时、幂等、重试语义；
- QoS Profile；
- trace ID、request ID、device ID 等公共元数据。

建议采用：

- Fast DDS IDL：DDS 数据契约唯一来源；
- OpenAPI 3.1：REST API 文档和客户端生成；
- AsyncAPI：DDS/MQTT/事件主题文档；
- JSON Schema：配置文件及动态业务参数校验；
- CMake 中增加契约兼容性检查。

不要让 C++ 结构体、Web JSON 和文档分别手工维护三份定义。

### 3. 配置中心与配置校验

当前 `config/pdr-runtime.properties` 已有较多配置，但还是“字符串配置集合”。建议补充：

- 配置项类型、范围、枚举和必填校验；
- 启动时 fail-fast；
- 配置版本；
- 默认配置、现场配置、设备配置分层；
- 敏感配置与普通配置分离；
- 配置变更审计；
- 支持仅对明确标记的配置进行热更新；
- WebUI 修改前预校验；
- 配置导入、导出和差异比较。

嵌入式版本建议继续使用本地文件，不必引入 Consul；后台集群版以后再通过 `IConfigurationProvider` 接入 Consul、etcd 或 Kubernetes ConfigMap。

### 4. 可靠性公共库

建议新建 `platform/reliability`，统一实现：

- Deadline/Timeout；
- 有上限的指数退避；
- Circuit Breaker；
- Bulkhead/并发隔离；
- 幂等键和重复请求检测；
- 有界队列与背压；
- 心跳和租约；
- Graceful Shutdown；
- 故障分类：临时、永久、配置、硬件、安全；
- 设备断线重连策略；
- 危险操作的安全复位。

这些能力不能散落在每个 Modbus、DDS、设备驱动和业务 Bundle 中。

### 5. 健康检查和运行状态模型

当前已经有进程状态和日志，但还需要统一：

- `/health/live`：进程是否存活；
- `/health/ready`：是否可以接收业务；
- `/health/detail`：DDS、数据库、设备、Bundle、子进程状态；
- 启动阶段状态；
- 降级状态；
- 最近故障及恢复时间；
- 设备通信质量、丢包、超时和重连次数。

每个组件实现统一的 `IHealthContributor`，由运行时聚合。这样后台部署、现场诊断和嵌入式维护可以共用一套状态语义。

## 第二优先级：平台成熟度建设

### 6. 补齐指标和结构化日志

现在业务 Trace 已经比较强，下一步应补 Metrics：

- Prometheus/OpenTelemetry Metrics；
- DDS 发布、订阅、丢包和延迟；
- 协议请求成功率和 P95/P99 延迟；
- 设备在线率；
- 工作流成功率；
- 队列深度；
- Bundle 和子进程重启次数；
- CPU、内存、磁盘和线程数。

日志应统一包含：

```text
timestamp
level
module
processId
deviceId
traceId
spanId
requestId
errorCode
```

最终形成 Logs + Metrics + Traces 三支柱，而不仅是业务 Trace。

### 7. 数据持久化和迁移框架

已有 SQLite 业务历史，但应建立通用持久化边界：

- `IRepository`/`IUnitOfWork`；
- SQLite 适配器；
- 后台版 PostgreSQL 适配器；
- Schema Migration；
- 数据保留和归档策略；
- 写入失败降级；
- 数据库损坏检测和恢复；
- 导出、导入与升级兼容性测试。

不要让各 Bundle 自行创建无版本的数据表。

### 8. 安全基线

仓库当前文档已明确 SimpleAuth 使用兼容性的 MD5 方案，不适合作为远程生产安全边界。因此需要：

- 禁止生产环境默认账号密码；
- Argon2id 或接入 OIDC/OAuth2；
- RBAC：查看、操作、配置、升级、管理员；
- TLS/反向代理；
- DDS Security：身份、访问控制、加密；
- 设备证书和设备身份；
- Secret Provider，不把密钥写入 properties；
- 登录、配置、升级、启停设备的审计日志；
- API 限流和请求体大小限制；
- 发布物漏洞扫描和 SBOM。

端测软件可采用本地账户；后台系统适合接入 Keycloak/企业 OIDC；嵌入式采用设备证书和最小权限接口。三者共享认证接口，不强行共享同一个重量级实现。

### 9. 版本、升级和回滚

建议建立统一制品模型：

- Runtime 版本；
- Bundle 版本；
- 配置 Schema 版本；
- DDS/API 契约版本；
- 固件版本；
- 数据库版本；
- 兼容矩阵。

补充：

- CPack 安装包；
- Bundle 签名和哈希；
- 升级前检查；
- 原子替换；
- 失败自动回滚；
- A/B 或双分区接口；
- 升级审计；
- 升级后健康检查。

框架只负责升级编排和验证，具体嵌入式板卡的 bootloader、分区切换由设备适配器完成。

## 第三优先级：测试与文档工程化

### 10. 建设分层测试体系

目前不少组件已有 smoke test，但还需要形成明确金字塔：

- 单元测试：Application、协议解析、状态机；
- 契约测试：IDL、OpenAPI、错误码兼容；
- 组件测试：单个 Bundle；
- 进程集成测试：DDS、子进程、SQLite；
- 故障注入：断网、超时、重复包、进程崩溃；
- 仿真测试：虚拟设备和回放数据；
- HIL：真实串口、CAN、Modbus、板卡；
- 长稳测试：24/72 小时；
- 性能基线；
- 模糊测试：协议帧和 JSON 输入；
- 安全测试。

端测软件还应建立“测试方案即数据”：

```yaml
id: board-power-cycle
version: 1
steps:
  - command: power.on
  - waitUntil: voltage.stable
    timeout: 5s
  - command: firmware.query
  - assert: firmware.version >= 2.1
  - finally: power.safeOff
```

这样相同测试流程可以由 Qt、WebUI、CLI 和 CI 共同执行。

### 11. 修复并升级 CI/CD

当前 `.github/workflows/ci.yml` 看起来仍包含旧目录和旧安装前缀，例如：

- `include services server tests platform demos`；
- `build/dependencies/install`；
- 旧的 acceptance 脚本/目标名称。

它与当前统一的 `build/install` 和迁移后目录可能存在漂移，应优先做一次 CI 实际审计。之后建议形成：

- Windows/Linux 主机构建；
- PetaLinux 交叉编译；
- Debug/Release；
- ASan/UBSan/TSan；
- clang-tidy；
- 格式检查；
- 文档链接和配置键检查；
- SDK 外部消费者测试；
- 契约兼容检查；
- SBOM 和漏洞扫描；
- Release 制品、哈希和签名。

### 12. 文档即代码

现有组件文档是很好的基础，下一步要补“治理文档”：

```text
docs/
├─ architecture/
│  ├─ overview.md
│  ├─ layering-rules.md
│  └─ deployment-profiles.md
├─ adr/
├─ contracts/
├─ operations/
│  ├─ runbook.md
│  ├─ troubleshooting.md
│  └─ recovery.md
├─ development/
│  ├─ new-service.md
│  ├─ new-device.md
│  ├─ new-protocol.md
│  └─ new-subprocess.md
└─ compatibility/
```

建议集成：

- Doxygen：C++ 公共接口；
- MkDocs Material：统一文档站；
- PlantUML/Mermaid：架构和时序图；
- ADR：记录关键架构决策；
- OpenAPI/AsyncAPI 自动生成接口文档；
- CI 检查失效链接、遗漏配置项和未记录公共接口。

## 建议定义三种部署 Profile

不要试图让所有目标都携带完整功能：

| Profile | 主要场景 | 建议能力 |
| --- | --- | --- |
| Embedded | PetaLinux/嵌入式设备 | Core、协议、设备、DDS、轻量日志、健康检查 |
| Edge/Test | Qt 端测、现场上位机 | Embedded + 工作流、SQLite、WebUI、完整追踪 |
| Server | 后台服务 | Edge + PostgreSQL、OIDC、集群部署、集中指标 |

通过 CMake Preset 和 Feature Flag 控制，而不是在业务代码里大量使用平台宏。

## 不建议现在直接集成

暂时不建议直接引入：

- Kubernetes 作为框架内部依赖；
- Kafka 替换所有 DDS 通信；
- Temporal 运行在端测和嵌入式进程内；
- 第二套 C++ 插件框架；
- Conan、vcpkg 与现有 superbuild 同时管理同一批依赖；
- 为了“微服务化”把每个 Bundle 都拆成独立进程；
- 业务代码直接依赖 Prometheus、PostgreSQL、Qt 或 Fast DDS SDK。

这些可以通过适配器扩展，但不应破坏当前 OSP + Fast DDS 的核心路线。

## 推荐实施顺序

建议按以下顺序推进：

1. 清理并验证 CI，建立可信基线。
2. 增加 `application/`、Workflow、Command、Result、Error 公共模型。
3. 建立 IDL/OpenAPI/JSON Schema 契约体系。
4. 增加配置校验、健康检查和可靠性公共库。
5. 补 OpenTelemetry Metrics 与结构化日志。
6. 建立数据库迁移、审计和安全基线。
7. 建立设备仿真、故障注入和 HIL 测试框架。
8. 最后再做 OTA、后台集群适配和高级工作流。

其中前四项最关键。完成后，PocoDDSRuntime 才会从“功能丰富的运行时工程”进一步变成“可以稳定派生多个产品的软件平台”。
