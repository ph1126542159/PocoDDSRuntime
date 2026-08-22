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

## 预检、提交与逆序回滚

先保存当前解析配置，再生成候选配置和摘要绑定计划：

```powershell
./tools/pdr.ps1 project config plan pdr-project.yaml `
  --current build/active-config.json `
  --candidate build/candidate-config.json `
  --output build/config-plan.json

./tools/pdr.ps1 project config apply pdr-project.yaml `
  --plan build/config-plan.json `
  --current build/active-config.json `
  --candidate build/candidate-config.json
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
所有参与者预检成功后才开始提交；提交调用前先记录 `commitAttempted`，所以进程即使在组件
响应前中断，也会在恢复时对该参与者执行幂等回滚。任一提交失败时按逆序回滚所有已尝试
参与者，全部回滚成功后才恢复旧配置快照。

事务日志位于 `build/config-transactions/`。中断后使用：

```powershell
./tools/pdr.ps1 project config recover pdr-project.yaml `
  --journal build/config-transactions/<transaction-id>.journal.json
```

能力清单、计划、Manifest、当前配置、候选配置和旧配置快照均有 SHA-256 绑定；任一输入变更
都会拒绝应用或恢复。组件必须用事务 ID 实现重复 `preflight`、`commit` 和 `rollback` 的
幂等语义。`rollback-failed` 不会被标记为成功，修复组件后需显式使用 `--retry-rollback`。
