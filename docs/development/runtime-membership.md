# Runtime 成员视图

`MembershipRuntime` 为同一 Fast DDS domain 中的多个 Runtime 实例提供有界、只读友好的在线成员视图。
它解决的是“有哪些 Runtime 最近仍在发心跳、某个实例是否以新进程代际重启”这一层问题，不提供
Leader Election、Quorum、分布式锁、配置复制或强一致写入。

## 边界与分层

| 层 | Owner | 职责 |
| --- | --- | --- |
| `PocoDDS::MembershipCore` | runtime-governance | 传输无关状态机、接收端 TTL、重放拒绝、墓碑和容量上限 |
| `PocoDDS::MembershipPersistence` | runtime-governance | SQLite 原子代际高水位，防止同一稳定 ID 在重启后复用 incarnation |
| `pdr.service.membershipRuntime` | governance-services | Fast DDS 心跳适配、OSP Service 注册、健康贡献者和优雅离线 |

团队可以分别修改状态机、DDS 适配和使用方。业务 Bundle 只能依赖安装后的
`PocoDDS::MembershipAPI`/`pdr.runtime-membership` 契约，不应包含服务的 `src/` 私有实现。

## 身份与时间规则

- `instanceId` 必须在同一 DDS domain 内唯一，并且跨重启稳定。默认值是
  `<nodeName>:runtime`；同一主机运行多个 Runtime 时必须显式配置不同 ID。
- 每次 Bundle 启动通过单条 SQLite 原子 UPSERT 分配严格递增 `incarnation`。两个进程并发使用
  同一数据库时也不会拿到重复代际。
- 每个代际的 `sequence` 严格递增；旧代际、倒退序号和重复心跳均不会刷新 TTL。
- 远端时间戳不参与存活判断。每个接收 Runtime 只使用自己的 `steady_clock`，因此系统时钟跳变
  或远端时钟漂移不会延长成员寿命。
- 优雅停止发送带最终序号的 `leave` 并保留墓碑。延迟到达的旧 heartbeat 不能立即复活成员；
  更高 incarnation 可以替换墓碑。

## 配置

```properties
pdr.fastdds.domainId = 0
# pdr.membership.instanceId = edge-a:runtime
pdr.membership.role = runtime
pdr.membership.endpoint =
pdr.membership.capabilities = health,service-registry
pdr.membership.topic = pdr.runtime.membership.v1
pdr.membership.heartbeatIntervalMilliseconds = 1000
pdr.membership.heartbeatTtlMilliseconds = 5000
pdr.membership.tombstoneRetentionMilliseconds = 30000
pdr.membership.maximumMembers = 1024
# pdr.membership.database = ${application.dir}data/membership/incarnations.sqlite
```

`heartbeatTtlMilliseconds` 必须至少是心跳间隔的两倍。容量达到上限时只允许驱逐已过期成员，
不会为了接收新身份而静默删除活跃成员。`capabilities` 只用于发现提示，不是授权声明；权限仍由
Capability Runtime 决定。

## 使用与验证

OSP Consumer 通过 `PocoDDS::Membership::MembershipRuntimeService` 获取 `snapshot()`。快照包含
generation、alive/expired 数量、成员代际/序号/接收年龄和拒绝统计。健康聚合器通过
`pdr.healthContributor.runtimeMembership` 检查本地成员和 DDS 发布状态；远端成员正常过期不会让
本 Runtime Readiness 自动失败。

```powershell
cmake --build build/profiles/server --config Release --target PDR_MembershipRuntime_Bundle
ctest --test-dir build/profiles/server -C Release -R "^membership-" --output-on-failure
```

核心测试使用可控单调时钟覆盖 TTL、墓碑、代际替换、序号重放和容量边界；持久化测试使用两个
独立 SQLite 连接并发分配代际。以上仍是本机核心/Bundle 验证，不等同于跨主机网络、防火墙、
DDS Discovery 或长稳验收。
