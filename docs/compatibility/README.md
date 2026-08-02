# 兼容矩阵

| 资产 | 当前版本 | 兼容规则 |
| --- | --- | --- |
| Runtime | 0.1.0 | 语义化版本 |
| HTTP API | 0.1.0 | OpenAPI 删除/收紧字段为不兼容 |
| Event Contract | 0.1.0 | AsyncAPI 地址或必填字段变化为不兼容 |
| Configuration Schema | 0.1.0 | 删除 key、改变类型或收紧范围为不兼容 |
| Database | 尚未统一 | 引入 Migration 后登记 |
| Firmware | 设备定义 | 必须由设备适配器报告 |

每次 Release 必须更新此表，并保存构建、测试和契约检查证据。

## 自动兼容性门禁

当前 `0.1.0` 兼容基线位于 `contracts/compatibility/0.1.0.json`。执行：

```powershell
python tools/check_compatibility.py
```

门禁检查已发布的 `PocoDDS::` CMake Target、公共 SDK 头文件和类型、配置属性
类型与范围、OpenAPI 方法和路径，以及 AsyncAPI Channel 名称和地址。

同一主版本允许增加可选配置、HTTP 操作、Channel 和公共类型。删除或改变既有契约
时检查会失败；必须提升 Runtime 主版本、提供迁移说明，并经过评审后建立新基线。
不能仅通过修改基线文件绕过不兼容变更。

## 升级、健康检查与回滚

`docs/compatibility/releases.json` 是发布兼容矩阵。升级工具默认只允许同一主版本升级；
跨主版本必须明确传入 `--allow-major-upgrade`，并先更新迁移说明和兼容矩阵。

部署前先使用交付包内的验证器严格核对解压目录：

```powershell
python C:/deploy/pdr-runtime/bin/release_manifest.py verify `
  --manifest C:/release/SHA256SUMS.json `
  --signature C:/release/SHA256SUMS.sig.json `
  --expected-key-id operations-2026-q3 `
  --public-key C:/trust/pdr-release-2026-q3.pub.pem `
  --expected-public-key-sha256 <审批记录中的公钥SHA-256> `
  --require-signature `
  --artifacts C:/release/pdr-runtime
```

停机前先执行只读预检；它不会创建锁、暂存目录或修改目标安装：

```powershell
python C:/deploy/pdr-runtime/bin/pdr.py upgrade preflight `
  --package C:/release/pdr-runtime `
  --manifest C:/release/SHA256SUMS.json `
  --signature C:/release/SHA256SUMS.sig.json `
  --expected-key-id operations-2026-q3 `
  --public-key C:/trust/pdr-release-2026-q3.pub.pem `
  --expected-public-key-sha256 <审批记录中的公钥SHA-256> `
  --trust-policy C:/trust/pdr-release-policy.json `
  --expected-trust-policy-id operations-2026-q3 `
  --expected-trust-policy-sha256 <审批记录中的策略SHA-256> `
  --target C:/deploy/pdr-runtime `
  --report C:/deploy/audit/upgrade-preflight.json
```

```powershell
python C:/deploy/pdr-runtime/bin/pdr.py upgrade apply `
  --package C:/release/pdr-runtime `
  --manifest C:/release/SHA256SUMS.json `
  --signature C:/release/SHA256SUMS.sig.json `
  --expected-key-id operations-2026-q3 `
  --public-key C:/trust/pdr-release-2026-q3.pub.pem `
  --expected-public-key-sha256 <审批记录中的公钥SHA-256> `
  --trust-policy C:/trust/pdr-release-policy.json `
  --expected-trust-policy-id operations-2026-q3 `
  --expected-trust-policy-sha256 <审批记录中的策略SHA-256> `
  --target C:/deploy/pdr-runtime `
  --audit C:/deploy/audit/upgrades.jsonl `
  --health-url https://127.0.0.1:9443/health/ready `
  --health-body-pattern '"ready":true' `
  --health-timeout 30
```

工具先验证清单中的每个 SHA-256，并拒绝清单外新增文件、重复条目和越出安装根目录的路径，
再复制到目标同盘的暂存目录并二次校验。旧目录先改名
为备份，暂存目录再原子改名为正式目录。升级器使用同目录独占锁和 fsync 后的事务日志；
并发升级会被拒绝。`data`、`logs`、`disabled-bundles` 随事务迁移，回滚时保留升级后
产生的最新状态；`codeCache` 不迁移，避免新旧 Bundle 缓存混用。健康检查是必需门禁，
可以选择文件哨兵、HTTP(S) 或无 shell 的验证命令。文件哨兵不得随安装包交付，必须由
激活后的服务产生；非本机 HTTP 探针必须使用 HTTPS。仅受控诊断可以显式使用
`--skip-health-check`。

默认还要求 Manifest 明确记录 `cleanRequired=true` 且 `dirty=false`。开发工作区生成的包只能
在隔离验证中显式添加 `--allow-development-release`，不得把该开关写入生产升级脚本。
生产预检和升级默认要求 `SHA256SUMS.sig.json`，推荐算法为 Ed25519。发布端通过
`--ed25519-private-key-environment` 指定保存私钥路径的环境变量；加密 PEM 的口令通过
`--private-key-passphrase-environment` 注入。目标端使用安装包内的原生
`pdr-signature-check` 和 OpenSSL 验签，不依赖 Python 密码库。验收同时固定 `keyId` 与公钥
SHA-256，二者必须与审批记录一致，以支持轮换、吊销并防止公钥文件被替换。
验证命令必须来自当前已信任的安装或独立 bootstrap，不得从尚未验签的新包中运行；工具会
拒绝使用位于待验包目录内的验签器。首次安装应由设备镜像预置 bootstrap 验签器及公钥摘要。
生产签名还必须由 `release-trust-policy.schema.json` 格式的策略授权。策略列出允许的
`keyId`、算法、公钥摘要、`notBefore`/`notAfter` 和吊销原因；策略文件不能来自待验包，且
其 `policyId` 与 SHA-256 必须由独立审批记录固定。已吊销、尚未生效或过期密钥一律在停机前
拒绝。`--allow-unmanaged-trust` 仅用于隔离诊断。
无签名包只能在隔离诊断中显式使用 `--allow-unsigned-release`。HMAC-SHA256 仍作为受限离线
兼容模式；其密钥必须是至少 32 字节随机值的 Base64，并且共享密钥不具备公钥签名的职责分离。
成功升级默认保留最近两份旧版本目录，可用 `--keep-backups N` 调整，但不得小于 1。
保留清理失败只写入 `backup_retention_failed` 审计，不会回滚已通过健康门禁的新版本。

健康失败会先恢复旧版本并复验旧目录 SHA-256。手动回滚：

```powershell
python C:/deploy/pdr-runtime/bin/pdr.py upgrade rollback `
  --target C:/deploy/pdr-runtime `
  --audit C:/deploy/audit/upgrades.jsonl
```

若主机在目录切换或健康检查期间掉电，保留事务文件和锁，不应手工删除。恢复命令按旧版本
完整性快照 fail-closed：不会把未经健康验收的新版本猜测为成功。

```powershell
python C:/deploy/pdr-runtime/bin/pdr.py upgrade recover `
  --target C:/deploy/pdr-runtime
```

审计日志使用 JSON Lines 并同步落盘，记录清单摘要、来源/目标版本、预检、暂存校验、
激活、健康检查、自动/人工回滚及中断恢复结果。审计路径必须位于可替换安装目录之外。
升级前必须停止仍占用 DLL/可执行文件的进程；板端 A/B 分区切换仍由具体设备适配器实现。
