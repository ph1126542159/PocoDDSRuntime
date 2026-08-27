# 团队契约包与锁文件

跨仓库开发时，Consumer 不应依赖 Provider 工作区的绝对路径，也不应从共享目录中“拿最新文件”。
PocoDDSRuntime 将以下纯 JSON 接口封装为不可执行的确定性契约包：

- Bundle `service-contracts.json`；
- Bundle `configuration-participants.json`；
- Bundle `configuration-key-lifecycle.json`；
- 三类对应的已发布兼容基线。

包内路径由角色和文件 SHA-256 生成。输入文件换目录、换文件名或从另一个仓库检出，只要内容、包
ID、版本、Owner 和 `source-date-epoch` 相同，制品字节就相同。包中不允许脚本、动态库、符号链接、
未登记条目或目录穿越。

## Provider 发布

```powershell
python tools/pdr.py contract-package pack `
  --package-id team.scheduling `
  --version 1.4.0 `
  --owner team.scheduling `
  --source-date-epoch 1700000000 `
  --input service-contract=Scheduler/bundle/service-contracts.json `
  --input participant-declaration=Scheduler/bundle/configuration-participants.json `
  --input key-lifecycle=Scheduler/bundle/configuration-key-lifecycle.json `
  --ed25519-private-key-environment PDR_TEAM_SCHEDULING_PRIVATE_KEY `
  --signing-key-id team-scheduling-2026 `
  --output build/contracts/team.scheduling-1.4.0.pdrcontracts

python tools/pdr.py contract-package verify `
  build/contracts/team.scheduling-1.4.0.pdrcontracts `
  --require-signature `
  --trust-policy contracts/team-contract-trust-policy.json `
  --expected-trust-policy-id product-team-contracts `
  --expected-trust-policy-sha256 $policySha256 `
  --report build/reports/team.scheduling.verify.json
```

私钥环境变量保存 PEM 文件路径，私钥和口令都不会写入包。包内 Ed25519 签名覆盖原始 manifest
字节；信任策略再固定 `keyId`、Owner、允许的精确包 ID/带点结尾的包前缀、公钥相对路径和
SHA-256、有效期及撤销表。公钥只能从信任策略目录读取，不能从待验证包中读取。生产锁定必须使用
`--require-signature`，仅本地开发可以显式使用未签名包。

## Consumer 锁定与解析

锁文件不记录源路径，团队可从制品库、CI cache 或受审查的本地目录取得包：

```powershell
python tools/pdr.py contract-package lock `
  --package cache/team.scheduling-1.4.0.pdrcontracts `
  --package cache/team.workflow-2.1.0.pdrcontracts `
  --require-signature `
  --trust-policy contracts/team-contract-trust-policy.json `
  --expected-trust-policy-id product-team-contracts `
  --expected-trust-policy-sha256 $policySha256 `
  --output contracts/team-contracts.lock.json

python tools/pdr.py contract-package resolve `
  --lock contracts/team-contracts.lock.json `
  --package D:/another-cache/scheduling-renamed.pdrcontracts `
  --package build/incoming/workflow.pdrcontracts `
  --require-signature `
  --trust-policy contracts/team-contract-trust-policy.json `
  --expected-trust-policy-id product-team-contracts `
  --expected-trust-policy-sha256 $policySha256 `
  --output build/resolved-contracts `
  --report build/reports/team-contract-resolution.json
```

解析要求提供的包集合与锁文件完全相同，并复核 package、manifest、artifact-set 和每个 JSON 文件的
摘要。输出报告列出各角色的相对路径；这些文件可继续传给现有
`pdr_add_component_contract_test()`、`pdr_add_configuration_participant_contract_test()` 和
`pdr_add_configuration_key_lifecycle_contract_test()`。

安装 SDK 还提供：

```cmake
pdr_add_team_contract_package_test(
    NAME resolve-provider-contracts
    LOCK "${CMAKE_CURRENT_SOURCE_DIR}/contracts/team-contracts.lock.json"
    PACKAGES ${provider_contract_packages}
    REQUIRE_SIGNATURE
    TRUST_POLICY "${CMAKE_CURRENT_SOURCE_DIR}/contracts/team-contract-trust-policy.json"
    EXPECTED_TRUST_POLICY_ID product-team-contracts
    EXPECTED_TRUST_POLICY_SHA256 "${team_contract_trust_policy_sha256}"
    OUTPUT_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/resolved-contracts"
    REPORT "${CMAKE_CURRENT_BINARY_DIR}/reports/team-contract-resolution.json")
```

该 CTest 不启动 Runtime、不访问网络、不扫描其他团队源码，并在每次解析时重新检查撤销、有效期、
Owner、包范围、公钥和签名。Provider 升级必须先生成新包，经 Reviewer 确认后刷新锁文件；仅替换
文件路径不需要改锁。策略轮换或撤销会改变策略 SHA，必须经过独立 Reviewer 更新锁定入口。

## 锁升级影响预演

产品维护 `team-contract-consumers.json`，显式声明 Consumer ID、Owner、消费的包/角色和升级后必须
执行的 CTest 标签。该目录不扫描其他团队源码，也不根据文件路径猜依赖：

```json
{
  "schemaVersion": 2,
  "product": "PocoDDSRuntimeTeamContractConsumerCatalog",
  "consumers": [{
    "id": "team.workflow",
    "owner": "team.workflow",
    "dependencies": [{
      "packageId": "team.scheduling",
      "roles": ["service-contract"]
    }],
    "requiredTestLabels": ["component", "service"]
  }]
}
```

候选锁进入评审前运行：

```powershell
python tools/pdr.py contract-package impact `
  --current-lock contracts/team-contracts.lock.json `
  --current-package cache/scheduling-1.4.0.pdrcontracts `
  --candidate-lock build/team-contracts.candidate.lock.json `
  --candidate-package build/scheduling-1.5.0.pdrcontracts `
  --consumer-catalog contracts/team-contract-consumers.json `
  --require-signature `
  --current-trust-policy contracts/team-contract-trust-policy.json `
  --current-expected-trust-policy-id product-team-contracts `
  --current-expected-trust-policy-sha256 $currentPolicySha256 `
  --candidate-trust-policy contracts/team-contract-trust-policy.json `
  --candidate-expected-trust-policy-id product-team-contracts `
  --candidate-expected-trust-policy-sha256 $candidatePolicySha256 `
  --report build/reports/team-contract-upgrade-impact.json
```

工具在比较前重新验证两份锁、全部包和签名。以下变化直接返回退出码 1：包删除/降级、同版本内容
漂移、Provider 删除/改名/降级/主版本变化、Participant 删除/换 Owner/改 Service/缩窄前缀/移除
排序保证、生命周期声明删除或身份变化。兼容升级返回 0，但仍输出受影响 Consumer、Owner、角色、
`requiredTestLabels` 和可直接用于 `ctest -L` 的正则；输入或信任证据非法返回 2。

安装 SDK 对应函数为 `pdr_add_team_contract_impact_test()`。它适合放在候选锁合并门禁中；报告
`inputSetSha256` 同时绑定当前锁、候选锁和 Consumer 目录，不能复用到另一组升级。

## 执行证据与 Consumer Owner 批准

兼容不等于已经验收。影响报告为 compatible 后，还要执行报告选出的真实 CTest，并由每个受影响
Consumer Owner 分别签署短期批准：

```powershell
python tools/pdr.py contract-package impact-execute `
  --report build/reports/team-contract-upgrade-impact.json `
  --ctest C:/Qt/Tools/CMake_64/bin/ctest.exe `
  --test-dir build `
  --config Release `
  --evidence build/reports/team-contract-impact-execution.json `
  --junit build/reports/team-contract-impact-tests.xml

python tools/pdr.py contract-package impact-approve `
  --report build/reports/team-contract-upgrade-impact.json `
  --owner team.workflow `
  --approver-id workflow-contract-owner `
  --key-id workflow-contract-owner-2026 `
  --private-key-environment PDR_WORKFLOW_IMPACT_APPROVAL_KEY `
  --lifetime-seconds 3600 `
  --output build/approvals/team.workflow.json

python tools/pdr.py contract-package impact-gate `
  --report build/reports/team-contract-upgrade-impact.json `
  --evidence build/reports/team-contract-impact-execution.json `
  --junit build/reports/team-contract-impact-tests.xml `
  --ctest C:/Qt/Tools/CMake_64/bin/ctest.exe `
  --test-dir build `
  --config Release `
  --approval-policy contracts/team-contract-impact-approval-policy.json `
  --expected-approval-policy-id product-impact-owners `
  --expected-approval-policy-sha256 $approvalPolicySha256 `
  --approval build/approvals/team.workflow.json `
  --gate-report build/reports/team-contract-impact-gate.json
```

执行证据固定影响报告、候选锁、CTest 可执行文件、当前测试目录、选中测试命令和 JUnit 摘要；Gate
会重新查询测试目录，目录或命令在执行后变化即拒绝。失败、disabled、skipped、标签覆盖不全或空选集
均不能生成通过证据。批准策略把 Owner、批准人、独立 Ed25519 key、公钥 SHA、有效期和撤销表固定在
待批准文件之外；每个受影响 Owner 必须有不同批准人和 key。破坏性影响不能进入批准流程，无影响
报告也不能夹带无关批准。

安装 SDK 提供同等的 `pdr_add_team_contract_impact_execution_test()`、
`pdr_add_team_contract_impact_approval_test()` 和 `pdr_add_team_contract_impact_gate_test()`。审批测试只读取
私钥路径环境变量；实际产品 CI 可把批准文件作为独立受保护作业的输入，再让 Gate 依赖影响、执行和
全部 Owner 批准测试。

## 契约 Registry 与环境晋级

团队不再需要向 Consumer 传递某台机器上的包路径。Registry 保存内容寻址 package/lock blob，
`registry.json` 只原子指向最新不可变状态；每次 publish、promote 和 rollback 都生成带前一状态
SHA-256 的新 revision。写操作使用跨进程独占 lease，并在修改前重新验证完整状态链、全部包、锁、
签名、信任策略 pin 和通道代次。

```powershell
python tools/pdr.py contract-package registry-init `
  --registry D:/contract-registry `
  --registry-id product-contracts `
  --actor contract-admin `
  --trust-policy contracts/team-contract-trust-policy.json `
  --expected-trust-policy-id product-team-contracts `
  --expected-trust-policy-sha256 $policySha256

python tools/pdr.py contract-package registry-publish `
  --registry D:/contract-registry `
  --package build/team.scheduling-1.5.0.pdrcontracts `
  --actor team.scheduling `
  --trust-policy contracts/team-contract-trust-policy.json `
  --expected-trust-policy-id product-team-contracts `
  --expected-trust-policy-sha256 $policySha256

python tools/pdr.py contract-package registry-promote `
  --registry D:/contract-registry `
  --channel dev `
  --lock build/team-contracts.candidate.lock.json `
  --expected-generation 0 `
  --actor release-manager `
  --trust-policy contracts/team-contract-trust-policy.json `
  --expected-trust-policy-id product-team-contracts `
  --expected-trust-policy-sha256 $policySha256

python tools/pdr.py contract-package registry-promote `
  --registry D:/contract-registry `
  --channel staging `
  --lock build/team-contracts.candidate.lock.json `
  --expected-generation 0 `
  --impact-gate build/reports/team-contract-impact-gate.json `
  --actor release-manager `
  --trust-policy contracts/team-contract-trust-policy.json `
  --expected-trust-policy-id product-team-contracts `
  --expected-trust-policy-sha256 $policySha256
```

默认通道顺序是 `dev → staging → production`。`dev` 可接收 Registry 中已发布包组成的新锁；后续通道
只能接收其直接前置通道当前的同一锁，并且必须提供候选锁摘要一致的执行/Owner 审批 Gate。
`--expected-generation` 提供乐观并发控制，阻止两名发布人员基于旧通道状态互相覆盖。Registry 拒绝
同包同版本不同内容、未发布包、包删除/降级、跳级和跨信任策略锁。

Consumer 只按通道解析，不再提供包文件列表：

```powershell
python tools/pdr.py contract-package registry-resolve `
  --registry D:/contract-registry `
  --channel production `
  --output build/resolved-production-contracts `
  --report build/reports/production-contract-resolution.json `
  --trust-policy contracts/team-contract-trust-policy.json `
  --expected-trust-policy-id product-team-contracts `
  --expected-trust-policy-sha256 $policySha256
```

安装 SDK 的 `pdr_add_team_contract_registry_test()` 提供相同的隔离 CTest。事故回退使用
`registry-rollback --expected-generation N --to-generation M --actor ... --reason ...`，它不会改写旧状态或
复用原代次，而是创建指向历史锁的新一代，并留下回退来源和原因。`registry-verify` 可离线复核完整
revision 转移语义和所有制品。

本地 Registry 状态链能发现意外损坏和不合法转移，但拥有 Registry 根目录完全写权限的人仍能重写
整条历史；生产部署还应使用只允许 CI 服务身份写入的远端存储、备份/保留策略，并把最新
`stateSha256` 定期锚定到仓库外审计系统。

## 跨机器 Registry 控制面

安装 SDK 提供 `team_contract_registry_remote.py`，以现有不可变 Registry 状态机作为唯一写入内核，
增加无服务端路径的远程 publish/promote/rollback/verify/resolve，并提供 status、recover 和 audit
运维接口。访问策略为每个 principal 固定
token SHA-256、角色、允许 package ID、允许 channel、有效期与撤销状态；服务端从 principal 派生
审计 actor，客户端不能自报身份。token 只从环境变量读取，不进入命令参数或响应。

生产服务必须提供 TLS 证书与私钥：

```powershell
python tools/pdr.py contract-package registry-remote-serve `
  --registry D:/contract-registry `
  --bind 0.0.0.0 --port 9443 `
  --tls-certificate D:/secrets/registry.crt `
  --tls-private-key D:/secrets/registry.key `
  --audit-archive-directory E:/independent-audit/segments `
  --access-policy D:/registry-policy/access.json `
  --expected-access-policy-id product-contract-registry-access `
  --expected-access-policy-sha256 $accessPolicySha256 `
  --access-policy-trust-policy D:/registry-policy/access-policy-signers.json `
  --expected-access-policy-trust-policy-id product-access-policy-signers `
  --expected-access-policy-trust-policy-sha256 $accessSignerPolicySha256 `
  --trust-policy D:/registry-policy/package-trust.json `
  --expected-trust-policy-id product-team-contracts `
  --expected-trust-policy-sha256 $packagePolicySha256 `
  --runner-trust-policy D:/registry-policy/runner-trust.json `
  --expected-runner-trust-policy-id product-ci-runners `
  --expected-runner-trust-policy-sha256 $runnerPolicySha256 `
  --gate-authorization-policy D:/registry-policy/gate-authorizers.json `
  --expected-gate-authorization-policy-id product-gate-authorizers `
  --expected-gate-authorization-policy-sha256 $gatePolicySha256 `
  --node-id contracts-oslo-01 `
  --handoff-evidence-directory E:/external-leader/handoff-evidence `
  --handoff-key-id contracts-oslo-01-handoff-2026 `
  --handoff-private-key-environment PDR_HANDOFF_PRIVATE_KEY
```

Provider 不需要共享工作区或 Registry 文件路径：

```powershell
$env:PDR_TEAM_REGISTRY_TOKEN = Get-Content D:/secrets/provider-token.txt -Raw
python tools/pdr.py contract-package registry-remote-publish `
  --url https://contracts.example.internal:9443 `
  --registry-id product-contracts `
  --request-id team-scheduler-publish-1042 `
  --token-environment PDR_TEAM_REGISTRY_TOKEN `
  --expected-revision 41 `
  --package build/team.scheduler-1.2.0.pdrcontracts
```

所有远程 mutation 必须提供 `expected-revision`；promote 还保留 channel generation 门禁。服务端将
canonical command SHA 与 request ID 持久化：同 ID/同内容只返回原结果，同 ID/不同内容拒绝；服务
中断后若 pending 请求已跨过 Registry revision，会 fail-closed 并要求人工核对，而不会盲目重放。
`auditor`/`operator` 可先查询脱敏状态；恢复动作必须同时固定原 command SHA、started revision 和当前
观测 revision。若 revision 未变，只能明确标记 `aborted` 并使用新 request ID 重试；若 revision 已
前进，只能标记 `uncertain`，由业务方核对 Registry revision/event 后另行处理，框架不会猜测成功：

```powershell
python tools/pdr.py contract-package registry-remote-status `
  --url https://contracts.example.internal:9443 `
  --registry-id product-contracts --request-id team-scheduler-publish-1042 `
  --token-environment PDR_TEAM_REGISTRY_AUDITOR_TOKEN

python tools/pdr.py contract-package registry-remote-recover `
  --url https://contracts.example.internal:9443 `
  --registry-id product-contracts --recovery-id incident-1842-recovery-1 `
  --target-request-id team-scheduler-publish-1042 `
  --target-request-sha256 $requestSha256 `
  --expected-started-revision 41 --expected-current-revision 42 `
  --disposition uncertain --reason "revision advanced before response durability" `
  --token-environment PDR_TEAM_REGISTRY_OPERATOR_TOKEN
```

请求的 `started/completed/recovered` 迁移写入控制目录下不可覆盖的 SHA-256 记录链；修改记录、删除
中间记录、重排或只回退 head 都会使 `registry-remote-audit-verify` 失败。为了检测攻击者把整个控制
目录恢复成较旧但内部自洽的副本，独立审计方应周期性将检查点签名并保存在控制目录之外：

```powershell
$env:PDR_REMOTE_AUDIT_KEY = "D:/audit-secrets/registry-auditor.private.pem"
python tools/pdr.py contract-package registry-remote-audit-checkpoint `
  --control-directory D:/contract-registry/.remote-control `
  --registry-id product-contracts --checkpoint-id daily-2026-08-25 `
  --auditor-id external.registry-auditor --key-id registry-audit-2026 `
  --private-key-environment PDR_REMOTE_AUDIT_KEY `
  --output E:/independent-audit/product-contracts-2026-08-25.json

python tools/pdr.py contract-package registry-remote-audit-checkpoint-verify `
  --control-directory D:/contract-registry/.remote-control `
  --registry-id product-contracts `
  --checkpoint E:/independent-audit/product-contracts-2026-08-25.json `
  --audit-policy E:/independent-audit/policy.json `
  --expected-audit-policy-id product-remote-registry-auditors `
  --expected-audit-policy-sha256 $auditPolicySha256
```

审计记录达到在线容量阈值时，可把已签名检查点覆盖的连续前缀写成确定性 `.pdraudit` 分段。服务启动
必须显式配置同一个控制目录外归档目录；create 只写归档并注册连续 marker/base，不删除在线记录：

```powershell
python tools/pdr.py contract-package registry-remote-audit-archive-create `
  --control-directory D:/contract-registry/.remote-control `
  --audit-archive-directory E:/independent-audit/segments `
  --registry-id product-contracts --archive-id product-contracts-2026-08-25 `
  --checkpoint E:/independent-audit/product-contracts-2026-08-25.json `
  --audit-policy E:/independent-audit/policy.json `
  --expected-audit-policy-id product-remote-registry-auditors `
  --expected-audit-policy-sha256 $auditPolicySha256 `
  --output product-contracts-2026-08-25.pdraudit

python tools/pdr.py contract-package registry-remote-audit-archive-prune `
  --control-directory D:/contract-registry/.remote-control `
  --audit-archive-directory E:/independent-audit/segments `
  --registry-id product-contracts `
  --expected-through-sequence $checkpointSequence `
  --expected-through-record-sha256 $checkpointRecordSha256 `
  --confirm-prune
```

prune 只删除已注册归档中逐字节相同的在线 audit record，不删除 request/recovery/response；中断后在线
重复前缀仍可验证，重试会只处理剩余副本。运行时每次验证都会复核外部归档 SHA、manifest、记录链、
checkpoint 绑定和在线后缀；`registry-remote-audit-archive-verify` 还会按固定 policy 重新验证每个 Ed25519
签名。归档目录丢失或任一字节变化都会 fail-closed。该机制仍不是多节点共识：要发现控制目录和归档
被同时整体回退，最新签名 checkpoint/policy 必须另存于独立审计域。

检查点私钥和输出路径都必须位于控制目录之外；验证会固定 policy ID/SHA、公钥 SHA、Registry scope、
签发有效期和撤销状态，并要求当前链仍包含已签名历史前缀。首次升级旧控制目录时，服务启动会为
既有请求建立迁移时点基线；该基线只能证明迁移之后的连续性，不能追溯证明迁移前未被改写。

### 访问策略热轮换与容量门禁

启动参数中的 access policy SHA 仍固定启动时基线。要在不中断服务的情况下撤销 token、变更角色或
调整容量，先准备普通 schema v1 候选内容，再由独立轮换密钥签成 schema v2 后继 revision；候选内容
本身不需要与前驱相同，`--expected-previous-policy-sha256` 指向当前活动文件的原始字节 SHA：

```powershell
$currentAccessSha = (Get-FileHash D:/registry-policy/access.json -Algorithm SHA256).Hash.ToLower()
$env:PDR_ACCESS_POLICY_SIGNER_KEY = "E:/policy-secrets/access-policy.private.pem"

python tools/pdr.py contract-package registry-access-policy-sign `
  --input D:/registry-policy/access-candidate-v1.json `
  --expected-previous-policy-sha256 $currentAccessSha `
  --policy-revision 7 --issued-at 2026-08-25T12:00:00Z `
  --key-id product-access-policy-2026 `
  --private-key-environment PDR_ACCESS_POLICY_SIGNER_KEY `
  --max-active-request-records 100000 `
  --max-recovery-records 100000 --max-audit-records 1000000 `
  --max-control-bytes 4294967296 `
  --output D:/registry-policy/access-revision-7.json

python tools/pdr.py contract-package registry-access-policy-activate `
  --active-policy D:/registry-policy/access.json `
  --candidate D:/registry-policy/access-revision-7.json `
  --expected-current-policy-sha256 $currentAccessSha `
  --trust-policy D:/registry-policy/access-policy-signers.json `
  --expected-trust-policy-id product-access-policy-signers `
  --expected-trust-policy-sha256 $accessSignerPolicySha256
```

`activate` 先校验签名、policy/Registry scope、当前文件 SHA、`revision + 1` 和前驱 SHA，再用同目录临时
文件原子替换。服务端每个请求前检查活动文件；合法后继写入 `policy-reloaded` 审计记录后才生效。
文件被直接换回旧版本、出现无签名内容、跳 revision 或签名无效时，服务端返回 503 并停止授权新请求，
不会继续静默使用内存中的旧策略。服务重启时需要把启动参数的 expected access-policy SHA 更新为
当前签名 revision；轮换 signer trust policy 本身仍要求受控重启并更新固定 SHA。

容量由活动签名策略控制，可通过 auditor/operator token 查询：

```powershell
python tools/pdr.py contract-package registry-remote-capacity `
  --url https://contracts.example.internal:9443 `
  --registry-id product-contracts `
  --token-environment PDR_TEAM_REGISTRY_AUDITOR_TOKEN `
  --report build/reports/registry-remote-capacity.json
```

报告分别给出活动请求、恢复、审计记录数量，各类字节数、控制目录总字节，以及新 mutation/recovery
是否仍可准入。写入按照最坏响应容量预留空间，在越界前返回 HTTP 507。当前版本有意不自动删除请求
记录、幂等响应或审计链，因为无检查点分段和 tombstone 的删除会破坏重放与取证语义；达到门禁后应
先扩容，后续再通过独立、检查点约束的归档流程治理历史，不能手工删除控制目录内容。

### Registry 写者租约与崩溃接管

本地 Registry 写指针和远程控制目录事务不再以“锁文件是否存在”判断占用。Windows 使用不共享写入
的文件句柄，POSIX 使用非阻塞 `flock`；进程退出或被终止后，操作系统自动释放所有权。`.lock`
文件故意保留为最近 Owner、PID、主机、操作和获取时间的只读证据，运维人员不得删除它：

```powershell
python tools/pdr.py contract-package registry-lease-status `
  --registry D:/contract-registry `
  --report build/reports/registry-writer-lease.json

python tools/pdr.py contract-package registry-remote-lease-status `
  --url https://contracts.example.internal:9443 `
  --registry-id product-contracts `
  --token-environment PDR_TEAM_REGISTRY_AUDITOR_TOKEN `
  --report build/reports/registry-remote-leases.json
```

每次获取租约都会在独立 epoch 文件中原子推进 fencing token。Registry 在发布当前指针前、远程控制
事务在落最终审计/响应前再次核对 epoch；若更高 epoch 已出现，旧写者 fail-closed，不能继续提交。
Owner 进程崩溃后的正常恢复方式是由受监督的新进程重新获取 OS 租约，而不是按时间猜测“stale”或
强制删除文件。epoch 损坏、Owner 元数据与 epoch 不一致或活动租约缺 Owner 时状态报告为 unhealthy，
新写入不得继续，应保留原文件取证后从已验证备份恢复 fencing 状态。

该租约保证同一受支持主机/文件系统上的单写者，不把不可靠网络文件系统、跨数据中心租约或多副本
共识包装成本地文件锁。多节点 HA 仍需带法定人数的外部协调器和存储级 fencing。

非 TLS 只允许显式 `--allow-insecure-loopback`，用于本机 CTest。当前服务是单 Registry、单写者的
串行控制面，不宣称多副本共识或自动故障转移；高可用部署仍需外部进程监督、存储复制和仓库外锚。

Consumer 使用 `registry-remote-resolve` 下载摘要逐文件复核的通道解析结果，并在临时目录完整校验后
原子发布到目标目录；返回的操作报告使用字段白名单，不包含 Registry、临时目录或策略文件的服务端
绝对路径。响应容量、请求容量、文件数量、解压总量均有界。`.pdrcontracts` 验证还要求
ZIP 结束记录精确位于文件末尾，附加未签名尾随字节会直接拒绝。

## CI Runner 证明与仓库外状态锚

Owner 批准说明“谁接受升级”，Runner 证明说明“哪一个受信执行环境、在哪个仓库 revision、通过哪条
workflow/job/run 执行了证据”。两者使用不同的 Ed25519 key 和信任策略：

```powershell
python tools/pdr.py contract-package runner-attest `
  --report build/reports/team-contract-upgrade-impact.json `
  --evidence build/reports/team-contract-impact-execution.json `
  --junit build/reports/team-contract-impact-tests.xml `
  --runner-id ci.windows.release `
  --repository product/runtime `
  --source-revision $gitCommit `
  --workflow team-contract-acceptance `
  --job-id windows-release `
  --run-id $ciRunId `
  --key-id windows-release-runner-2026 `
  --private-key-environment PDR_TEAM_CONTRACT_RUNNER_KEY `
  --output build/reports/team-contract-runner-attestation.json
```

Runner 签名绑定 impact/input/candidate lock、执行证据、JUnit、CTest 程序、目录 catalog 和实际命令
摘要。`impact-gate` 通过 `--runner-attestation`、`--runner-trust-policy` 及固定 policy ID/SHA 复核
repository/workflow scope、有效期和撤销。安装 SDK 的
`pdr_add_team_contract_runner_attestation_test()` 可将此步骤放在 execution 与最终 Gate 之间。
Registry 的 staging/production 晋级强制要求 Gate 含有效 Runner 摘要；仅本地生成的无 Runner Gate
不能晋级。

最终发布还需由独立 Gate 授权服务使用 `gate-authorize` 重放完整 Gate 校验并签名。授权精确绑定
Gate 原始字节、候选锁、impact/执行/Runner 摘要、Registry ID 与允许通道，且只有短期有效：

```powershell
python tools/pdr.py contract-package gate-authorize `
  --gate-report build/reports/team-contract-impact-gate.json `
  --report build/reports/team-contract-upgrade-impact.json `
  --evidence build/reports/team-contract-impact-execution.json `
  --junit build/reports/team-contract-impact-tests.xml `
  --ctest $ctest --test-dir build --config Release `
  --approval-policy contracts/impact-approval-policy.json `
  --expected-approval-policy-id product-impact-owners `
  --expected-approval-policy-sha256 $approvalPolicySha256 `
  --approval build/reports/team-a.approval.json `
  --runner-attestation build/reports/team-contract-runner-attestation.json `
  --runner-trust-policy contracts/runner-trust-policy.json `
  --expected-runner-trust-policy-id product-ci-runners `
  --expected-runner-trust-policy-sha256 $runnerPolicySha256 `
  --registry-id product-contracts --channel staging --channel production `
  --authorization-id release-00042 --authorizer-id release.gate.service `
  --key-id release-gate-2026 `
  --private-key-environment PDR_RELEASE_GATE_KEY `
  --output build/reports/team-contract-gate-authorization.json
```

安装 SDK 的 `pdr_add_team_contract_gate_authorization_test()` 提供相同重放签发步骤。Registry 在
staging/production 晋级时独立验证授权 policy ID/SHA、签名、公钥摘要、Registry/channel scope、
有效期和撤销，并把授权 SHA 写入不可变通道状态；修改 Gate 内 Owner 汇总后，即使 Runner 签名仍
有效也不能晋级。发布管理者、Owner、Runner、包发布者与 Gate 授权服务应使用相互独立的密钥。

Registry 当前状态还可由独立审计服务签名并保存在 Registry 根目录之外：

```powershell
python tools/pdr.py contract-package registry-anchor `
  --registry D:/contract-registry `
  --anchor-id product-contracts-00042 `
  --anchor-service-id external.audit.service `
  --key-id registry-audit-2026 `
  --private-key-environment PDR_REGISTRY_AUDIT_KEY `
  --output E:/external-audit/product-contracts-00042.anchor.json `
  --trust-policy contracts/team-contract-trust-policy.json `
  --expected-trust-policy-id product-team-contracts `
  --expected-trust-policy-sha256 $packagePolicySha256

python tools/pdr.py contract-package registry-anchor-verify `
  --registry D:/contract-registry `
  --anchor E:/external-audit/product-contracts-00042.anchor.json `
  --anchor-policy E:/external-audit/registry-anchor-policy.json `
  --expected-anchor-policy-id product-registry-auditors `
  --expected-anchor-policy-sha256 $anchorPolicySha256 `
  --trust-policy contracts/team-contract-trust-policy.json `
  --expected-trust-policy-id product-team-contracts `
  --expected-trust-policy-sha256 $packagePolicySha256
```

验证要求当前 pointer 的 revision 不低于锚点，并沿当前 previous-state SHA 链精确找到被签名状态；把
整个 Registry 恢复成较老但内部自洽的副本也会被发现。锚点 policy 单独限制审计服务、key 和允许的
Registry ID，并复核公钥 SHA、有效期和撤销。若需要连续外部锚链，新锚可用 `--previous-anchor`
绑定上一份锚文件摘要。Consumer CI 可通过安装 SDK 的
`pdr_add_team_contract_registry_anchor_verification_test()` 持续执行同一回退检测；签发锚点仍由独立
审计服务负责，CMake Consumer 不接触审计私钥。

### Registry 整库灾难恢复点

普通 Runtime 恢复点不包含 Team Contract Registry。取得“精确等于当前 revision”的外部 anchor 后，
可在 Registry 写者租约下创建确定性 `.pdrregistry`。恢复点包含从 revision 0 到当前 revision 的完整
状态链、当前累计 package/lock blob、pointer 和 anchor；不会包含私钥、访问 token、远程控制目录或
审计归档：

```powershell
python tools/pdr.py contract-package registry-recovery-create `
  --registry D:/contract-registry `
  --recovery-point-id product-contracts-dr-00042 `
  --anchor E:/external-audit/product-contracts-00042.anchor.json `
  --operator registry.backup `
  --output F:/offsite/product-contracts-00042.pdrregistry `
  --anchor-policy E:/external-audit/registry-anchor-policy.json `
  --expected-anchor-policy-id product-registry-auditors `
  --expected-anchor-policy-sha256 $anchorPolicySha256 `
  --trust-policy contracts/team-contract-trust-policy.json `
  --expected-trust-policy-id product-team-contracts `
  --expected-trust-policy-sha256 $packagePolicySha256

python tools/pdr.py contract-package registry-recovery-verify `
  --recovery-point F:/offsite/product-contracts-00042.pdrregistry `
  --expected-recovery-point-sha256 $recoveryPointSha256 `
  --anchor-policy E:/external-audit/registry-anchor-policy.json `
  --expected-anchor-policy-id product-registry-auditors `
  --expected-anchor-policy-sha256 $anchorPolicySha256 `
  --trust-policy contracts/team-contract-trust-policy.json `
  --expected-trust-policy-id product-team-contracts `
  --expected-trust-policy-sha256 $packagePolicySha256
```

只有原 Registry 已确认不可用并完成变更审批后，才恢复到一个尚不存在的新目录：

```powershell
python tools/pdr.py contract-package registry-recovery-restore `
  --recovery-point F:/offsite/product-contracts-00042.pdrregistry `
  --expected-recovery-point-sha256 $recoveryPointSha256 `
  --destination D:/restored/product-contract-registry `
  --restore-id incident-1842-registry-restore-1 `
  --operator registry.recovery `
  --operation-audit E:/external-audit/registry-restore-operations.jsonl `
  --confirm-source-unavailable `
  --anchor-policy E:/external-audit/registry-anchor-policy.json `
  --expected-anchor-policy-id product-registry-auditors `
  --expected-anchor-policy-sha256 $anchorPolicySha256 `
  --trust-policy contracts/team-contract-trust-policy.json `
  --expected-trust-policy-id product-team-contracts `
  --expected-trust-policy-sha256 $packagePolicySha256
```

restore 先在同一父目录构造并完整复验暂存 Registry，再原子发布；目标已存在、介质摘要变化、anchor
落后于当前状态、anchor policy/包 trust policy 漂移或未确认源端失效都会拒绝。它不提供自动故障
切换，也不授予新节点 Leader 身份；远程 request/audit 控制状态与外部分段归档必须按各自恢复流程
恢复并重新验证，确认旧写节点被隔离后才能重新开放 mutation。

### 只读 Registry 热备

同一 `.pdrregistry` 也可以初始化仍有健康主 Registry 的只读热备；这条路径不需要声明源端失效：

```powershell
python tools/pdr.py contract-package registry-standby-init `
  --recovery-point F:/offsite/product-contracts-00042.pdrregistry `
  --expected-recovery-point-sha256 $recoveryPointSha256 `
  --destination D:/standby/product-contract-registry `
  --standby-id contracts-oslo-02 --operator standby.sync `
  --operation-audit E:/external-audit/standby-operations.jsonl `
  --anchor-policy E:/external-audit/registry-anchor-policy.json `
  --expected-anchor-policy-id product-registry-auditors `
  --expected-anchor-policy-sha256 $anchorPolicySha256 `
  --trust-policy contracts/team-contract-trust-policy.json `
  --expected-trust-policy-id product-team-contracts `
  --expected-trust-policy-sha256 $packagePolicySha256
```

取得更高 revision 的新恢复点后，先停止备节点远程服务，再固定当前 revision/state/sync generation
执行快进。候选完整状态链必须包含备节点当前状态；完整旧目录会原子移到指定同级路径：

```powershell
python tools/pdr.py contract-package registry-standby-sync `
  --recovery-point F:/offsite/product-contracts-00047.pdrregistry `
  --expected-recovery-point-sha256 $newRecoveryPointSha256 `
  --destination D:/standby/product-contract-registry `
  --standby-id contracts-oslo-02 --sync-id sync-00047 `
  --operator standby.sync `
  --expected-revision 42 --expected-state-sha256 $standbyStateSha256 `
  --expected-sync-generation 1 --confirm-standby-stopped `
  --previous-output D:/standby/product-contract-registry.previous-42 `
  --operation-audit E:/external-audit/standby-operations.jsonl `
  --anchor-policy E:/external-audit/registry-anchor-policy.json `
  --expected-anchor-policy-id product-registry-auditors `
  --expected-anchor-policy-sha256 $anchorPolicySha256 `
  --trust-policy contracts/team-contract-trust-policy.json `
  --expected-trust-policy-id product-team-contracts `
  --expected-trust-policy-sha256 $packagePolicySha256
```

`.pdr-standby.json` 由 Registry 核心识别，因此本地或远程 publish/promote/rollback 最终都会在写入
内核处拒绝；`registry-verify`、`registry-resolve` 和 `registry-standby-status` 仍可用于只读验证。
standby 不是可自行提升的 primary。远程只读服务的 control directory 必须放在 Registry 根目录之外，
避免同步目录切换时丢失 request/audit 状态；不能通过删除 standby marker 绕过晋升协议。

### 外部 Leader 授权与 fencing

需要主备切换时，把 Leader authority、信任策略、公钥和操作审计放在所有 Registry 目录之外，并由
独立控制面提供强 ACL、持久化与防回退保护。authority 每次只原子发布一个签名 `current-grant.json`，
同时保留从 token 1 开始的完整不可变 grant 链；grant 最长有效 24 小时。

首次把现有主节点纳入控制时，按它的精确 revision/state 签发 token 1，再显式激活：

```powershell
python tools/pdr.py contract-package registry-leader-issue `
  --authority E:/external-leader/product-contracts `
  --authority-id product-contracts-leader --registry-id product-contracts `
  --purpose leadership --leader-id contracts-oslo-01 `
  --expected-current-token 0 --expected-current-grant-sha256 $('0' * 64) `
  --baseline-revision 47 --baseline-state-sha256 $primaryStateSha256 `
  --issued-at $issuedAt --not-before $notBefore --expires-at $expiresAt `
  --key-id product-leader-authority-2026 `
  --private-key-environment PDR_LEADER_PRIVATE_KEY `
  --leader-trust-policy E:/external-leader/trust/policy.json `
  --expected-leader-trust-policy-id product-leader-authorities `
  --expected-leader-trust-policy-sha256 $leaderPolicySha256 `
  --operator ha.control --operation-audit E:/external-audit/leader.jsonl

python tools/pdr.py contract-package registry-leader-activate `
  --registry D:/primary/product-contract-registry --node-id contracts-oslo-01 `
  --current-grant E:/external-leader/product-contracts/current-grant.json `
  --expected-current-grant-sha256 $grant1Sha256 --confirm-enroll-primary `
  --operator ha.control --operation-audit E:/external-audit/leader.jsonl `
  --leader-trust-policy E:/external-leader/trust/policy.json `
  --expected-leader-trust-policy-id product-leader-authorities `
  --expected-leader-trust-policy-sha256 $leaderPolicySha256 `
  --trust-policy contracts/team-contract-trust-policy.json `
  --expected-trust-policy-id product-team-contracts `
  --expected-trust-policy-sha256 $packagePolicySha256
```

默认 `--authority` 文件后端适合单机控制面和确定性测试。生产多节点控制面可由独立团队实现
`read-current`、`read-grant`、`compare-and-swap` 三操作的外部进程适配器，把状态落在 etcd 等具备
线性一致 CAS 和防回退能力的存储中。Runtime 不依赖具体客户端库；配置固定适配器 scope、可执行文件、
附属制品、允许透传的环境变量、超时和最大响应：

```json
{
  "schemaVersion": 1,
  "product": "PocoDDSRuntimeTeamContractRegistryLeaderBackendConfig",
  "backendId": "product-contracts-etcd",
  "kind": "external-command",
  "protocolMajor": 1,
  "minimumProtocolMinor": 0,
  "requiredCapabilities": [
    "atomic-compare-and-swap",
    "commit-outcome-reconciliation",
    "immutable-history",
    "linearizable-read-current",
    "scope-confinement"
  ],
  "authorityIds": ["product-contracts-leader"],
  "registryIds": ["product-contracts"],
  "executable": "C:/Program Files/PDR/pdr-etcd-leader-adapter.exe",
  "executableSha256": "<adapter-executable-sha256>",
  "arguments": [],
  "artifactPins": [],
  "environmentVariables": ["PDR_ETCD_ENDPOINTS", "PDR_ETCD_CLIENT_CERT"],
  "timeoutSeconds": 5,
  "maxResponseBytes": 65536
}
```

schema v2 在任何存储操作前发送独立 Capability Request，严格校验 request/backend 身份、协议 major、最低
minor 和语义能力集合。major 不一致、minor 低于策略或缺少任一 required capability 都会停止；不会把
“命令能运行”误当成“事务语义兼容”。旧 schema v1 仍可显式加载，便于已有团队迁移，但它没有协商证据，
不能通过 `registry-leader-backend-capabilities` 放行。新 SDK 生成器只产生 v2。

签发和激活都固定配置原始字节 SHA。外部绑定使用 schema v2，只保存 backend ID、配置路径/SHA 和
当前 grant SHA，不保存共享 `current-grant.json` 路径；每次 publish/promote/rollback 及提交前复核都会
重新查询权威后端：

```powershell
python tools/pdr.py contract-package registry-leader-issue `
  --authority-backend-config E:/leader-control/etcd-backend.json `
  --expected-authority-backend-config-sha256 $backendConfigSha256 `
  --authority-id product-contracts-leader --registry-id product-contracts `
  --purpose leadership --leader-id contracts-oslo-01 `
  --expected-current-token 0 --expected-current-grant-sha256 $('0' * 64) `
  --baseline-revision 47 --baseline-state-sha256 $primaryStateSha256 `
  --not-before $notBefore --expires-at $expiresAt `
  --key-id product-leader-authority-2026 `
  --private-key-environment PDR_LEADER_PRIVATE_KEY `
  --operator ha.control `
  --leader-trust-policy E:/external-leader/trust/policy.json `
  --expected-leader-trust-policy-id product-leader-authorities `
  --expected-leader-trust-policy-sha256 $leaderPolicySha256

python tools/pdr.py contract-package registry-leader-activate `
  --registry D:/primary/product-contract-registry --node-id contracts-oslo-01 `
  --authority-backend-config E:/leader-control/etcd-backend.json `
  --expected-authority-backend-config-sha256 $backendConfigSha256 `
  --authority-id product-contracts-leader `
  --expected-current-grant-sha256 $grant1Sha256 --confirm-enroll-primary `
  --operator ha.control --operation-audit E:/external-audit/leader.jsonl `
  --leader-trust-policy E:/external-leader/trust/policy.json `
  --expected-leader-trust-policy-id product-leader-authorities `
  --expected-leader-trust-policy-sha256 $leaderPolicySha256 `
  --trust-policy contracts/team-contract-trust-policy.json `
  --expected-trust-policy-id product-team-contracts `
  --expected-trust-policy-sha256 $packagePolicySha256
```

适配器通过 stdin/stdout 交换安装 SDK 中定义的 JSON 合同；签名仍在 authority 命令侧完成，配置若尝试把
本次签发使用的私钥或 passphrase 环境变量加入透传白名单会直接被拒绝。
CAS 必须同时比较 `expectedCurrentToken` 和 `expectedCurrentGrantSha256`，成功后持久保存新 grant 的逐字节
内容及不可变历史，并让随后的 `read-current` 立即看到相同字节。适配器超时或不可用时系统选择停止写入，
不会回退到缓存或文件后端；CAS 请求发出后若响应或 read-back 丢失，会返回 `COMMITTED_ERROR`，运维必须先
读取权威 current 再决定重试，不能假定未提交。绑定后的后端类型也不能通过普通 renewal 静默改变。

### Leader Backend 独立验收

适配器仓库无需复制 Runtime 测试或取得 authority 签名私钥。先生成独立的能力协商证据：

```powershell
python tools/pdr.py contract-package registry-leader-backend-capabilities `
  --backend-config E:/adapter-validation/backend.json `
  --expected-backend-config-sha256 $backendConfigSha256 `
  --authority-id adapter-team-conformance-authority-0001 `
  --registry-id adapter-team-conformance-registry-0001 `
  --report E:/adapter-validation/capability-evidence.json
```

报告绑定实现 ID、协议版本、声明/要求的能力集合、配置 SHA-256 和规范化能力清单 SHA-256。随后运行安装 SDK
提供的正式 Conformance 命令；它会
在指定 scope 写入合成 token 1，执行缺失历史、逐字节 current/history、陈旧 CAS、两个不同 token 2 候选
并发竞争和 loser 不落盘检查，并输出摘要绑定证据：

```powershell
$backendConfigSha256 = (Get-FileHash `
  E:/adapter-validation/backend.json -Algorithm SHA256).Hash.ToLower()

python tools/pdr.py contract-package registry-leader-backend-conformance `
  --backend-config E:/adapter-validation/backend.json `
  --expected-backend-config-sha256 $backendConfigSha256 `
  --authority-id adapter-team-conformance-authority-0001 `
  --registry-id adapter-team-conformance-registry-0001 `
  --confirm-dedicated-empty-scope `
  --report E:/adapter-validation/conformance-evidence.json
```

该命令会真实提交 token 1 和一个竞争胜出的 token 2，不提供 delete/cleanup 操作。authority ID 与 Registry ID
必须是专门为本次验收分配的空 scope；已有 current 时直接拒绝，成功后的 scope 应连同报告保留为适配器版本
证据，下一版本使用新的 scope。v2 Conformance 报告同时绑定协商后的协议版本和能力清单摘要。通过只证明
适配器满足 PDR 的存储/CAS 协议，不替代实际 etcd/Consul 集群的
TLS、ACL、quorum、快照恢复、跨故障域和长稳验收。

安装 SDK 还提供
`share/PocoDDSRuntime/examples/team-contract-registry-leader-backend-file/` 参考工程。其中
`create_backend_config.py` 生成固定 Python、适配器及 scope 的配置，`file_backend_adapter.py` 给出独立进程、
跨进程锁、逐字节不可变历史、`fsync` 和原子 current 替换的最小实现。SDK 外部 Consumer 会从安装目录
实际生成配置并执行上述 Conformance，因此示例不是仅存在于源码树中的伪样例。该文件实现仍是单机教学
后端；生产适配器团队应保留 JSON 边界和验收测试，只替换持久化/CAS 层，并补充目标集群验收。

### Leader Backend 受控迁移与回滚

普通 renewal 继续禁止改变 `authorityBackend`。后端升级必须先把不可变 grant 链在线同步到具备 v2 能力协商
的独立 target：

```powershell
python tools/pdr.py contract-package registry-leader-backend-migration-sync `
  --migration-id product-contracts-etcd-v2 `
  --authority-id product-contracts-leader --registry-id product-contracts `
  --source-backend-config E:/leader-control/etcd-v1.json `
  --expected-source-backend-config-sha256 $sourceSha `
  --target-backend-config E:/leader-control/etcd-v2.json `
  --expected-target-backend-config-sha256 $targetSha `
  --confirm-target-migration-scope `
  --transaction-backend-config E:/leader-control/migration/transaction-store.json `
  --expected-transaction-backend-config-sha256 $transactionStoreSha `
  --artifact-store-config E:/leader-control/migration/artifact-store.json `
  --expected-artifact-store-config-sha256 $artifactStoreSha `
  --actor ha.operator `
  --output E:/leader-control/migration/online-sync.json
```

Sync 只接受空 target 或与 source 逐字节相同的完整前缀；target 超前、历史分叉或同步期间 source 变化都会
停止。事务存储复用 Leader Backend SPI：本地可以继续使用 `--transaction <绝对路径>` 和进程租约，跨主机则
使用上述固定配置。该配置必须把 `migrationId` 放入 `authorityIds`、把 Registry ID 放入 `registryIds`；每个
Migration ID 因而拥有独立 current/history scope。外部存储要求 schema v2 能力协商，事务 `stateVersion` 同时
作为单调 fencing token，`previousGrantSha256` 固定前一状态；etcd 适配器以同一个原子事务比较 current、确认
history 不存在并写入两者。配置 Artifact Store 后，事务升级为 schema v3：证据字段只保存
`storeId/namespaceId/sha256/sizeBytes/mediaType`，不再保存操作者主机路径；每次 Put 都执行写后读和逐字节摘要
校验。交接人员必须先读取当前 SHA，而不是覆盖前一位操作者的状态：

```powershell
python tools/pdr.py contract-package registry-leader-backend-migration-status `
  --transaction-backend-config E:/leader-control/migration/transaction-store.json `
  --expected-transaction-backend-config-sha256 $transactionStoreSha `
  --artifact-store-config E:/leader-control/migration/artifact-store.json `
  --expected-artifact-store-config-sha256 $artifactStoreSha `
  --migration-id product-contracts-etcd-v2 --registry-id product-contracts `
  --registry D:/primary/product-contract-registry `
  --report E:/leader-control/migration/status.json
```

完成在线预热后，在 source 签发下一 `purpose=fence` grant，再以 Status 返回的
`transactionSha256` 续作到新的证据路径：

```powershell
python tools/pdr.py contract-package registry-leader-backend-migration-resume `
  --transaction-backend-config E:/leader-control/migration/transaction-store.json `
  --expected-transaction-backend-config-sha256 $transactionStoreSha `
  --artifact-store-config E:/leader-control/migration/artifact-store.json `
  --expected-artifact-store-config-sha256 $artifactStoreSha `
  --migration-id product-contracts-etcd-v2 --registry-id product-contracts `
  --expected-transaction-sha256 $transactionSha `
  --actor handoff.operator --confirm-target-migration-scope `
  --output E:/leader-control/migration/fence-sync.json
```

旧 SHA 会被拒绝，因此两位操作者不能各自基于过期状态推进。若 Backend 已完成同步并写出证据、但进程在更新
事务前中断，可用 `registry-leader-backend-migration-reconcile --sync-evidence ...
--expected-sync-evidence-sha256 ...` 接纳该孤儿 checkpoint；工具会重新读取双方链，只有固定前缀仍逐字节一致
时才更新事务。随后在 target
基于该 fence 签发直接后继的 leadership grant，并生成切换证据：

```powershell
python tools/pdr.py contract-package registry-leader-backend-migration-finalize `
  --migration-id product-contracts-etcd-v2 `
  --registry D:/primary/product-contract-registry `
  --authority-id product-contracts-leader --registry-id product-contracts `
  --sync-evidence E:/leader-control/migration/fence-sync.json `
  --expected-sync-evidence-sha256 $syncSha `
  --expected-target-grant-sha256 $targetLeadershipSha `
  --trust-policy contracts/team-contract-trust-policy.json `
  --expected-trust-policy-id product-team-contracts `
  --expected-trust-policy-sha256 $packagePolicySha `
  --transaction-backend-config E:/leader-control/migration/transaction-store.json `
  --expected-transaction-backend-config-sha256 $transactionStoreSha `
  --artifact-store-config E:/leader-control/migration/artifact-store.json `
  --expected-artifact-store-config-sha256 $artifactStoreSha `
  --expected-transaction-sha256 $transactionShaAfterResume `
  --actor ha.operator `
  --output E:/leader-control/migration/cutover.json

python tools/pdr.py contract-package registry-leader-activate `
  --registry D:/primary/product-contract-registry --node-id contracts-oslo-01 `
  --authority-backend-config E:/leader-control/etcd-v2.json `
  --expected-authority-backend-config-sha256 $targetSha `
  --authority-id product-contracts-leader `
  --expected-current-grant-sha256 $targetLeadershipSha `
  --backend-migration-evidence E:/leader-control/migration/cutover.json `
  --expected-backend-migration-evidence-sha256 $cutoverSha `
  <其余 Registry 与 Leader trust 参数>
```

Activate 在 Registry process lease 内再次检查旧 binding、source fence、target leadership、Registry baseline、
同步证据和全部摘要，然后写 schema v3 binding。切换不是危险的双主双写：它保留一个短暂但明确的 fence
间隙。Activate 成功后再以 cutover 证据运行 `registry-leader-backend-migration-reconcile`，事务才从
`prepared` 进入 `completed`；这使接手人员能够区分“证据已准备”和“binding 已切换”。

`--output` 仍会保留一份便于人工检查和激活的本地导出，但 schema v3 事务的权威证据是 Artifact Store 引用；
删除本地 sync 导出后，Status、Resume 和 Abort 仍从内容寻址存储验证证据。需要在另一主机生成激活/Finalize
输入时，可以只传递引用文件：

```powershell
python tools/pdr.py contract-package artifact-store-get `
  --config E:/leader-control/migration/artifact-store.json `
  --expected-config-sha256 $artifactStoreSha `
  --namespace-id product-contracts-etcd-v2 `
  --reference E:/handoff/fence-sync.reference.json `
  --output E:/handoff/fence-sync.json
```

安装 SDK 的 `examples/team-contract-artifact-store-file/` 是协议参考实现，适合单机或共享文件系统。生产团队可
在不修改迁移工具的情况下实现 S3、MinIO 或 Blob 适配器；仍须通过命名空间隔离、不可变创建、写后读、缺失
对象和篡改失败关闭验收。Artifact Store 不承担事务 CAS，Transaction Store 也不承担大对象传输，两者职责独立。

跨主机接管还不能把 source/target 的本机 `configPath` 写入共享事务。安装 SDK 的
`examples/team-contract-backend-config-resolver-file/` 为此提供第三个独立 SPI：共享状态只保存
`resolverId/configId/backendId/revision`，每台操作者主机用自己固定摘要的 resolver config 和 mapping 解析到
本机 backend config。相同逻辑引用允许解析到不同安装目录和不同 backend config SHA，但解析后的 backend ID、
authority/Registry scope、能力清单和本地制品 pin 仍须全部通过。mapping 不得保存秘密值；凭据继续由后端配置
声明的环境变量或专用凭据提供器注入。

```powershell
$sourceRefSha = (Get-FileHash E:/handoff/source-ref.json -Algorithm SHA256).Hash.ToLower()
$targetRefSha = (Get-FileHash E:/handoff/target-ref.json -Algorithm SHA256).Hash.ToLower()
$resolverSha = (Get-FileHash E:/leader-control/backend-resolver.json -Algorithm SHA256).Hash.ToLower()

python tools/pdr.py contract-package registry-leader-backend-migration-sync `
  --migration-id product-contracts-etcd-v3 `
  --authority-id product-contracts-authority --registry-id product-contracts `
  --source-backend-ref E:/handoff/source-ref.json `
  --expected-source-backend-ref-sha256 $sourceRefSha `
  --target-backend-ref E:/handoff/target-ref.json `
  --expected-target-backend-ref-sha256 $targetRefSha `
  --backend-config-resolver-config E:/leader-control/backend-resolver.json `
  --expected-backend-config-resolver-config-sha256 $resolverSha `
  --transaction-backend-config E:/leader-control/transaction-backend.json `
  --expected-transaction-backend-config-sha256 $transactionStoreSha `
  --artifact-store-config E:/leader-control/artifact-store.json `
  --expected-artifact-store-config-sha256 $artifactStoreSha `
  --confirm-target-migration-scope --actor ha.operator `
  --output E:/handoff/initial-sync.json
```

该组合生成 schema v4 transaction 和 schema v2 sync/cutover evidence。Status、Resume、Finalize、Reconcile、Abort
以及使用 v2 cutover evidence 的 Activate 都必须传入当前主机的 resolver config；共享 transaction/evidence 中不再
出现 backend config 路径。`backend-config-resolve` 可在正式操作前单独检查某个引用的本机解析结果和摘要证据。

只有 Status 显示 source 仍是绑定的 `leadership` 且 target 只是其精确前缀时，
`registry-leader-backend-migration-abort` 才会写不可变终止证据并把事务置为 `aborted`。目标历史为审计而保留，
不会删除。source 一旦 Fence、双方分叉或 binding 已切换，Abort 必须拒绝；此时只能完成切换，或创建新事务
交换 source/target 走受控回滚。`completed` 和 `aborted` 都是终态，Resume 会拒绝。回滚使用完全相同的流程，
只需交换 source/target；不能通过复制配置或普通 renewal 绕过。

### etcd 生产适配路径

安装 SDK 的 `examples/team-contract-registry-leader-backend-etcdctl/` 提供不向 Runtime 泄漏 etcd 客户端依赖的
独立适配器。配置生成器要求至少三个不同的 HTTPS endpoint，固定 Python、适配器、`etcdctl`、CA、客户端
证书、私钥和附属制品 SHA；所有 key 收敛在专用 `keyPrefix`。适配器先执行线性一致 current 读取，再由
[`etcdctl txn`](https://github.com/etcd-io/etcd/blob/main/etcdctl/README.md#txn-options) 同时比较 current 原始值、
确认目标 history 不存在，并原子写 history/current。并发者无法基于同一前驱提交不同的新 grant。

真实集群必须先启用客户端证书认证和 RBAC，并让证书 CN 对应的 etcd 用户只拥有该 `keyPrefix`；etcd 默认
不会自动启用这些安全能力。生成配置后可单独运行只读预检：

```powershell
$adapterConfigSha256 = (Get-FileHash `
  E:/leader-control/etcd-adapter.json -Algorithm SHA256).Hash.ToLower()

python E:/PocoDDSRuntime/build/install/bin/pdr.py contract-package registry-leader-etcd-preflight `
  --config E:/leader-control/etcd-adapter.json `
  --expected-config-sha256 $adapterConfigSha256 `
  --report E:/leader-control/etcd-cluster-preflight.json
```

预检查询所有 endpoint 的 health/status，要求它们属于同一 cluster、member ID 唯一、观察到同一个已选
Leader、Raft applied index 不超过 commit index，并执行命名空间内的线性只读探测。版本放行时推荐改用
一次性 Acceptance，把写入前预检、专用空 scope 的 Backend Conformance 和写入后预检绑定到同一目录：

```powershell
$backendConfigSha256 = (Get-FileHash `
  E:/leader-control/etcd-backend.json -Algorithm SHA256).Hash.ToLower()

python E:/PocoDDSRuntime/build/install/bin/pdr.py contract-package registry-leader-etcd-acceptance `
  --adapter-config E:/leader-control/etcd-adapter.json `
  --expected-adapter-config-sha256 $adapterConfigSha256 `
  --backend-config E:/leader-control/etcd-backend.json `
  --expected-backend-config-sha256 $backendConfigSha256 `
  --authority-id product-contracts-etcd-acceptance-0001 `
  --registry-id product-contracts-etcd-acceptance-0001 `
  --confirm-dedicated-empty-scope `
  --output-directory E:/leader-control/acceptance/product-contracts-etcd-v1
```

输出目录必须是尚不存在的绝对路径。成功后保留 `preflight-before.json`、`conformance.json`、
`preflight-after.json` 和绑定前三者 SHA-256 的 `acceptance.json`，不自动清理已提交的 token 1/token 2。
写入前失败返回 2；一旦可能已经提交但后置检查或证据收敛失败，则保留现场、写
`acceptance-failure.json` 并返回 3，操作者必须先对账，不能直接换目录重跑。上线前还应完成真实三节点
断网、失主、证书/RBAC 拒绝、快照恢复及长稳测试。

跨节点切换使用 drain + fence + handoff 的显式流程。先持久关闭远程命令入口；状态写入远程 control
directory，服务端会在创建 idempotency request 之前拒绝包括只读命令在内的所有新 command：

```powershell
python tools/pdr.py contract-package registry-drain-start `
  --registry D:/primary/product-contract-registry `
  --control-directory E:/registry-control/product-contracts `
  --registry-id product-contracts --node-id contracts-oslo-01 `
  --handoff-id handoff-00048 --expected-generation 0 `
  --expected-revision 47 --expected-state-sha256 $primaryStateSha256 `
  --operator ha.control --reason 'planned failover'
```

处理所有遗留 pending request 后签发下一 token 的 `purpose=fence` grant，再由旧主完成 drain。finalize 会
确认 Registry 未变化、pending 集合为空、旧主实际观察到当前 fence token，并签出最长一小时的交接证据：

```powershell
python tools/pdr.py contract-package registry-drain-finalize `
  --registry D:/primary/product-contract-registry `
  --control-directory E:/registry-control/product-contracts `
  --registry-id product-contracts --node-id contracts-oslo-01 `
  --handoff-id handoff-00048 --expected-generation 1 `
  --expected-revision 47 --expected-state-sha256 $primaryStateSha256 `
  --operator ha.control --issued-at $issuedAt --expires-at $expiresAt `
  --key-id contracts-oslo-01-handoff-2026 `
  --private-key-environment PDR_HANDOFF_PRIVATE_KEY `
  --output E:/external-leader/handoff-00048.json
```

随后从旧主最终状态创建恢复点、快进备节点，并签发下一 token 的 leadership grant。跨节点
`registry-leader-issue` 必须同时提供 `--handoff-evidence`、固定 handoff trust policy ID/SHA；grant 会
记录 evidence SHA。最后对备节点执行 `registry-leader-activate`，它先落盘 leader binding，再移除
standby marker，任一步中断都保持只读。

直接从一个 Leader ID 签发另一个 Leader ID 会被拒绝。每个受管 Registry 还保存
`.pdr-fencing.json` 高水位：节点一旦观察到更高的有效签名 token，就拒绝外部 authority 回放旧 grant。
所有 publish/promote/rollback 都在获得进程租约后检查 grant，并在 `registry.json` 指针提交前再次检查。
旧主只有重新获得同节点有效 leadership grant 才能执行 `registry-drain-resume`；已转移后无法重新开放入口。
默认文件型 authority 提供确定性的单写者协议，但它本身不是 Raft/etcd；若该存储可被整体回退，且旧主
从未观察到 fence token，仍需由基础设施隔离旧主。生产多节点部署应使用上述 SPI，把 authority 承载在
具备线性一致性、CAS 和防回退能力的控制存储中；适配器协议不会把弱一致后端自动变成安全的 Leader authority。

运维端不需要登录旧主或读取其 Registry、control directory 和签名密钥。远程服务配置上述 node ID、
外部 evidence directory 与 handoff signer 后，具备 `operator` 角色的 token 可通过同一 RBAC/TLS 控制面
完成 start/status/finalize/resume；请求只携带公开身份和精确状态前置条件：

```powershell
python tools/pdr.py contract-package registry-remote-drain-start `
  --url https://contracts-oslo-01.example.internal:9443 `
  --registry-id product-contracts --handoff-id handoff-00048 `
  --expected-generation 0 --expected-revision 47 `
  --expected-state-sha256 $primaryStateSha256 `
  --reason 'planned failover' --token-environment PDR_TEAM_REGISTRY_OPERATOR_TOKEN

python tools/pdr.py contract-package registry-remote-drain-status `
  --url https://contracts-oslo-01.example.internal:9443 `
  --registry-id product-contracts `
  --token-environment PDR_TEAM_REGISTRY_OPERATOR_TOKEN

python tools/pdr.py contract-package registry-remote-drain-finalize `
  --url https://contracts-oslo-01.example.internal:9443 `
  --registry-id product-contracts --handoff-id handoff-00048 `
  --expected-generation 1 --expected-revision 47 `
  --expected-state-sha256 $primaryStateSha256 `
  --issued-at $issuedAt --expires-at $expiresAt `
  --evidence-output E:/external-leader/handoff-00048.json `
  --token-environment PDR_TEAM_REGISTRY_OPERATOR_TOKEN
```

服务端用确定性的 `<handoff-id>-generation-<generation>.json` 保存证据；完全相同的 start/finalize 重试
返回 `replayed=true`，finalize 重试下载原有字节，不会再次签名。不同前置条件、非 operator、未排空、
存在 pending request、未观察新 fence、Registry 状态漂移或旧节点已被 fence 都会 fail-closed。resume 同样
走远程接口，但仅适用于尚未失去有效同节点 leadership grant 的取消切换场景。

## Secret Provider v2 与 Backend schema v3/v4

Backend 不再需要把认证材料写入配置或共享迁移事务。schema v3 增加固定的 `secretProvider` 描述符和
`credentialBindings`；每个 binding 只携带目标子进程环境变量名以及
`{kind:"secret-ref", providerId, secretId, version}`。调用路径先重新校验 Provider 配置、可执行程序、适配器
和 mapping SHA，再协商 `bounded-secret/no-secret-persistence/scoped-read/version-pinned-read`，最后按请求解析。
解析值必须为非空 UTF-8、不能含 NUL，并只存在于当前 Backend 子进程环境；能力协商不会读取凭据。

`pdr.py contract-package secret-provider-check` 提供运维预检，但报告故意不包含秘密值、摘要或长度，避免低熵
凭据被离线猜测。环境变量参考 Provider 仅供迁移与测试；生产实现应使用 Credential Manager、Vault、云
Secret Manager/KMS 或 workload identity。缺失、版本不符、越权引用、Provider 身份变化或任一固定制品漂移
都会在 Backend 子进程启动前失败。Provider schema v1 与 Backend schema v1/v2/v3 保持兼容。

Provider schema v2 返回 `issuedAt/expiresAt/selectedVersion` 租约，并协商
`leased-secret/rotation-fallback/revocation-aware`。轮换引用显式保存有序新旧版本和 `fallbackUntil`；新版本
可用时立即优先，新版本尚未投放或已撤销时只能在窗口内使用旧版本，窗口结束后失败关闭。Backend schema v4
再要求 `minimumCredentialLeaseSeconds >= timeoutSeconds + 1`，每次启动子进程前确认租约覆盖完整操作窗口。
Provider 的必需运行环境与可选秘密来源 allowlist 分离，允许版本分阶段投放，同时拒绝继承无关宿主变量。

Backend、Secret Provider、Artifact Store 和 Backend Config Resolver 的外部进程执行已统一使用
[`team_contract_adapter_runtime.py`](team-contract-adapter-runtime.md)。新增 Adapter 不应复制 `Popen`、超时轮询、
环境构造或 stdout/stderr 读取逻辑；协议模块只保留身份、scope 和业务响应校验。公共层变更必须同时通过四类
协议集成测试、安装 SDK 和 PDR-REC-0037。

跨团队部署不再要求把每种新 Adapter 写入核心注册表。Adapter 团队生成摘要固定的 Manifest，部署 Owner 把
Manifest 摘要写入 Host 本地 Catalog；`pdr.py contract-package adapter-catalog-list/check` 随后完成声明式发现和
只读 Capability 健康检查。Catalog 仅统一发现与能力观察，不提供通用业务调用：各协议宿主仍独立执行完整的
request/response、身份、scope 和一致性校验。安装 SDK 的 `examples/team-contract-adapter-catalog/` 提供生成器，
PDR-REC-0038 验证未知类型无需核心代码注册、传递 pin 和失败关闭边界。

Host 部署通过 `adapter-catalog-activate` 把固定 Catalog 写入内容寻址状态库，再原子切换唯一 pointer。
写者使用跨进程 lease/fencing epoch、expected generation CAS 和唯一 operation ID；精确重试幂等，冲突重放、
并发旧写及 Catalog generation 降级均拒绝。`adapter-catalog-current/current-check` 为消费者提供经过完整 state 链
与传递 pin 验证的当前快照，探测期间 pointer 改变会丢弃结果。`adapter-catalog-rollback` 只选择历史已验证
Catalog，并以前进的新 activation generation 留下审计记录。PDR-REC-0039 覆盖该生命周期边界。

长运行消费者更新由 `adapter-catalog-reconcile/recover/status` 管理。Reconciler 固定并协商外部 lifecycle Hook，按
prepare、零 pending drain、Catalog CAS switch、activate、有限 health gate、commit 顺序推进。每次副作用前写入
自摘要 journal；中断恢复依赖稳定 transaction operation ID，不重复创建 Catalog generation。切换前失败 abort，
切换后失败自动创建精确源 Catalog 的前进式 rollback generation；rollback Hook 失败可再次恢复。PDR-REC-0040
覆盖进程中断、持续不健康、首次 rollback 失败、重放冲突、pin 漂移、journal 篡改和 stderr 脱敏。
已 committed 事务不能由 Fleet 或操作者直接覆盖 Catalog pointer；必须调用
`adapter-catalog-reconcile-revert`，由原 journal、源摘要和同一 lifecycle Hook 完成前进式、幂等撤销。

多 Host 发布由 `adapter-catalog-fleet-run/recover/status` 管理。摘要固定的 Fleet Plan 把第一波零失败 Canary、
后续 wave、每波失败预算、节点故障域、源 activation generation 和最大并发绑定为一次 rollout；Node Executor
SPI 隔离 SSH/WinRM/Kubernetes/代理等传输实现。协调器只接受能力协商后的幂等节点 deploy/status/revert，节点
实际变更仍由各自 Reconciler 完成。任一 wave 超预算立即停止后续准入，并按 wave/节点逆序撤销已经 committed
的节点；pending 节点不变。自摘要 Fleet journal 支持节点完成但协调器未收到响应的恢复，PDR-REC-0041 覆盖。

Fleet Plan v2 在 Node Executor 之外固定独立 Wave Gate SPI。每个 wave 的 `gatePolicy` 声明最短观察时间、最大
判定次数和拒绝动作；观察期只持久化 `waiting` 后返回，不占用长运行进程。Gate 只看到脱敏节点计数并返回
`pass/pause/fail` 与证据 SHA。暂停后普通 recover 不会绕过，`fleet-resume/fleet-abort` 使用 control generation
CAS、唯一 operation ID、actor 和 reason 记录人工决定；abort 继续复用节点 Reconciler 的逆序撤销。Plan v1
保持兼容，PDR-REC-0042 覆盖 Gate 响应歧义、SLO 暂停、观察窗口、人工控制、篡改、pin 和脱敏。

Fleet Plan v3 再固定独立 Control Authorizer SPI，解决 v2 actor 仅由调用方自报的问题。Authorizer 只接收
operation/action、claimed actor、control generation、Gate/Catalog 摘要和 reason SHA，返回 allow/deny、
认证 Principal、证据 SHA 与稳定诊断码。Principal 不匹配、适配器异常和无明确决定均失败关闭；deny 会进入
自摘要授权历史，但不改变 rollout 或 control generation。稳定 authorization ID 使响应丢失可安全重试，已经
拒绝的 operation ID 不受后续环境策略变化影响。允许控制继续复用 v2 CAS、幂等 resume/abort 与 Reconciler
逆序回滚。Plan v1/v2 保持兼容，PDR-REC-0043 覆盖授权故障注入和安装 SDK。

Fleet Plan v4 使用既有 Registry Leader Backend 的线性 CAS 保存一个小型 State Pointer，并把每版完整 journal
作为不可变内容写入既有 Artifact Store。Plan 仅固定两个适配器的 ID 和配置 SHA；各协调 Host 可用不同本地
配置路径及空 scratch 目录接管同一 rollout。每次写入增加 `stateVersion/fencingToken` 并连接前一 Pointer 与
journal 摘要，旧协调器 CAS、缺失或篡改的 blob、scope/pin 漂移均失败关闭；提交响应丢失通过读回当前 Pointer
消歧。Plan v1-v3 保持本地 journal 兼容，PDR-REC-0044 验证跨主机接管边界。

Fleet Plan v5 进一步去除 Executor、Wave Gate、Control Authorizer、State Backend 和 Artifact Store 的全部
本机配置路径及配置 SHA。Plan 为五类 Adapter 保存统一 `adapter-config-ref`，包含 Resolver/Config/Adapter ID、
Adapter 类型和 revision；每个协调 Host 用自身固定摘要的 Adapter Config Resolver 将同一引用解析到本机配置。
Resolver 请求绑定 `adapter-catalog-fleet -> rolloutId -> catalogId` scope，返回配置仍需通过对应 Adapter 的完整
配置、制品 pin 和能力协商校验。远端 Pointer schema v2 与 journal v5 也只保存逻辑引用，因此 Host A 与 Host B
的 Resolver 配置、映射路径以及五类 Adapter 配置摘要可以不同，同时不能改变逻辑 Adapter 身份。v1-v4 保持
兼容；PDR-REC-0045 覆盖跨 Host 逻辑引用接管、类型/版本/scope/pin 漂移与失败关闭。

## 统一 Adapter Conformance Kit

`adapter-conformance` 为七类公共边界提供同一认证入口：Fleet Executor、Wave Gate、Control Authorizer、
Registry Leader Backend、Artifact Store、Adapter Config Resolver 和 Governance Approval Signer。它复用各模块自己的
严格 config loader 与 capability negotiation，不维护第二份协议解释。认证会重复协商以验证能力摘要稳定性，
重新验证 executable/artifact/config pin，主动提交错误 config SHA 验证失败关闭，检查环境 allowlist 和进程
timeout/response-size 策略，并生成自摘要 `PocoDDSRuntimeTeamContractAdapterConformanceEvidence`。

证据的 `conformanceId` 只由逻辑 Adapter 身份、配置/能力摘要、scope、协议和 check-set 版本计算，因此同一
固定配置的重复认证不受报告路径和时间影响；不同 Host 的本地配置 SHA 不同时应得到不同 ID。
`certifiedAt/reportSha256` 提供本次运行的审计身份。报告明确不包含配置路径、配置
内容、命令参数或环境值，适合由 Adapter 团队交付给集成团队。`integration-readiness` 只证明公共适配层边界，
不能替代 etcd/对象存储/IAM/节点部署的真实环境 acceptance。PDR-REC-0046 覆盖 pin、replay、scope、漂移、
脱敏、自摘要和安装 CLI。

Governance Approval Signer 使用 `--adapter-kind governance-approval-signer`，并通过 `--scope-primary` 固定
唯一 `approverId`。证据绑定 signer ID、approver scope、配置 SHA、完整 purpose/key capability 摘要；签名器团队
可重复生成稳定 conformance ID，独立认证团队再使用 `adapter-conformance-attest` 对精确 evidence SHA、kind/ID、
config SHA 与 approver scope 签名。现有 Adapter Conformance Trust Policy 可把 Certifier 权限限制到
`governance-approval-signer` 和明确 signer ID，并复用有效期、撤销、轮换和最低 generation 检查。
该公共认证注册不会把 Signer 加入 Fleet v6 的六类强制 rollout admission；两种准入集合保持明确分离。

## Fleet v6 Adapter Conformance Admission

Fleet Plan v6 通过 `adapterConformancePolicy` 声明认证等级、check-set、证据最大年龄、六类必需 Adapter 和
九项必需检查。协调 Host 使用 `adapter-conformance-admission-create` 将六份 evidence 组成 Host 本地 bundle，
执行 `run/recover/resume/abort/status` 时同时传入 bundle 路径及预期 SHA。准入在业务调用前复核 bundle/evidence
摘要、认证时间、Adapter ID、配置 SHA、protocol、scope、required capabilities，并在真实能力协商后再次比对
capability manifest SHA；任一项不一致均失败关闭。

Plan、远程 Pointer 和 journal 都不保存 evidence/config 的本地路径。journal v6 仅追加 policy、bundle、
conformance、config、capability 和 evidence 的摘要身份，所以另一个 Host 可以使用不同路径和不同固定 bundle
接管同一 rollout，同时保留可追溯的两次 admission。integration-readiness 仍不能替代生产环境 acceptance。

## Fleet v7 Signed Adapter Conformance Trust

Fleet Plan v7 进一步要求 `adapterConformanceTrustPolicy`。集成团队固定 trust policy 的 ID、最低 generation 和
文件 SHA；Adapter 认证方用 Ed25519 私钥对精确 evidence SHA、conformance ID、Adapter kind/ID、配置 SHA 与
scope 签名。policy 为每把公钥限制允许的 Adapter kind/ID 和有效期，并定义最大 attestation lifetime；
`revokedKeys` 可立即拒绝旧密钥，提升 generation 后可并行加入新密钥完成轮换。

```powershell
$evidenceSha = (Get-FileHash C:\pdr\fleet-executor-conformance.json -Algorithm SHA256).Hash.ToLower()
python pdr.py contract-package adapter-conformance-attest `
  --evidence C:\pdr\fleet-executor-conformance.json `
  --expected-evidence-sha256 $evidenceSha `
  --certifier-id runtime-adapter-team --key-id adapter-certifier-2026-b `
  --private-key-environment PDR_ADAPTER_CERTIFIER_PRIVATE_KEY `
  --report C:\pdr\fleet-executor-attestation.json

python pdr.py contract-package adapter-conformance-admission-create `
  --bundle-id host-b-admission --rollout-id oslo-adapters-v7 `
  --catalog-id production-adapters `
  --evidence fleet-executor C:\pdr\fleet-executor-conformance.json `
  --attestation fleet-executor C:\pdr\fleet-executor-attestation.json `
  --output C:\pdr\host-b-admission.json
```

实际 bundle 必须同时包含六类 evidence/attestation。执行 Fleet 命令时除 bundle 及其 SHA 外，还必须传入
`--adapter-conformance-trust-policy` 和 `--expected-adapter-conformance-trust-policy-sha256`。journal v7 只保留
trust policy、attestation、certifier 和 key 的摘要身份，不保存公私钥路径或 evidence 路径。示例中的
`create_conformance_trust_demo.py` 只用于本地 SDK 验收；生产私钥必须由团队自己的 KMS/HSM 和发布流程管理。

### External Certifier Signer

生产签名可将 `--private-key-environment` 替换为外部 Signer Adapter：

```powershell
$signerSha = (Get-FileHash C:\pdr\adapter-certifier-signer.json -Algorithm SHA256).Hash.ToLower()
python pdr.py contract-package adapter-conformance-attest `
  --evidence C:\pdr\fleet-executor-conformance.json `
  --expected-evidence-sha256 $evidenceSha `
  --certifier-id runtime-adapter-team --key-id adapter-certifier-2026-b `
  --signer-config C:\pdr\adapter-certifier-signer.json `
  --expected-signer-config-sha256 $signerSha `
  --report C:\pdr\fleet-executor-attestation.json
```

Signer 配置固定 executable、arguments、supporting artifacts、公钥、key ID、环境变量 allowlist、timeout、
payload/response 上限和 required capabilities。主进程先协商 protocol/capability/key set，再向隔离进程发送
规范 payload 和 SHA；响应必须回显 request/signer/certifier/key/purpose，并由主进程用固定公钥再次验签。
attestation schema v2 只记录 `signerId`、config SHA 和 capability manifest SHA，不记录 endpoint、本地路径或凭证。
安装示例 `team-contract-adapter-certifier-signer-local` 使用本地 PEM 仅演示协议；生产 Adapter 应在进程内部调用
KMS/HSM，且不得导出私钥字节。

### Adapter Certifier Trust Control

生产 trust policy 不应由单个开发者直接覆盖。公共 CLI 将变更拆成三个可审计阶段：
`adapter-certifier-trust-propose` 固定当前/候选 policy 的 ID、generation、SHA 和治理策略；
`adapter-certifier-trust-approve` 让审批人分别对 proposal 原始字节签名；
`adapter-certifier-trust-activate` 重新验证全部 pin、有效期、Ed25519 签名和职责分离后，再原子替换活动 policy。

治理策略的普通阈值至少为 2，审批人和 key 必须同时不同，proposal 发起人不能审批，激活人必须在独立
allowlist 内且不能是发起人或本次审批人。`emergency-revocation` 使用独立、更短的有效期和审批阈值，
候选策略除 generation 与新增 `revokedKeys` 外必须逐字段等于当前策略；因此紧急路径不能添加 certifier、
扩大 Adapter kind/ID、换公钥、删除/改写旧吊销或放宽 attestation lifetime。激活报告只记录逻辑身份和
摘要，不记录密钥或本地路径。

多协调 Host 部署使用 `adapter-certifier-trust-remote-*` 命令。活动 policy、每次 activation evidence 和
状态记录写入 Artifact Store，Registry Leader Backend 只保存当前 CAS pointer；pointer 的 `stateVersion`
同时作为 fencing token，并固定前一 pointer SHA、当前 state SHA、operation ID 和 coordinator ID。Host 接管时
必须重新读取并验证完整前驱、policy 和 activation 摘要链，再基于精确 state version/policy SHA 提交下一代。

`remote-propose` 从远程权威状态读取当前 policy，不依赖某台 Host 的活动文件；审批文件仍是可移交的独立
Ed25519 制品。`remote-activate` 复用与本机激活完全相同的双人审批和职责分离验证，随后才进行远程 CAS。
Backend 返回结果不确定时只在当前 pointer 精确匹配预期 state/coordinator/operation 时确认成功；陈旧 Host、
丢失历史、缺失 Artifact、内容漂移或 scope/config pin 变化均失败关闭。

Pointer v2 使用 `--adapter-config-resolver-config`、对应 Resolver config SHA/ID，以及两份分别固定 SHA 的
`--state-backend-config-ref`、`--artifact-store-config-ref`。此模式拒绝同时传入直接 Backend/Artifact config。
远程 pointer 仅保存 Resolver ID 和逻辑 reference；每台 Host 可用不同 Resolver 配置把同一 reference 解析到
自己的绝对路径、配置 SHA 和凭据 Provider。解析 scope 固定为 consumer type
`adapter-certifier-trust-state`、`controlId` 和 `trustPolicyId`，并重新检查 reference 的 kind、Adapter ID、
revision、返回配置 product/identity 与内容 pin。
未提供 Resolver 参数时继续生成并验证 direct-config pointer v1。

已有 direct-config pointer v1 不能通过切换启动参数静默变成 v2。迁移使用四个独立公共命令：
`adapter-certifier-trust-remote-migration-preflight` 从 source direct Adapter 和 target Resolver Adapter 分别
读取并验证完整权威链；`migration-propose` 固定源 pointer/state/policy SHA、config pin、目标逻辑引用和
治理策略；`migration-approve` 由不同审批人对 proposal 原始字节签名；`migration-activate` 复核标准阈值、
职责分离和全部 pin 后，写入不可变 migration evidence/state，并用下一 fencing token 一次 CAS 发布 pointer v2。

迁移不改变活动 policy generation 或 SHA。CAS 前失败只会产生不可达的内容寻址对象，权威 pointer 仍为 v1；
CAS 成功响应丢失时必须精确回读新 pointer，重复相同 proposal/operation 返回已验证结果。历史验证只允许
`v1 --(signed migrate state)--> v2` 这一单向边界，普通 activation 不得改变配置作用域。迁移后可继续使用
portable Host 激活下一代 policy，旧 direct Host 因 fencing/CAS 冲突不能覆盖新状态。

### Governance Approval 公共协议

新模块不得复制 Ed25519 法定人数验证。`governance-approval-subject` 将任意 JSON payload 的 product/SHA、
业务 subject type、审批 role、initiator、治理 policy ID/SHA 和期限封装为可移交 subject；审批人使用
`governance-approval-approve` 对 subject 原始字节签名；执行方使用 `governance-approval-verify` 同时提供
原 payload、subject、policy、签名集合、公钥目录与 executor ID，生成摘要化 evidence。

Policy 可声明多个 role，每个 role 拥有独立最小审批数和最长 subject 生命周期；approver 可被授予多个 role。
验证要求 approver 人员和 key 同时唯一，检查按时间生效的 key revocation、公钥内容 pin 和 Ed25519 签名，
并强制 initiator、所有 approver、executor 相互分离。Evidence 不记录 payload 内容、密钥、本地路径或环境变量。

已有业务协议无需破坏性替换自己的 approval schema。公共 Python 引擎
`team_contract_governance_approval.verify_ed25519_quorum()` 接收业务 validator 与 subject SHA 字段名，
因此 Adapter Trust Policy 的 `proposalSha256` 和 pointer Migration 的同名字段继续兼容，但法定人数、角色、
撤销、key pin 和职责分离由同一实现负责。业务模块仍负责验证 proposal 的业务语义，公共引擎不替代领域规则。

审批命令支持两种互斥签名模式：兼容模式使用 `--private-key-environment` 在当前进程加载本地 PEM；生产模式
使用 `--signer-config` 和 `--expected-signer-config-sha256` 调用外部 Governance Approval Signer。后者适用于
KMS、HSM、Vault 或企业签名服务，主机进程不读取私钥。配置会固定 signer/approver 身份、Ed25519 公钥、
key set、允许 purpose、执行制品与环境变量策略；能力协商返回值也必须与这些声明逐项一致。

三个 purpose 分别是 `governance-approval`、`adapter-certifier-trust-approval` 和
`adapter-certifier-trust-migration-approval`，不得跨业务重放。签名器返回后，主机仍使用配置中固定的公钥
本地验签。v2 的域分离 signing payload 还同时签入 approval product、approver/key、subject SHA、purpose
以及 signer/config/capability 摘要，因此替换信封中的 provenance 或跨 purpose 重放都会验签失败。
外部模式生成 schema v2 approval envelope，只附带 `signerId`、`signerConfigSha256` 与
`signerCapabilityManifestSha256`，不记录配置路径、私钥位置或凭据；本地模式继续生成 schema v1。
安装示例 `team-contract-governance-approval-signer-local` 使用本地 PEM 演示协议和故障注入，不能替代生产密钥边界。

生产环境可再向三个 approve 命令同时传入 `--signer-admission-config` 与
`--expected-signer-admission-config-sha256`。准入配置固定 signer conformance evidence、独立 certifier
attestation、trust policy、最低 policy generation 与证据最大年龄。签名开始前，主机会重新读取全部固定制品，
验证证据未过期、certifier 未被撤销且获准认证精确 signer kind/ID，并要求证据中的 signer ID、approver scope、
config SHA 和 capability SHA 与当前已加载 signer 一致。准入成功生成 schema v3 envelope；其中只包含 conformance、
certifier 和 policy 的逻辑身份与摘要，所有字段都进入域分离 signing payload，修改任一 provenance 字段都会使验签失败。

Schema v3 同时要求执行时重新准入。`governance-approval-verify`、`adapter-certifier-trust-activate` 和
`adapter-certifier-trust-remote-migration-activate` 必须提供 `--signer-readmission-bundle`、对应 SHA pin 及
`--signer-readmission-report`。Bundle 是 executor 本地配置，按 `approvalSha256` 精确映射到本机 Admission Config；
它不进入共享 approval envelope。执行方重新检查 evidence 年龄、attestation 签名、Certifier scope/有效期/撤销以及
signer/config/capability/approver provenance，并可在同一 policy ID 下接受仍授权该 Certifier 的更高 generation。

Readmission Evidence 同时记录创建时和执行时 Trust Policy 的逻辑身份、generation 和 SHA，不记录任何本机路径；
其摘要会进入通用 Verify Evidence、Trust Activation Report 或 Migration Report 的 schema v2，确保执行审计与实际
信任判定绑定。Bundle 必须恰好覆盖全部 v3 approval，缺项、多项、错误 approval SHA 或缺少 evidence 输出均失败关闭。
本地 PEM v1 与未采用创建时准入的外部 v2 继续按原路径执行，不要求 Bundle，也拒绝误传的 Bundle。
