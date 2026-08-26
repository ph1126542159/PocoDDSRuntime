# 生产 Service 契约图与兼容门禁

Runtime 的 Service Dependency Guard 负责已安装 Bundle 的动态可用性；组件级
`pdr component contract-test` 负责一个 Consumer 对显式 Provider fixture 的独立测试。
仓库级 `pdr service-contract graph` 补充两者之间的发布前边界：扫描 `services/**/bundle/service-contracts.json`，
在不启动 Runtime 的情况下验证完整生产 Service 图。

## 默认门禁

```powershell
./tools/pdr.ps1 service-contract graph `
  --root . --scan-root services `
  --baseline contracts/service-contract-baseline.json `
  --report build/reports/service-contract-graph.json

./tools/pdr.ps1 service-contract verify `
  --root . --scan-root services `
  --baseline contracts/service-contract-baseline.json `
  --report build/reports/service-contract-graph.json
```

门禁从每个契约旁唯一的 `.bndlspec` 推导 Bundle symbolic name，不能由 JSON 自报 Owner，并验证
`.bndlspec` 确实打包 `bundle/*`。报告绑定所有契约、Bundle spec 和已发布基线的 SHA-256，覆盖：

- 每个必需 Requirement 的版本范围和 `minimumProviders`；
- 全局 `serviceName` 唯一性；
- 必需 Service 依赖环；
- 已发布 Bundle/Provider 被删除、版本倒退或在同一主版本内改名；
- Provider 主版本替换后，所有生产 Consumer 是否已经迁移到新范围；
- 可选 Requirement 未满足的 warning。

`verify` 会从当前输入重建完整报告；只修改 JSON 结果、替换某一个输入或使用旧报告都会失败。

## 已发布基线

`contracts/service-contract-baseline.json` 表示已经发布的生产 Service 表面，不是当前工作树的自动
镜像。日常 PR 不应为了通过门禁而刷新它。Provider 的兼容扩展可以保持基线不变；不兼容改名必须
提升 Provider 主版本，并在同一交付序列中迁移 Consumer。新版本真正发布后，Release Owner 才执行：

```powershell
./tools/pdr.ps1 service-contract baseline-snapshot `
  --root . --scan-root services `
  --output contracts/service-contract-baseline.json
```

基线更新必须与发布证据一起评审。删除历史基线中的 Owner，或只重新生成基线来掩盖未迁移的
Consumer，都不属于兼容修复。

## 多团队边界

Provider 团队拥有 `provides` 的 Contract、版本和 Service 名；Consumer 团队拥有自己的版本范围、
必需性和冗余数量。仓库图只证明源码中的生产声明互相兼容，不证明 Service 已注册或业务健康；
部署后的 Bundle Active、Service Registry Owner、动态 readiness 和生命周期 TOCTOU 仍由
Service Dependency Runtime 在实际执行点检查。外部产品组件不在 `services/` 扫描范围内，应继续
使用安装 SDK 提供的独立组件契约测试。

必需依赖图采用 fail-closed 规则：所有匹配 Provider 都进入依赖边。如果冗余 Provider 设计形成
表面环，应先调整 Contract 分层，而不是把环隐藏为例外。
