# 安全基线

## 部署 Profile

`security.profile` 支持：

- `development`：允许本机回环地址上的无认证开发界面；绑定外部地址时必须同时配置认证和 TLS。
- `production`：必须启用 TLS、配置认证服务，并禁止兼容性 SimpleAuth。

Runtime 启动时通过 `ConfigurationValidator` 执行相同规则；仓库和部署配置还可以独立执行：

```powershell
python tools/security_gate.py config/pdr-runtime.properties
```

配置文件中名称包含 `password`、`secret` 或 `token` 的非空值会被门禁拒绝。生产密钥应由
部署环境或后续 `SecretProvider` 适配器提供，不能提交进 properties、日志、Trace 或发布包。

当前 SimpleAuth 使用旧兼容哈希，只允许受控本地兼容场景。生产 OIDC、企业账户、证书签发
和私钥托管需要部署环境提供；仓库的安全门禁不把这些外部能力标记为已完成。

## 发布检查

每个发布物必须包含：

- `SHA256SUMS.json`：文件路径、大小和 SHA-256；
- `pocoddsruntime.spdx.json`：SPDX 2.3 软件物料清单；
- Git commit、版本及工作区是否干净；
- 对应构建、测试和兼容性检查结果。

CI 使用 `--require-clean`，防止从未提交工作树产生正式制品。哈希校验发现文件缺失、替换
或修改时会失败。代码签名证书和发布私钥不能存储在仓库中，应由受保护的发布流水线注入。
