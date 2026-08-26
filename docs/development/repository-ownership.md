# 仓库所有权与 CODEOWNERS

多人协作使用两层所有权模型：

- `contracts/framework-components.json` 定义稳定的逻辑 Owner，例如 `team/runtime-core`，并同时绑定组件路径、依赖、构建 Target 和 CTest label。
- `contracts/repository-owners.json` 把逻辑 Owner 映射到 GitHub 可识别的用户或组织 Team，例如 `@org/runtime-core`。

`.github/CODEOWNERS` 是以上两个契约的生成物，不允许手工维护。当前仓库位于个人账号下，因此所有逻辑 Owner 暂时映射到 `@ph1126542159`；建立 GitHub Organization 和真实 Team 后，只需修改 Reviewer 映射，不应改动组件依赖或目录边界。

`services/` 不再作为单一 Owner 边界：治理类 Runtime Service 属于
`governance-services / team/runtime-governance`，设备与协议网关属于
`gateway-services / team/device-platform`，传统通用服务属于
`utility-services / team/services`。因此修改 Scheduler、DeviceGateway 或 UnitsOfMeasure 会生成
不同的直接 Owner 和测试 label 集合；三者只通过稳定 platform API/Service Contract 协作，不能借
同一顶层目录形成未声明的源码依赖。

## 修改与验证

```powershell
python tools/repository_ownership.py render `
  --catalog contracts/framework-components.json `
  --registry contracts/repository-owners.json `
  --output .github/CODEOWNERS

python tools/repository_ownership.py verify `
  --catalog contracts/framework-components.json `
  --registry contracts/repository-owners.json `
  --codeowners .github/CODEOWNERS
```

校验会拒绝缺失或过期的逻辑 Owner、无效 GitHub handle、重复 Reviewer 以及与契约不一致的 CODEOWNERS。首条 `*` fallback 保证新增或未归类路径仍需默认 Reviewer；框架级路径随后生成，组件的精确路径最后生成，因此 `cmake/PocoDDSPlugins.cmake` 等特例可以覆盖 `cmake/` 的默认 Reviewer。

源码门禁只能证明 CODEOWNERS 与契约一致。要让 GitHub 真正阻止未审批合并，仓库管理员还必须在 `main` 分支保护中启用 Pull Request 审查及 **Require review from Code Owners**；这属于托管平台状态，不能由本地测试结果代替。
