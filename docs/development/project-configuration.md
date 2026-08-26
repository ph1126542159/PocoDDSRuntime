# 产品配置治理

产品配置由 `pdr-project.yaml` 的 `config.version`、`config.layers` 和
`config.migrations` 定义。默认优先级为 `base < robot < site`；每层文件名按字典序合并，
后层只能用相同类型覆盖前层，不能把整数悄悄改成字符串或把对象改成标量。

每个 JSON 或 JSON 兼容 YAML 文件使用相同信封：

```json
{
  "version": 1,
  "values": {
    "network": {"port": 9080},
    "auth": {"token": {"$env": "WAREHOUSE_AUTH_TOKEN"}}
  }
}
```

名称含 `password`、`secret`、`token` 或 `privateKey` 的值禁止内联，必须使用唯一的
`{"$env":"NAME"}` 引用。解析报告只记录环境变量名称和是否缺失，不读取或输出秘密值。
生产门禁应加 `--require-environment`，缺少变量时立即失败：

```powershell
./tools/pdr.ps1 project config resolve pdr-project.yaml `
  --output build/resolved-config.json --require-environment
```

## 声明式迁移

升级配置时在 `config/migrations/` 中依次提供 `v1-to-v2.json`、`v2-to-v3.json`。每一步
必须连续，只允许 `rename`、`remove` 和 `set-default` 三种可审计操作：

```json
{
  "from": 1,
  "to": 2,
  "operations": [
    {"op": "rename", "from": "robot.controlPeriodMs", "path": "robot.control_period_ms"},
    {"op": "set-default", "path": "robot.watchdog.enabled", "value": true}
  ]
}
```

```powershell
./tools/pdr.ps1 project config resolve pdr-project.yaml `
  --target-version 2 --output build/resolved-v2.json
```

输出记录每层和每个迁移文件的 SHA-256、最终值摘要、源版本和目标版本。解析成功只证明候选
配置合法，不能等同于服务已安全热切换。

产品迁移还必须和提供键的 Bundle 生命周期契约交叉校验。将迁移文件传给
`pdr component key-lifecycle-test` 或 SDK CMake 的 `MIGRATIONS` 参数后，每个 `rename/remove` 都必须
匹配 `bundle/configuration-key-lifecycle.json` 中同一个 source/replacement/operation，且两端键仍由
该 Bundle 的 Participant 前缀拥有。`set-default` 不删除旧表面，不要求弃用记录。该门禁证明迁移
获得了正确团队授权，但不会代替下方的审批、在线预检或事务回滚。

## 组件能力与配置所有权

`pdr-project.yaml` 的 `config.capabilities` 指向能力清单。新项目默认生成空清单，组件只有在
实现事务协议后才能登记为 `hot-reload`，禁止用一个“万能回调”绕过所有权边界：

```json
{
  "schemaVersion": 1,
  "participants": [
    {
      "id": "motion-control",
      "ownedPaths": ["/robot/control"],
      "mode": "hot-reload",
      "after": [],
      "timeoutSeconds": 5,
      "command": ["bin/motion-config-agent", "--stdio"]
    },
    {
      "id": "mission-service",
      "ownedPaths": ["/mission"],
      "mode": "restart",
      "after": ["motion-control"],
      "timeoutSeconds": 30,
      "command": ["bin/mission-config-agent", "--stdio"]
    },
    {
      "id": "safety-boundary",
      "ownedPaths": ["/robot/safety"],
      "mode": "immutable"
    }
  ]
}
```

所有权使用 RFC 6901 JSON Pointer。不同参与者不能声明重叠前缀；变更路径无人认领或触碰
`immutable` 区域时，计划阶段直接拒绝。`restart` 变更必须在应用时显式传入
`--allow-restart`，其命令负责受控停止、加载和恢复，不能伪装成热更新。

## 高风险路径多人审批

项目可在 `config.approvalPolicy` 引用配置审批策略。规则使用 JSON Pointer 前缀匹配变更，分别
声明 `minimumApprovals`、`requiredRoles` 和 `separateInitiator`；同一路径命中多条规则时必须
全部满足。未命中规则的低风险变更仍按普通事务执行。安装包提供
`project-config-approval-policy.example.json`，其中全零公钥摘要会保持 fail-closed，必须替换。

先生成短期请求，再由不同角色分别签署：

```powershell
./tools/pdr.ps1 project config approval-request pdr-project.yaml `
  --plan build/config-plan.json --ticket CHANGE-42 --initiator deploy-operator `
  --expires-in-seconds 1800 --output build/config-approval.json

$env:PDR_CONFIG_APPROVER_KEY = '<secure>\safety-officer.pem'
./tools/pdr.ps1 project config approve `
  --request build/config-approval.json --approver-id safety-officer `
  --key-id safety-officer-2026 `
  --private-key-path-environment PDR_CONFIG_APPROVER_KEY `
  --signature-output build/safety-approval.signature.json
```

`apply` 对每个 `--approval-signature` 使用安装侧 `pdr-signature-check` 重新验签，并要求：请求未
过期、计划和策略摘要完全一致、审批人/密钥不重复、密钥未吊销、人数与角色分别满足、需要时
发起人不能自批。生产流水线必须从受保护配置提供预期策略 ID/SHA-256；可信公钥目录和验签器
必须位于产品项目之外。验证结果只把工单、发起人、角色、密钥和证据摘要写入 journal，不写私钥。
生产流水线还应固定传入 `--require-approval-policy`；这样即使有人删除 Manifest 中的策略引用并
重新生成计划，也会因缺少受信策略而拒绝，不能把高风险变更伪装成普通变更。

## 预检、提交与逆序回滚

先保存当前解析配置，再生成候选配置和摘要绑定计划：

```powershell
./tools/pdr.ps1 project config plan pdr-project.yaml `
  --current build/active-config.json `
  --candidate build/candidate-config.json `
  --output build/config-plan.json

./tools/pdr.ps1 project config preflight pdr-project.yaml `
  --plan build/config-plan.json `
  --current build/active-config.json `
  --candidate build/candidate-config.json `
  --output build/config-preflight.json

./tools/pdr.ps1 project config apply pdr-project.yaml `
  --plan build/config-plan.json `
  --current build/active-config.json `
  --candidate build/candidate-config.json `
  --actor deploy-operator `
  --preflight-evidence build/config-preflight.json `
  --require-approval-policy `
  --approval-request build/config-approval.json `
  --approval-policy config/approval-policy.json `
  --expected-approval-policy-id production-config-v1 `
  --expected-approval-policy-sha256 '<pinned-policy-sha256>' `
  --approval-trusted-keys-directory '<trusted>\config-approvers' `
  --approval-signature build/safety-approval.signature.json `
  --approval-signature build/operations-approval.signature.json `
  --signature-check-executable '<runtime>\bin\pdr-signature-check.exe'
```

执行顺序由 `after` 拓扑排序决定。框架通过 `shell=False` 启动命令，并在 stdin 发送
`pdr-config-transaction/1` JSON 请求；请求只包含事务 ID、阶段、参与者、变更路径和配置文件
路径，不传递秘密值。组件 stdout 必须只返回以下信封：

```json
{
  "schemaVersion": 1,
  "transactionId": "与请求一致的 UUID",
  "participant": "motion-control",
  "status": "ready"
}
```

`preflight`、`commit`、`rollback` 阶段分别返回 `ready`、`committed`、`rolled-back`。
独立 `preflight` 会真实调用全部受影响参与者，但不会调用 `commit`、替换活动配置或创建提交
journal。证据绑定 Manifest、能力清单、计划、当前/候选配置和参与者结果，并带自校验
`evidenceSha256`；`apply --preflight-evidence` 会拒绝被修改或已经漂移的证据，同时为防止预检后
环境变化仍会再次执行预检。

所有参与者预检成功后才开始提交；提交调用前先记录 `commitAttempted`，所以进程即使在组件
响应前中断，也会在恢复时对该参与者执行幂等回滚。任一提交失败时按逆序回滚所有已尝试
参与者，全部回滚成功后才恢复旧配置快照。

事务日志位于 `build/config-transactions/`。中断后使用：

```powershell
./tools/pdr.ps1 project config status pdr-project.yaml `
  --state-dir build/config-transactions --check `
  --report build/config-transaction-status.json

./tools/pdr.ps1 project config recover pdr-project.yaml `
  --journal build/config-transactions/<transaction-id>.journal.json `
  --actor recovery-operator

./tools/pdr.ps1 project config verify-audit `
  --state-dir build/config-transactions `
  --report build/config-audit-verification.json

# 由独立审计身份生成签名锚；私钥、输出目录均须位于事务状态目录之外
$env:PDR_CONFIG_AUDIT_CHECKPOINT_KEY = '<protected>\config-audit-anchor-private.pem'
./tools/pdr.ps1 project config audit-checkpoint `
  --state-dir build/config-transactions --actor audit-anchor-service `
  --key-id config-audit-anchor-2026 `
  --private-key-path-environment PDR_CONFIG_AUDIT_CHECKPOINT_KEY `
  --output '<external>\checkpoint.json' `
  --signature-output '<external>\checkpoint.signature.json'

./tools/pdr.ps1 project config verify-audit-checkpoint `
  --checkpoint '<external>\checkpoint.json' `
  --signature '<external>\checkpoint.signature.json' `
  --public-key '<trusted>\config-audit-anchor-public.pem' `
  --expected-key-id config-audit-anchor-2026 `
  --expected-public-key-sha256 '<pinned-public-key-sha256>' `
  --signature-check-executable '<install>\bin\pdr-signature-check.exe' `
  --state-dir build/config-transactions --expected-min-sequence 1 `
  --report build/config-audit-checkpoint-verification.json
```

`status` 是无副作用的协作交接入口：同时报告活动/陈旧锁、事务 ID、发起人、终态数量、精确的
待恢复 journal 和审计链健康。`--check` 只在 `canApply=true` 时返回 0；活动事务、待恢复事务、
损坏 journal/锁或无效审计都会阻止流水线进入下一次 apply。陈旧锁会被标为 warning，下一次受控
事务操作仍会按现有锁协议清理它。新锁同时绑定 PID 和进程创建身份，避免崩溃后 PID 被复用时把
旧锁长期误判成仍在运行；无法取得创建身份时保持 fail-safe，不主动清除可能有效的锁。

能力清单、Manifest、当前配置和旧配置快照均有 SHA-256 绑定；journal v3 在事务开始时把计划和
候选配置复制为事务私有快照，后续恢复不依赖可能被其他开发者覆盖的共享文件。journal 自身带
`journalSha256`，并通过文件 `fsync + atomic replace` 持久化。任一未完成事务都会在
全局锁内阻止新的 `apply`，必须先恢复，避免旧事务回滚覆盖另一名操作者刚提交的新配置。
组件必须用事务 ID 实现重复 `preflight`、`commit` 和 `rollback` 的幂等语义。
`rollback-failed` 不会被标记为成功，修复组件后需显式使用 `--retry-rollback`。

每个终态还追加到 `config-transaction-audit.jsonl`：记录强制 `actor`、递增 sequence、前序记录
摘要、事务/计划/journal 终态摘要；`config-transaction-audit.head.json` 固定最后记录和整个日志
摘要。`verify-audit` 同时复核 hash-chain、head、尾部截断和最新 journal 的双向绑定。若进程在
追加记录、更新 head、回写 journal 指针之间崩溃，`recover` 只允许对恰好一个落后边界进行前向
对账。`audit-checkpoint` 在先完整验证审计链和所有终态 journal 后，使用独立 Ed25519 密钥签名
当前 sequence、末记录摘要、完整日志摘要和 head 摘要。`verify-audit-checkpoint` 固定 key ID 与公钥
摘要，并证明签名序列仍是当前日志的精确前缀，所以允许链正常增长、拒绝回滚到检查点之前或改写
历史。检查点、签名和公钥 pin 必须复制到 WORM/远端审计系统或独立受保护域；若它们只与本地日志
一起保存，本地日志与 head 同时被删除时仍无法证明历史存在。
