# etcdctl Leader Backend Adapter

该独立 SDK 示例把 PDR Leader Backend SPI 映射到 etcd v3。它不链接 Runtime 或 etcd 客户端库，而是调用
SHA-256 固定的 `etcdctl`，便于适配器团队独立发布和升级。

核心事务同时比较 current 的原始值、确认目标 history key 不存在，并在一个 `txn` 中写入不可变 history
与 current。读操作显式使用线性一致模式。配置生成器强制至少三个不同的 HTTPS endpoint，并固定
`etcdctl`、适配器配置、CA、客户端证书、客户端私钥及附属制品。

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

随后对一个全新的专用 scope 运行安装 SDK 的
`pdr.py contract-package registry-leader-backend-conformance`。etcd 必须启用 client certificate authentication
和 RBAC，客户端证书 CN 对应的用户只授予所配置 `keyPrefix` 的读写权限。

在产生任何 authority 写入前，先运行只读集群预检：

```powershell
$adapterSha = (Get-FileHash "$work/adapter.json" -Algorithm SHA256).Hash.ToLower()
python "$sdk/bin/pdr.py" contract-package registry-leader-etcd-preflight `
  --config "$work/adapter.json" `
  --expected-config-sha256 $adapterSha `
  --report "$work/cluster-preflight.json"
```

预检要求所有配置 endpoint 健康、属于一个 cluster、映射到不同 member、观察到同一个已选 Leader，并执行
配置前缀下的线性只读探测。写 RBAC、事务和逐字节历史仍由专用空 scope 的 Conformance 验证。

本仓库自动测试使用事务语义模型验证命令编码、并发唯一胜者、history/current 原子写和 pin 漂移；由于当前
验证环境没有实际 etcd 集群，它不证明真实集群的 TLS 握手、RBAC、Raft quorum、网络分区、快照恢复或长稳。
