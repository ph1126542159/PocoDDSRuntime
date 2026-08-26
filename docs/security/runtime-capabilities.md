# Runtime Bundle 能力权限

## 目标与边界

`pdr.service.capabilityRuntime` 为 Runtime 内的 Bundle/组件提供统一的资源能力判定。策略与组件
声明分离，默认效果固定为 `deny`；组件可以描述自己需要什么能力，但不能给自己授权。策略文件
由部署方维护，默认位置为 `${application.dir}config/pdr-capability-policy.json`。

这是一层可审计的框架治理，不是操作系统沙箱。同一进程中的原生 C++ Bundle 若直接取得原始
OSP Service、原始 Transport 或设备对象，仍可能绕过受控外观。需要运行不可信插件时，应使用
独立 `pdr-plugin-host`/子进程、操作系统账户和 IPC 门禁；不能把同进程能力判定宣称为任意代码
隔离。

## 主体、资源和动作

主体使用稳定的 Bundle/服务身份，例如 `pdr.runtime-core`、`operator` 或
`vendor.component.instance`。资源模式只支持精确值、单独的 `*`，或一个尾部 `*` 前缀；不支持
中间通配符和正则表达式。

| 资源类型 | 合法动作 | 当前框架执行点 |
|---|---|---|
| `service` | `discover`, `use` | 能力策略自身换代；供受控 Service 外观复用 |
| `topic` | `publish`, `subscribe` | `AuthorizedTransport` |
| `configuration` | `read`, `write` | `TransactionEngine` 写事务授权 Hook |
| `device` | `observe`, `operate` | API 已预留；设备必须通过后续受控外观接入 |
| `schema` | `read`, `register`, `deprecate` | Schema Registry 动态注册和废弃 |

匹配规则中，任意显式 `deny` 都优先于 `allow`；没有 allow 时返回
`CAPABILITY_DEFAULT_DENY`。判定结果包含策略 generation、SHA-256 摘要、命中规则 ID 和解释，
同时进入有界内存审计和 SQLite 持久审计。SQLite 使用 WAL、`synchronous=FULL` 和有界保留；
审计写入失败会让授权调用抛出异常，因此受控入口不会在“允许但未留下审计”的状态下继续执行。
普通 `decide`/`require` 每次都判定并审计；高频受控路径可显式使用
`decideLeased`/`requireLeased` 或把 `DecisionLeaseAuthorizer` 交给 `AuthorizedTransport`。

## Decision Lease

Decision Lease 只复用已经审计成功的 `allow`，拒绝结果永不缓存。租约键完整包含 Principal、资源类型、
资源和动作，并同时受以下边界限制：

- 策略 generation 变化时，在下一次操作前清空旧 generation 的全部租约；跨换代发放时最多重试三次，
  无法取得稳定 generation 就 fail-closed。
- 每个租约同时受 TTL 和最大使用次数约束，任一耗尽都会重新执行策略判定并写持久审计。
- 持久化存储进入 `recoveryRequired` 时，已有缓存也不能继续授权。
- 容量有界并按最久未访问项淘汰；`leases()` 提供 hit、miss、issued、denied、expired、
  invalidated 和 evicted 统计，不依赖 SystemMonitoring 实现。

租约命中代表复用一次已经审计的短期授权，不会为每条消息生成独立 SQLite 行。需要逐操作审计的
管理、配置、Schema 或设备控制路径应继续使用普通 `decide`/`require`；租约主要面向高频 Topic
publish/subscribe 门禁。

| 配置 | 默认值 | 硬边界 |
|---|---:|---:|
| `pdr.capabilityRuntime.leaseEnabled` | `true` | 可显式关闭并退化为逐次判定 |
| `pdr.capabilityRuntime.leaseDurationMilliseconds` | `250` | `1..60000` |
| `pdr.capabilityRuntime.leaseMaximumUses` | `1024` | `1..1000000` |
| `pdr.capabilityRuntime.leaseCapacity` | `4096` | `1..1000000` |

## 策略示例

```json
{
  "$schema": "../schemas/runtime-capability-policy.schema.json",
  "version": 1,
  "defaultEffect": "deny",
  "rules": [
    {
      "id": "sensor-publish",
      "effect": "allow",
      "principal": "vendor.sensor.*",
      "resourceKind": "topic",
      "resource": "telemetry.*",
      "actions": ["publish"]
    }
  ]
}
```

运行构建门禁或解释单次决策：

```powershell
./build/bin/pdr-capability-check.exe `
  --policy contracts/capabilities/default-policy.json --validate

python tools/pdr.py capability check `
  --policy contracts/capabilities/default-policy.json `
  --principal vendor.sensor.one --resource-kind topic `
  --resource telemetry.temperature --action publish

python tools/pdr.py capability store-check `
  --database build/bin/data/pdr.service.capabilityRuntime/var/capabilities.sqlite `
  --seed-policy contracts/capabilities/default-policy.json

python tools/pdr.py capability store-apply `
  --database build/bin/data/pdr.service.capabilityRuntime/var/capabilities.sqlite `
  --seed-policy contracts/capabilities/default-policy.json `
  --candidate-policy capability-policy.json --actor operator `
  --request-id change-2026-08-24-01 --expected-generation 1
```

多人开发时，每个组件可在自己的目录生成独立策略草案，交由部署负责人评审合并，无需编辑
中心源码注册表：

```powershell
python tools/pdr.py capability scaffold `
  --rule-id sensor-publish --principal vendor.sensor.one `
  --resource-kind topic --resource telemetry.temperature --action publish `
  --output capability-policy.json
```

## 独立在线管理面

`pdr.service.capabilityManagement` 独立拥有 `/api/v1/capabilities`，不依赖
`SystemMonitoring.cpp`。接口使用 `pdr.identity.management` 验证 Bearer token；写请求中的 actor
只能由服务端使用认证 Principal ID 生成，客户端提交 `actor` 会直接返回 400。即使全局管理认证在
开发配置中可选，在线策略校验和换代仍禁止匿名调用。

| 接口 | 权限 | 行为 |
|---|---|---|
| `GET /api/v1/capabilities` | `capability.read` 或 `capability.manage` | 策略、持久化和租约状态，不返回数据库路径 |
| `GET /api/v1/capabilities/audit?limit=100` | `capability.read` 或 `capability.manage` | 最近的持久授权审计 |
| `POST /api/v1/capabilities/validate` | `capability.manage` | 严格校验完整策略并返回 digest，不修改状态 |
| `POST /api/v1/capabilities/policy` | `capability.manage` | generation CAS + 跨重启幂等换代 |

换代还必须通过当前 capability policy 中 actor 对
`service:pdr.service.capabilityRuntime:use` 的二次授权。也就是说，仅配置管理权限不能绕过当前策略，
仅在策略中自授权也不能绕过 Bearer 身份。请求体上限为 1 MiB，每个 Principal 每分钟最多 30 个
校验/换代请求。

```powershell
$headers = @{
  Authorization = "Bearer $env:PDR_CAPABILITY_OPERATOR_TOKEN"
  "X-PDR-Request-Id" = "change-2026-08-24-02"
}
$body = @{
  expectedGeneration = 2
  policy = Get-Content ./reviewed-policy.json -Raw | ConvertFrom-Json
} | ConvertTo-Json -Depth 20
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:9080/api/v1/capabilities/policy `
  -Headers $headers -ContentType application/json -Body $body
```

相同 Principal、request ID、expected generation 和候选策略重试会返回
`idempotentReplay=true`；跨 Principal 复用、同 ID 改内容或 generation 过期返回 409。

## 配置与 Schema 事务

配置 `ApplyRequest` 必须携带经过上层身份适配器确认的 `principal`。事务引擎在写入日志、执行
Participant preflight 或创建事务记录之前，按每个 `changedKey` 检查 `configuration:write`；
幂等重放也重新授权，不能借用另一个 Principal 的 request ID 绕过策略。

Schema Provider 的 `providerId` 同时作为注册 Principal，且 Schema `owner` 必须等于该 ID。
Provider 批量注册前会先检查每个 subject 的 `schema:register`，任一拒绝都会阻止整个批次进入
Registry。内置 Runtime Schema 在可信启动路径中初始化，不经过动态 Provider 门禁。

策略换代要求 `requestId`、`actor` 和 `expectedGeneration`。SQLite 事务先同时提交新策略快照和
幂等记录，随后才把同一 generation 安装到进程内不可变快照；重复的相同请求可跨重启返回原结果，
不同输入复用 request ID 或 generation 过期都会失败。

策略文件只在数据库第一次创建时作为 seed。之后 SQLite generation 是权威来源；文件摘要变化只
报告 `sourceDrift=true`，不会在启动时静默覆盖已生效策略。数据库在启动时执行完整性检查，并重新
计算规范化策略文档的 SHA-256；失败时 Capability Bundle 不注册 Service，依赖它的配置和 Schema
写入口也无法启动。不能通过删除数据库“修复”生产故障，因为这会回退到 seed 并丢失换代/审计证据。
数据库一旦进入 `recoveryRequired`，即使底层 I/O 暂时恢复也会保持 fail-closed，必须通过显式完整性
验证后才能重新使用。Runtime 和离线工具都持有同一个操作系统级独占租约；运行期间执行
`store-check`/`store-apply` 会被拒绝，残留的 `.lock` 文件本身不代表租约仍被占用。
远程管理仍必须增加认证 Principal 到 actor 的不可伪造映射，不能直接向普通 Bundle 暴露管理写入口。
