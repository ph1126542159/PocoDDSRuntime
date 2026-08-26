# 框架变更影响与多人协作门禁

框架仓库使用 `contracts/framework-components.json` 维护源码路径、逻辑 Owner、组件依赖、构建
Target 和 CTest label。它不是运行时 Bundle/Service 清单，也不替代 GitHub 的实际审批配置；它的
职责是让一次源码变更需要谁审查、构建什么、测试什么成为可验证的机器契约。逻辑 Owner 通过
`contracts/repository-owners.json` 映射为真实 GitHub Reviewer，并生成 `.github/CODEOWNERS`；详见
[仓库所有权与 CODEOWNERS](repository-ownership.md)。

```powershell
python tools/framework_change_impact.py analyze `
  --catalog contracts/framework-components.json `
  --output build/reports/framework-change-impact.json `
  platform/BundleManagement/src/BundleManager.cpp
```

局部改动先选择直接组件，再沿反向依赖图加入所有消费者。例如 BundleManagement 改动会同时选择
Launcher、Server 和 WebUI。输出包含 `owners`、`buildTargets`、`testLabels` 以及可直接传给
`ctest -L` 的 `ctestLabelRegex`。

生产 `services/` 按团队交付边界拆分为 `governance-services`、`gateway-services` 和
`utility-services`。因此 SchedulerRuntime、DeviceGateway 和 UnitsOfMeasure 的改动会分别路由到
`team/runtime-governance`、`team/device-platform` 和 `team/services`，不会因为共享一个顶层目录而
要求无关团队参与。

三个责任域同时暴露稳定的 CMake 聚合 Target，可以在同一配置树中独立构建：

```powershell
cmake --build build/profiles/server --config Release --target PDRGovernanceServices
cmake --build build/profiles/server --config Release --target PDRGatewayServices
cmake --build build/profiles/server --config Release --target PDRUtilityServices
```

`framework-component-build-groups` 门禁将聚合 Target 的成员与 CMake 实际生产 Target 图对照；
新增 Service Bundle 却忘记纳入对应组、将其他团队 Target 误收进组，或者变更影响目录与
CMake 已漂移时都会 fail-closed。

可以直接执行变更报告中的 `buildTargets` 并写入绑定证据：

```powershell
$revision = git rev-parse HEAD
python tools/framework_build_evidence.py execute `
  --root . `
  --report build/reports/framework-change-impact.json `
  --build-dir build/profiles/server `
  --links build/profiles/server/reports/framework-link-manifest.json `
  --groups build/profiles/server/reports/framework-component-build-groups.json `
  --dependencies release/dependencies.json `
  --source-revision $revision `
  --cmake "C:/path/to/cmake.exe" `
  --configuration Release `
  --parallelism 2 `
  --evidence build/reports/framework-build-execution-evidence.json
```

只有 CMake 返回成功且执行前后输入摘要不变时才会原子写入证据。证据同时给出
`cacheKey`；它包含 Profile、配置、源修订、变更文件、构建输入和影响计划摘要，
可作为团队级缓存命名空间。缓存恢复或上传前使用独立 gate 重算当前输入：

```powershell
python tools/framework_build_evidence.py gate `
  --root . `
  --report build/reports/framework-change-impact.json `
  --build-dir build/profiles/server `
  --links build/profiles/server/reports/framework-link-manifest.json `
  --groups build/profiles/server/reports/framework-component-build-groups.json `
  --dependencies release/dependencies.json `
  --source-revision $revision `
  --cmake "C:/path/to/cmake.exe" `
  --evidence build/reports/framework-build-execution-evidence.json
```

以下情况始终 `fullSuite=true`，禁止 affected-only：

- 根 CMake、Preset、CI、公共配置、契约、发布或工具链发生变化；
- 新路径尚未归类；
- 一个路径被多个组件规则含糊匹配；
- 当前没有可靠的变更基线。

这是故障安全边界：目录新增后若忘记登记，不会静默漏测，而是退化为全量构建和测试。文档单独
修改会给出 `docsOnly=true`，仍需运行文档契约门禁。

工具可以直接执行计划选中的 CTest 并生成摘要绑定证据；本地局部验证使用 affected label，正式
full-stack CI 增加 `--force-full-suite`，因此仍执行完整验收：

```powershell
python tools/framework_change_impact.py execute `
  --report build/reports/framework-change-impact.json `
  --ctest "C:/path/to/ctest.exe" `
  --test-dir build/profiles/server `
  --config Release `
  --evidence build/reports/framework-ci-execution-evidence.json
```

执行证据包含计划 SHA-256、选择模式、真实执行的测试名称和数量，不能挪用到另一份计划。随后用
独立 gate 收口：

```json
{
  "schemaVersion": 1,
  "operation": "framework-ci-execution-evidence",
  "reportSha256": "<sha256>",
  "selection": "affected-labels",
  "fullSuitePassed": false,
  "passedLabels": ["bundle", "bundle-deployment", "security"],
  "executedTestCount": 3,
  "executedTests": ["bundle-policy", "bundle-recovery", "security-policy"],
  "ctestConfig": "Release",
  "ctestCatalogSha256": "<sha256>",
  "approvedOwners": ["team/osp-runtime"]
}
```

```powershell
python tools/framework_change_impact.py gate `
  --report build/reports/framework-change-impact.json `
  --evidence build/reports/ci-execution.json `
  --require-owner-approvals
```

`fullSuite=true` 时，罗列全部 label 不能伪装成全量通过，证据必须同时声明
`selection=full-suite` 和 `fullSuitePassed=true`。计划内容变化后旧证据的 `reportSha256` 失效。源码门禁能证明逻辑 Owner、真实 Reviewer 和 CODEOWNERS 一致，但只有 GitHub
分支保护启用 **Require review from Code Owners** 后，才能把平台状态宣称为强制人工审批。

`requires` 还会由[框架源码与 CMake 链接依赖边界](framework-dependency-boundaries.md)同时校验
生产源码的直接 `#include` 和已配置 target 的直接链接关系。变更影响沿依赖图反向选择消费者，
两个依赖门禁则沿正向依赖证明 Consumer 没有越层访问 Provider；三者共用同一份目录，避免测试
选择、源码结构和构建链接图逐渐漂移。
