# Leader Backend Adapter SDK 示例

这是一个只依赖 Python 标准库的独立适配器示例，实现安装 SDK 定义的
`read-current`、`read-grant` 和 `compare-and-swap` JSON 协议。它演示以下必须保持的边界：

- `expectedCurrentToken` 与 `expectedCurrentGrantSha256` 在同一个跨进程锁内比较；
- grant 原始字节逐字节保存，历史文件只创建、不覆盖；
- current 使用写入、`fsync`、原子替换更新；
- authority/Registry scope、适配器、解释器和配置文件均由允许列表或 SHA-256 固定；
- stdin 只接收一个有界请求，stdout 只输出一个协议响应，诊断写入 stderr。

此实现仅用于 SDK 接入、开发和一致性验收。它依赖单机文件锁，不提供分布式 consensus、mTLS、ACL、
多节点 quorum、快照灾备或跨故障域能力，不能作为多节点生产 Leader Authority。

## 从安装包运行

```powershell
$sdk = 'E:/PocoDDSRuntime/build/install'
$sample = "$sdk/share/PocoDDSRuntime/examples/team-contract-registry-leader-backend-file"
$work = 'E:/adapter-validation/file-example-0001'
New-Item -ItemType Directory -Force "$work/store" | Out-Null
$env:PDR_LEADER_BACKEND_SAMPLE_ROOT = "$work/store"

python "$sample/create_backend_config.py" `
  --python (Get-Command python).Source `
  --adapter "$sample/file_backend_adapter.py" `
  --backend-id file-example-0001 `
  --authority-id file-example-authority-0001 `
  --registry-id file-example-registry-0001 `
  --output "$work/backend.json"

$configSha = (Get-FileHash "$work/backend.json" -Algorithm SHA256).Hash.ToLower()
python "$sdk/bin/pdr.py" contract-package registry-leader-backend-capabilities `
  --backend-config "$work/backend.json" `
  --expected-backend-config-sha256 $configSha `
  --authority-id file-example-authority-0001 `
  --registry-id file-example-registry-0001 `
  --report "$work/capabilities.json"

python "$sdk/bin/pdr.py" contract-package registry-leader-backend-conformance `
  --backend-config "$work/backend.json" `
  --expected-backend-config-sha256 $configSha `
  --authority-id file-example-authority-0001 `
  --registry-id file-example-registry-0001 `
  --confirm-dedicated-empty-scope `
  --report "$work/conformance.json"
```

默认生成器输出 schema v2；适配器必须在任何 store 访问前声明协议 `1.0` 以及原子 CAS、提交结果对账、不可变
历史、线性 current 读取和 scope 隔离能力。能力报告摘要会进入后续 Conformance 证据。schema v1 仅作为
旧配置兼容输入，不产生能力协商报告。

需要凭据时，增加 `--secret-provider-config`、一个或多个
`--credential ENVIRONMENT_VARIABLE SECRET_ID VERSION` 即生成 schema v3。配置只保留版本化引用；Provider
在每次业务请求前解析并把值注入该 Backend 子进程。能力协商不读取凭据，普通 `environmentVariables` 与
`credentialBindings` 不能重名；缺失、版本变化、Provider 身份或固定制品漂移都会在 Backend 操作前失败。

无中断轮换使用 `--rotating-credential ENV SECRET_ID PREFERRED_VERSION FALLBACK_VERSION FALLBACK_UNTIL` 生成
schema v4，并用 `--minimum-credential-lease-seconds` 要求租约覆盖本次 Backend 超时。新版本可用时总是优先；
旧版本只在明确期限内回退。租约不足、回退过期、两版本均不可用或撤销都会在启动 Backend 子进程前失败。

`create_backend_config.py --root-environment <NAME>` 可为两个独立 store 生成 source/target 配置。安装 SDK 的
`registry-leader-backend-migration-sync` 会验证并复制不可变公共前缀；完整 cutover/rollback 还必须经过 source
fence、target 直接后继 leadership、`migration-finalize` 和携带迁移证据的 `registry-leader-activate`。
为 Sync 同时传入 `--transaction` 与 `--actor` 可创建共享事务；后续操作者使用 Status 返回的事务 SHA 执行
Resume。Reconcile 只接纳仍匹配双方链的固定 checkpoint，Abort 只允许在 source 尚未 Fence 时终止并保留
target 历史。跨主机时可改传 `--transaction-backend-config`，复用本适配器或 etcd 适配器的原子 CAS/history
协议；配置的 authority scope 必须使用 Migration ID。本地 `--transaction` 文件继续作为兼容和单机路径。

事务状态与迁移证据是两个独立职责。若不同主机不共享证据目录，同时传入
`--artifact-store-config/--expected-artifact-store-config-sha256`；schema v3 事务会保存内容寻址引用而不是
绝对路径。安装 SDK 的 `examples/team-contract-artifact-store-file/` 提供参考协议和文件适配器。

跨主机操作应再使用安装 SDK 的 `team-contract-backend-config-resolver-file` 示例。配置 source/target 引用后，
schema v4 事务不再保存 backend config 的本机路径或 SHA；每台主机通过自己的固定 resolver mapping 解析同一
`resolverId/configId/backendId/revision`。完整 Status/Resume/Finalize/Activate/Reconcile/Abort 流程均支持该模式。

Conformance 会永久写入 token 1 和 token 2。每次验收必须使用新的空 scope，并保留 store 与报告作为
适配器版本证据；示例和 SDK 均不会删除或重置 authority 状态。
