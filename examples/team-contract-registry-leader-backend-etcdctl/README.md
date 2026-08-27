# etcdctl Leader Backend Adapter

该独立 SDK 示例把 PDR Leader Backend SPI 映射到 etcd v3。它不链接 Runtime 或 etcd 客户端库，而是调用
SHA-256 固定的 `etcdctl`，便于适配器团队独立发布和升级。

核心事务同时比较 current 的原始值、确认目标 history key 不存在，并在一个 `txn` 中写入不可变 history
与 current。读操作显式使用线性一致模式。配置生成器强制至少三个不同的 HTTPS endpoint，并固定
`etcdctl`、适配器配置、CA、客户端证书、客户端私钥及附属制品。

生成的 Backend 配置使用 schema v2。Acceptance 在接触 etcd 前先协商协议 `1.0` 及原子 CAS、提交结果
对账、不可变历史、线性 current 读取和 scope 隔离能力，并把能力清单摘要绑定进最终证据。

同一 SPI 也可作为迁移事务存储，无需维护第二套 etcd 协议。生成配置时把每个 Migration ID 追加到
`--authority-id`，把业务 Registry ID 追加到 `--registry-id`；迁移命令传
`--transaction-backend-config/--expected-transaction-backend-config-sha256`。事务 schema v2 将
`stateVersion` 映射为 fencing token，并以 `previousGrantSha256` 固定前一状态，所以 current 和不可变
history 仍由同一个 `etcdctl txn` 提交。Leader authority 与迁移事务必须使用不同 scope，不能共享 current。

etcd Transaction Store 只协调迁移状态，不承载证据对象。跨主机操作请同时配置独立 Artifact Store；事务会
升级为 schema v3 内容引用。若各操作者主机的 etcdctl、证书或安装路径不同，再配置
`examples/team-contract-backend-config-resolver-file/`；schema v4 事务只保存稳定配置引用，各主机本地解析并
重新验证 etcd Backend scope 和 pins。对象存储团队可基于安装 SDK 的 `examples/team-contract-artifact-store-file/`
协议实现 S3、MinIO 或 Blob 适配器。

## 生成配置

```powershell
$sdk = 'E:/PocoDDSRuntime/build/install'
$sample = "$sdk/share/PocoDDSRuntime/examples/team-contract-registry-leader-backend-etcdctl"
$work = 'E:/leader-control/etcd-adapter-0001'
New-Item -ItemType Directory -Force $work | Out-Null

python "$sample/create_backend_configs.py" `
  --python (Get-Command python).Source `
  --adapter "$sample/etcd_backend_adapter.py" `
  --adapter-id product-contracts-etcd-v1 `
  --backend-id product-contracts-etcd `
  --authority-id product-contracts-leader `
  --registry-id product-contracts `
  --etcdctl 'C:/Program Files/etcd/etcdctl.exe' `
  --endpoint https://etcd-1.example:2379 `
  --endpoint https://etcd-2.example:2379 `
  --endpoint https://etcd-3.example:2379 `
  --key-prefix /pdr/product-contracts/leader/v1 `
  --cacert E:/pki/etcd/ca.pem `
  --cert E:/pki/etcd/product-contracts.pem `
  --key E:/pki/etcd/product-contracts-key.pem `
  --adapter-config-output "$work/adapter.json" `
  --backend-config-output "$work/backend.json"
```

etcd 必须启用 client certificate authentication 和 RBAC，客户端证书 CN 对应的用户只授予所配置
`keyPrefix` 的读写权限。

在产生任何 authority 写入前，先运行只读集群预检：

```powershell
$adapterSha = (Get-FileHash "$work/adapter.json" -Algorithm SHA256).Hash.ToLower()
python "$sdk/bin/pdr.py" contract-package registry-leader-etcd-preflight `
  --config "$work/adapter.json" `
  --expected-config-sha256 $adapterSha `
  --report "$work/cluster-preflight.json"
```

预检要求所有配置 endpoint 健康、属于一个 cluster、映射到不同 member、观察到同一个已选 Leader，并执行
配置前缀下的线性只读探测。

正式放行不要分散运行预检和 Conformance；对全新的专用 scope 使用一次性 Acceptance：

```powershell
$backendSha = (Get-FileHash "$work/backend.json" -Algorithm SHA256).Hash.ToLower()
python "$sdk/bin/pdr.py" contract-package registry-leader-etcd-acceptance `
  --adapter-config "$work/adapter.json" `
  --expected-adapter-config-sha256 $adapterSha `
  --backend-config "$work/backend.json" `
  --expected-backend-config-sha256 $backendSha `
  --authority-id product-contracts-etcd-acceptance-0001 `
  --registry-id product-contracts-etcd-acceptance-0001 `
  --confirm-dedicated-empty-scope `
  --output-directory "$work/acceptance-0001"
```

Acceptance 在写入前后各做一次拓扑预检，中间运行公开 Backend Conformance，并把三份阶段报告的 SHA-256
绑定进 `acceptance.json`。输出目录必须不存在，验收 scope 会保留 token 1、token 2 和不可变历史。返回码 3
表示可能已经提交，`acceptance-failure.json` 和存储现场必须先对账，不可直接清理或重跑。

本仓库自动测试使用事务语义模型验证命令编码、并发唯一胜者、history/current 原子写、健康/Leader/learner/
Raft 异常拒绝、证据绑定和 pin 漂移；由于当前验证环境没有实际 etcd 集群，它不证明真实集群的 TLS 握手、
RBAC、Raft quorum、网络分区、快照恢复或长稳。
