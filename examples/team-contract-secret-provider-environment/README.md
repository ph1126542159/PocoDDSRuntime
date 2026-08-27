# Environment Secret Provider 示例

该参考适配器把稳定的单版本引用或有序双版本轮换引用解析为有时间上限的秘密租约。mapping 只包含环境
变量名、版本与 `active/revoked` 状态，不包含值；Provider 配置固定 Python、适配器和 mapping 的 SHA。
v2 把秘密来源列入可选 allowlist，因此新旧版本可以独立投放，但 Provider 子进程仍不会继承任何未声明变量。

这是迁移桥接和测试实现。生产团队应按同一 SPI 接入 Windows Credential Manager、Vault、云 Secret
Manager/KMS 或 workload identity。Backend 配置、事务、证据、报告和日志不得包含解析值、摘要或长度；公开
`secret-provider-check` 只报告版本化引用及 `available=true`。

```powershell
python create_secret_provider_config.py `
  --python C:\Python312\python.exe `
  --adapter C:\pdr\environment_secret_provider_adapter.py `
  --provider-id production-registry-secrets `
  --entry etcd-client-key deploy-2026-09 PDR_ETCD_CLIENT_KEY_NEW `
  --entry etcd-client-key deploy-2026-08 PDR_ETCD_CLIENT_KEY_OLD `
  --lease-seconds 30 --minimum-remaining-seconds 5 `
  --mapping-output C:\pdr\secret-map.json `
  --output C:\pdr\secret-provider.json
```

轮换引用把新版本放在 `versions[0]`、旧版本放在 `versions[1]`，并必须给出 `fallbackUntil`。新值存在时立即
优先使用；新值尚未投放或被撤销时，只能在期限内回退旧值；期限结束后不会静默继续使用旧值。`--revoked
SECRET_ID VERSION` 可生成撤销测试映射。Provider v1 精确引用仍兼容，但不提供租约、轮换或撤销语义。
