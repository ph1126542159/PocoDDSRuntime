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
python "$sdk/bin/pdr.py" contract-package registry-leader-backend-conformance `
  --backend-config "$work/backend.json" `
  --expected-backend-config-sha256 $configSha `
  --authority-id file-example-authority-0001 `
  --registry-id file-example-registry-0001 `
  --confirm-dedicated-empty-scope `
  --report "$work/conformance.json"
```

Conformance 会永久写入 token 1 和 token 2。每次验收必须使用新的空 scope，并保留 store 与报告作为
适配器版本证据；示例和 SDK 均不会删除或重置 authority 状态。
