# Runtime Schema Registry

`pdr.service.schemaRegistry` 为 Runtime 内的消息、事件、命令、配置和服务契约提供不可变、可追溯的 Schema 目录。它解决跨团队只约定 `messageType`/`schemaVersion` 字符串、却没有统一结构和兼容门禁的问题。

## 边界

| 组件 | 职责 |
| --- | --- |
| `PocoDDS::SchemaRegistryAPI` | 稳定 Schema、Provider 和 OSP Service 契约 |
| `PocoDDS::SchemaRegistryCore` | 规范化、SHA-256 指纹、兼容判断、并发注册和 SQLite 历史 |
| `pdr.service.schemaRegistry` | Provider 动态发现、内置 Topic 契约和 Runtime 服务注册 |
| `pdr-schema-check` | 构建/CI 基线与候选兼容门禁 |
| `pdr schema scaffold` | 在组件自己的目录生成初始 Schema，不修改中央组件清单 |

Schema Registry 不负责传输消息、不拥有业务字段，也不修改 `SystemMonitoring.cpp`。Transport 继续负责交付，业务 Bundle 继续拥有 Schema；Registry 只治理版本、身份、兼容性和持久化历史。

## Schema 信封

每个契约包含全局稳定的 `subject`、语义版本、类型、固定 Owner、格式、兼容策略、JSON Schema Draft 7 定义以及 Runtime 计算的规范化 SHA-256 指纹。

同一 `subject@version` 永远不可覆盖。相同指纹重复注册是幂等成功；不同指纹会被拒绝。Owner、Kind、Format 和兼容策略在一个 Subject 内不可静默切换。

## 兼容规则

| 模式 | 保证 |
| --- | --- |
| `backward` | 新 Reader 能读取旧 Writer 数据 |
| `forward` | 旧 Reader 能读取新 Writer 数据 |
| `full` | 同时满足 backward 与 forward |
| `none` | 只执行身份、版本、不可变性和持久化检查 |

同一主版本的破坏性修改会被拒绝。显式提升主版本后可以登记破坏性契约，兼容报告仍保留具体问题。当前检查器保守支持对象、数组、类型、必填字段、枚举、数值范围、字符串长度和布尔 `additionalProperties`；遇到 `$ref`、组合 Schema、条件 Schema 或 `patternProperties` 会失败关闭，避免给出未经证明的兼容结论。

## Provider 注册

业务 Bundle 实现 `SchemaProviderService`，Service 属性必须声明：

```text
pdr.schema.provider.kind = registry
pdr.schema.provider.id = my.bundle.id
```

`providerId()` 必须等于属性 ID，每个 Schema 的 `owner` 也必须等于该 ID。一个 Provider 发布的多个 Schema 使用单个 SQLite 事务注册：其中任意一项不兼容，整批不会落库。Bundle 卸载只移除 Provider 在线状态，已经登记的不可变历史仍保留。

## 开发和构建门禁

生成组件自有契约：

```powershell
python tools/pdr.py schema scaffold my.product.telemetry `
  --owner my.product.bundle --kind event --compatibility backward `
  --output components/Telemetry/schemas/telemetry.json
```

比较冻结基线和候选：

```powershell
build/bin/pdr-schema-check.exe `
  --baseline contracts/schema-registry/baselines/pdr.runtime.topic-contract/1.0.0.json `
  --candidate contracts/schema-registry/current/pdr.runtime.topic-contract.json
```

顶层构建目标 `pdr-schema-compatibility-gate` 会检查 `contracts/schema-registry/catalog.json`。新增已发布契约时，将冻结版本复制到 `baselines/<subject>/<version>.json`，日常修改只作用于 `current/` 候选；不要重写历史基线。

## 持久化与运行配置

默认数据库位于 Bundle 持久目录；也可显式设置：

```properties
# pdr.schemaRegistry.database = C:/ProgramData/PocoDDS/schema-registry/schemas.sqlite
```

SQLite 使用 WAL 和 `synchronous=FULL`。启动时重新解析全部记录并验证指纹；数据库损坏、未知数据库版本或不受支持的 Schema 关键字会让 Bundle 失败关闭。生产部署应为数据库和 WAL/SHM 文件设置仅 Runtime 身份可写的操作系统 ACL。

当前访问面是 OSP SDK Service，并未新增 HTTP/UI 写入口。若后续需要管理页面，应通过独立、鉴权的治理 API 读取摘要，不应把完整 Schema 写逻辑塞进监控 Bundle。

