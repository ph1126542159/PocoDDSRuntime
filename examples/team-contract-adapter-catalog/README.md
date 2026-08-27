# Team Contract Adapter Catalog 示例

Adapter Manifest 把一个现有外部进程配置声明为可发现的实现；Catalog 汇总本机已批准的 manifest。新增实现只需
生成 manifest 并进入 Catalog，不需要为列举和能力健康检查修改 `pdr.py`。Catalog 不提供通用业务调用，CAS、
Secret、Artifact 和 Resolver 操作继续使用各自强类型宿主。

```powershell
python create_adapter_manifest.py `
  --config C:\pdr\secret-provider.json `
  --manifest-id production-secret-provider.deploy-2026-09 `
  --adapter-id production-secret-provider `
  --adapter-type secret-provider --owner team/security-platform `
  --revision deploy-2026-09 --protocol-id pdr.secret-provider `
  --identity-field providerId `
  --capability-request-product PocoDDSRuntimeTeamContractSecretProviderCapabilityRequest `
  --capability-manifest-product PocoDDSRuntimeTeamContractSecretProviderCapabilityManifest `
  --output C:\pdr\manifests\secret-provider.json

python create_adapter_catalog.py `
  --catalog-id oslo-runtime-adapters --generation 1 `
  --manifest C:\pdr\manifests\secret-provider.json `
  --output C:\pdr\adapter-catalog.json
```

随后使用 `pdr.py contract-package adapter-catalog-list` 查看声明，使用 `adapter-catalog-check` 对所有选中
Adapter 做只读能力协商。每次操作都会重新固定 Catalog、Manifest、目标配置、可执行程序和辅助制品。

生产 Host 使用独立状态目录原子选择当前 Catalog：

```powershell
$catalogSha = (Get-FileHash C:\pdr\adapter-catalog.json -Algorithm SHA256).Hash.ToLower()
python pdr.py contract-package adapter-catalog-activate `
  --catalog C:\pdr\adapter-catalog.json --expected-catalog-sha256 $catalogSha `
  --state-dir C:\ProgramData\PocoDDSRuntime\adapter-catalog `
  --expected-generation 0 --operation-id deploy-adapters-2026-09 `
  --actor release-operator --reason "approved adapter rollout"

python pdr.py contract-package adapter-catalog-current-check `
  --state-dir C:\ProgramData\PocoDDSRuntime\adapter-catalog
```

更新时必须提交当前 activation generation；过期操作者不能覆盖新状态。回滚使用
`adapter-catalog-rollback --expected-generation <current> --to-generation <historical>`，它复用已验证的历史
Catalog，但创建新的 activation generation，不倒退状态历史。

需要协调长运行 Adapter 生命周期时，先用 `create_reconciler_config.py` 固定 lifecycle Hook，再由 Reconciler
执行完整事务：

```powershell
python create_reconciler_config.py `
  --python C:\Python312\python.exe `
  --adapter C:\pdr\sdk\lifecycle_reconciler_adapter.py `
  --reconciler-id oslo-runtime-lifecycle `
  --output C:\pdr\reconciler.json

python pdr.py contract-package adapter-catalog-reconcile `
  --config C:\pdr\reconciler.json --expected-config-sha256 <config-sha256> `
  --state-dir C:\ProgramData\PocoDDSRuntime\adapter-catalog `
  --transaction-dir C:\ProgramData\PocoDDSRuntime\adapter-rollouts `
  --transaction-id rollout-2026-09 `
  --catalog C:\pdr\adapter-catalog-v2.json `
  --expected-catalog-sha256 <catalog-sha256> --expected-generation 1 `
  --actor release-operator --reason "approved staged rollout"
```

生命周期 Hook 必须实现幂等的 `prepare/drain/activate/health/commit/abort/rollback`。中断后使用
`adapter-catalog-reconcile-recover`；它根据 journal 和当前 Catalog 状态继续，而不是从头猜测。参考 Hook 仅使用
文件模拟进程生命周期，供 SDK 与测试使用，不等同于生产 Runtime/容器编排实现。

已经 committed 的事务可通过 `adapter-catalog-reconcile-revert` 显式撤销。该命令不会直接改 pointer，而是使用原
事务固定的源 Catalog 创建新的 rollback generation，再调用同一个幂等 lifecycle `rollback` Hook；精确重试不会
产生第二次回退。这是多 Host 反向波次回退必须使用的单节点原语。

多 Host 发布先为每个节点生成映射，再固定参考 Node Executor，最后生成 wave plan：

```powershell
python create_fleet_node_map.py --executor-id oslo-fleet `
  --audit C:\ProgramData\PocoDDSRuntime\fleet-audit.log `
  --node node-a C:\pdr\node-a\state C:\pdr\node-a\transactions C:\pdr\node-a\lifecycle `
    C:\pdr\reconciler.json C:\pdr\adapter-catalog-v2.json 1 healthy `
  --output C:\pdr\fleet-node-map.json

python create_fleet_executor_config.py --python C:\Python312\python.exe `
  --adapter C:\pdr\sdk\fleet_node_executor_adapter.py `
  --mapping C:\pdr\fleet-node-map.json --tools-dir C:\pdr\sdk\bin `
  --executor-id oslo-fleet --output C:\pdr\fleet-executor.json

python create_fleet_plan.py --rollout-id oslo-adapters-v2 `
  --catalog C:\pdr\adapter-catalog-v2.json --executor-config C:\pdr\fleet-executor.json `
  --max-parallel-nodes 2 --wave canary canary 0 --wave wave-1 wave 0 `
  --node canary node-a rack-a 1 --node wave-1 node-b rack-b 1 `
  --output C:\pdr\fleet-plan.json
```

运行使用 `adapter-catalog-fleet-run`；协调器异常退出后使用 `adapter-catalog-fleet-recover`，观察使用
`adapter-catalog-fleet-status`。参考 Executor 是本机文件映射，用于 SDK 和验收；生产实现应在同一 SPI 后对接
经授权的远程代理/编排平台，凭据留在 Executor 边界内，不能写进 Plan、node map、journal 或报告。

需要每波 SLO/错误预算或人工审批时，生成 Wave Gate config，并让 Plan 进入 schema v2：

```powershell
python create_wave_gate_config.py --python C:\Python312\python.exe `
  --adapter C:\pdr\sdk\wave_gate_adapter.py --gate-id production-slo-gate `
  --output C:\pdr\wave-gate.json

python create_fleet_plan.py --rollout-id oslo-adapters-v2 `
  --catalog C:\pdr\adapter-catalog-v2.json --executor-config C:\pdr\fleet-executor.json `
  --gate-config C:\pdr\wave-gate.json --max-parallel-nodes 2 `
  --wave canary canary 0 --wave wave-1 wave 0 `
  --node canary node-a rack-a 1 --node wave-1 node-b rack-b 1 `
  --wave-gate canary 300 2 pause --wave-gate wave-1 900 2 rollback `
  --output C:\pdr\fleet-plan-v2.json
```

未到观察时间时状态为 `paused/waiting`，定时调用 recover 会在到期后判定；Gate 返回 pause 时必须使用
`adapter-catalog-fleet-resume` 或 `adapter-catalog-fleet-abort`，并提交 expected control generation、唯一 operation
ID、actor 和 reason。参考 Gate 使用环境变量和文件状态验证幂等边界，不是生产指标系统；生产实现应在 SPI 后
读取 Prometheus/OpenTelemetry/审批服务，只返回判定、稳定诊断码和证据摘要。

生产控制不应只信任 CLI 自报的 actor。生成 Control Authorizer config 并加入同一个 plan 后进入 schema v3：

```powershell
python create_control_authorizer_config.py --python C:\Python312\python.exe `
  --adapter C:\pdr\sdk\control_authorizer_adapter.py `
  --authorizer-id production-release-authorizer `
  --output C:\pdr\control-authorizer.json

python create_fleet_plan.py --rollout-id oslo-adapters-v3 `
  --catalog C:\pdr\adapter-catalog-v2.json --executor-config C:\pdr\fleet-executor.json `
  --gate-config C:\pdr\wave-gate.json `
  --control-authorizer-config C:\pdr\control-authorizer.json `
  --wave canary canary 0 --wave wave-1 wave 0 `
  --node canary node-a rack-a 1 --node wave-1 node-b rack-b 1 `
  --wave-gate canary 300 2 pause --wave-gate wave-1 900 2 rollback `
  --output C:\pdr\fleet-plan-v3.json
```

参考 Authorizer 默认拒绝并把判定按 authorization ID 持久化，只用于 SDK 验证。生产实现应在 SPI 内验证
IAM Principal、短期签名审批或 OPA 决策；凭据通过适配器允许的环境/工作负载身份获得，不能进入 Plan、请求、
journal 或报告。允许响应中的 Principal 必须等于命令 claimed actor。

需要由另一台协调主机接管 rollout 时，在 v3 的基础上加入远程状态 Backend 与 Artifact Store，Plan 自动进入
schema v4：

```powershell
python create_fleet_plan.py --rollout-id oslo-adapters-v4 `
  --catalog C:\pdr\adapter-catalog-v2.json --executor-config C:\pdr\fleet-executor.json `
  --gate-config C:\pdr\wave-gate.json `
  --control-authorizer-config C:\pdr\control-authorizer.json `
  --state-backend-config C:\pdr\fleet-state-backend.json `
  --artifact-store-config C:\pdr\fleet-journal-store.json `
  --wave canary canary 0 --node canary node-a rack-a 1 `
  --wave-gate canary 300 2 pause --output C:\pdr\fleet-plan-v4.json

python pdr.py contract-package adapter-catalog-fleet-recover `
  --plan C:\pdr\fleet-plan-v4.json --expected-plan-sha256 <PLAN_SHA256> `
  --executor-config C:\pdr\fleet-executor.json `
  --expected-executor-config-sha256 <EXECUTOR_SHA256> `
  --state-backend-config D:\host-b\fleet-state-backend.json `
  --artifact-store-config D:\host-b\fleet-journal-store.json `
  --coordinator-id host-b --state-dir D:\host-b\fleet-scratch
```

两个 Host 的配置文件路径可以不同，但内容 SHA、Backend/Store ID、授权 scope 必须与 Plan 一致。v4 的
`--state-dir` 不再是权威 journal，只是本机 scratch；生产 Backend 应提供线性 CAS 和不可变历史，Artifact
Store 应提供 namespace confinement、不可变内容与 read-after-write。

当两个 Host 的五类 Adapter 配置内容或路径都可能不同，使用 Adapter Config Resolver 生成 Plan v5。Plan 只保存
带类型、Adapter ID、revision 和 resolver ID 的逻辑引用；Resolver 配置与映射留在各 Host 本地：

```powershell
python create_fleet_plan.py --rollout-id oslo-adapters-v5 `
  --catalog C:\pdr\adapter-catalog-v2.json --executor-config C:\pdr\fleet-executor.json `
  --gate-config C:\pdr\wave-gate.json --control-authorizer-config C:\pdr\control-authorizer.json `
  --state-backend-config C:\pdr\fleet-state-backend.json `
  --artifact-store-config C:\pdr\fleet-journal-store.json `
  --adapter-config-resolver-id fleet-config-resolver `
  --config-ref fleet-executor fleet.executor revision-1 `
  --config-ref wave-gate fleet.gate revision-1 `
  --config-ref control-authorizer fleet.authorizer revision-1 `
  --config-ref registry-leader-backend fleet.state revision-1 `
  --config-ref artifact-store fleet.artifacts revision-1 `
  --wave canary canary 0 --node canary node-a rack-a 1 `
  --wave-gate canary 300 2 pause --output C:\pdr\fleet-plan-v5.json

python pdr.py contract-package adapter-catalog-fleet-recover `
  --plan C:\pdr\fleet-plan-v5.json --expected-plan-sha256 <PLAN_SHA256> `
  --adapter-config-resolver-config D:\host-b\resolver.json `
  --expected-adapter-config-resolver-config-sha256 <HOST_B_RESOLVER_SHA256> `
  --coordinator-id host-b --state-dir D:\host-b\fleet-scratch
```

Resolver 请求固定 `consumerType=adapter-catalog-fleet`、rollout ID 和 Catalog ID；类型、ID、revision、scope、
映射内容 pin 任一不一致都会失败关闭。Plan v1-v4 继续使用原直连参数。

每个 Adapter 团队在交付配置前应运行统一的 integration-readiness conformance：

```powershell
$sha = (Get-FileHash C:\pdr\fleet-executor.json -Algorithm SHA256).Hash.ToLower()
python pdr.py contract-package adapter-conformance `
  --adapter-kind fleet-executor `
  --config C:\pdr\fleet-executor.json --expected-config-sha256 $sha `
  --report C:\pdr\fleet-executor-conformance.json
```

同一命令支持 `wave-gate`、`control-authorizer`、`registry-leader-backend`、`artifact-store` 和
`adapter-config-resolver`。Backend 额外传 `--scope-primary <AUTHORITY_ID> --scope-secondary <REGISTRY_ID>`；
Artifact Store 传 `--scope-primary <NAMESPACE_ID>`。证据固定 Adapter/配置/能力摘要，重复协商必须稳定，错误
配置 pin 必须拒绝，并且不包含本机路径、配置内容或环境值。这个级别证明通用集成边界；真实集群、真实 IAM、
性能和业务副作用仍需各 Adapter 的专项 acceptance。

Fleet Plan v7 可在 v6 evidence 准入上增加签名信任链。先用公共
`adapter-conformance-attest` 命令为六类 evidence 生成 Ed25519 attestation，再用
`adapter-conformance-admission-create --attestation <KIND> <PATH>` 生成 schema v2 bundle；执行 Fleet 时固定
trust policy 文件 SHA。`create_conformance_trust_demo.py` 能生成仅供本地 SDK 验收的临时密钥和 policy，生产
环境不得把该脚本当作 KMS/HSM 或证书发布系统。
