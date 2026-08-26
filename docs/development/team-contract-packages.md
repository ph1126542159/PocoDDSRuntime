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
  "schemaVersion": 1,
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

适配器仓库无需复制 Runtime 测试或取得 authority 签名私钥。安装 SDK 提供正式 Conformance 命令；它会
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
证据，下一版本使用新的 scope。通过只证明适配器满足 PDR 的存储/CAS 协议，不替代实际 etcd/Consul 集群的
TLS、ACL、quorum、快照恢复、跨故障域和长稳验收。

安装 SDK 还提供
`share/PocoDDSRuntime/examples/team-contract-registry-leader-backend-file/` 参考工程。其中
`create_backend_config.py` 生成固定 Python、适配器及 scope 的配置，`file_backend_adapter.py` 给出独立进程、
跨进程锁、逐字节不可变历史、`fsync` 和原子 current 替换的最小实现。SDK 外部 Consumer 会从安装目录
实际生成配置并执行上述 Conformance，因此示例不是仅存在于源码树中的伪样例。该文件实现仍是单机教学
后端；生产适配器团队应保留 JSON 边界和验收测试，只替换持久化/CAS 层，并补充目标集群验收。

### etcd 生产适配路径

安装 SDK 的 `examples/team-contract-registry-leader-backend-etcdctl/` 提供不向 Runtime 泄漏 etcd 客户端依赖的
独立适配器。配置生成器要求至少三个不同的 HTTPS endpoint，固定 Python、适配器、`etcdctl`、CA、客户端
证书、私钥和附属制品 SHA；所有 key 收敛在专用 `keyPrefix`。适配器先执行线性一致 current 读取，再由
[`etcdctl txn`](https://github.com/etcd-io/etcd/blob/main/etcdctl/README.md#txn-options) 同时比较 current 原始值、
确认目标 history 不存在，并原子写 history/current。并发者无法基于同一前驱提交不同的新 grant。

真实集群必须先启用客户端证书认证和 RBAC，并让证书 CN 对应的 etcd 用户只拥有该 `keyPrefix`；etcd 默认
不会自动启用这些安全能力。生成配置后先运行只读预检：

```powershell
$adapterConfigSha256 = (Get-FileHash `
  E:/leader-control/etcd-adapter.json -Algorithm SHA256).Hash.ToLower()

python E:/PocoDDSRuntime/build/install/bin/pdr.py contract-package registry-leader-etcd-preflight `
  --config E:/leader-control/etcd-adapter.json `
  --expected-config-sha256 $adapterConfigSha256 `
  --report E:/leader-control/etcd-cluster-preflight.json
```

预检查询所有 endpoint 的 health/status，要求它们属于同一 cluster、member ID 唯一、观察到同一个已选
Leader、Raft applied index 不超过 commit index，并执行命名空间内的线性只读探测。之后仍须在专用空 scope
执行 Backend Conformance；上线前还应完成真实三节点断网、失主、证书/RBAC 拒绝、快照恢复及长稳测试。

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
