# 产品项目打包与验包

产品交付包不是简单压缩构建目录。`pdr project package` 将以下证据绑定为一个确定性 ZIP：

- 安装或部署目录下的实际 payload；
- `pdr-project.yaml` 与当前 `pdr-project.lock.json`；
- 按配置层解析后的非秘密配置；
- 项目、内部组件、PocoDDSRuntime 和项目第三方依赖的 SPDX 2.3 SBOM；
- 每个文件的大小、SHA-256，以及可选的分离签名信封。

已登记模板的项目在打包前必须通过 `project template status --check`。存在模板升级、渲染
上下文变化或受管文件漂移时拒绝发行；明确选择 `--keep-project` 的项目定制文件不属于漂移。
交付包 Manifest 同时绑定模板 ID/版本，并与项目锁中的规范化 Manifest 交叉校验。
已登记且含 `.pdr-component.json` 的组件还必须处于当前模板版本且结构文件无漂移；组件业务
源码可以正常迭代，不会因偏离初始脚手架内容而阻止发行。旧的手写组件可继续使用，但应按
[组件模板升级](component-templates.md)显式采用后才获得该项治理证据。

## 依赖登记

项目直接使用但不属于 PocoDDSRuntime 的第三方依赖必须进入项目清单：

```powershell
./tools/pdr.ps1 project dependency add pdr-project.yaml VendorSDK `
  --version 2.4.1 --license Apache-2.0 `
  --download https://vendor.example/sdk-2.4.1.zip
./tools/pdr.ps1 project dependency list pdr-project.yaml
```

依赖变更会更新清单和组合文件，因此发布前必须重新生成项目锁：

```powershell
./tools/pdr.ps1 project resolve pdr-project.yaml `
  --output pdr-project.lock.json
```

## 可复现打包

`--artifacts` 应指向经过安装和测试的产品目录，而不是中间目标文件目录。同一 payload、清单、
锁文件、配置和 `SOURCE_DATE_EPOCH` 会得到字节一致的 ZIP：

```powershell
$env:SOURCE_DATE_EPOCH = "1787356800"
./tools/pdr.ps1 project package create pdr-project.yaml `
  --artifacts build/install --output build/dist/product-1.2.3.zip `
  --version 1.2.3 --license Proprietary
```

`--version` 必须与 `pdr-project.yaml.version` 完全一致，避免流水线候选、外部验收和最终 ZIP 使用
三个不同版本号。旧项目先执行 `pdr project version pdr-project.yaml <version>`。

`--refresh-lock` 适合本地试制；正式 CI 应先单独执行 `project resolve` 并审查锁文件。输出位于项目
内部时只能放在 `build/` 或 `install/`，防止交付包反向污染源码摘要。

## 签名与验证

HMAC 只用于隔离诊断或单组织内部流水线。生产发布使用 Ed25519，私钥路径和口令只能通过环境
变量传入：

```powershell
$env:PDR_PROJECT_PRIVATE_KEY = "C:/secure/project-release-private.pem"
./tools/pdr.ps1 project package create pdr-project.yaml `
  --artifacts build/install --output build/dist/product-1.2.3.zip `
  --version 1.2.3 --ed25519-private-key-environment PDR_PROJECT_PRIVATE_KEY `
  --signing-key-id project-release-2026

./tools/pdr.ps1 project package verify build/dist/product-1.2.3.zip `
  --require-signature --public-key C:/trust/project-release-public.pem `
  --expected-public-key-sha256 <approved-sha256> `
  --expected-key-id project-release-2026 `
  --report build/reports/project-package-verify.json
```

验包过程不解压文件，会拒绝路径穿越、链接、重复/未知文件、大小超限、摘要变化、项目/锁/配置
身份不一致、畸形 SBOM 和不可信签名。验包通过证明的是“所验证 ZIP 的完整性和来源绑定”；仍不
替代目标机安装启动、HIL、真实设备和长稳验收。

建议先运行[产品项目统一资格流水线](project-pipelines.md)，再把其状态、CTest/colcon 日志和外部
验收证据纳入产品发布审批。`automatedComplete=true` 但 `releaseReady=false` 表示自动检查已经
完成、外部门禁仍待批准，不得按交付就绪处理。
