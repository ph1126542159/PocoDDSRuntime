# 产品项目统一资格流水线

`pdr project pipeline` 把每个产品都应执行的自动步骤生成成同一种哈希绑定计划，并复用框架的
可恢复阶段执行器。计划中的命令以参数数组直接启动，不经过 shell 拼接；源码 Git commit、工作区
改动摘要、计划摘要和每个声明输出都进入断点状态。

## 创建计划

```powershell
$Pdr = "$env:PDR_SDK_PREFIX/bin/pdr.py"
python $Pdr project pipeline create pdr-project.yaml `
  --sdk-prefix $env:PDR_SDK_PREFIX `
  --cmake C:/Qt/Tools/CMake_64/bin/cmake.exe `
  --ctest C:/Qt/Tools/CMake_64/bin/ctest.exe `
  --build-root build/qualification `
  --output build/qualification/plan.json
```

`pdr-project.yaml.version` 是产品自身的具体 SemVer，不是 Runtime 版本范围。创建项目时用
`project create --version 1.0.0`，已有项目用 `project version pdr-project.yaml 1.0.0` 设置；计划、
外部验收和交付包必须使用同一个版本。

生成器先完整验证 Manifest、项目模板和所有带 `.pdr-component.json` 的组件，然后生成固定顺序：

1. `project validate`；
2. `project resolve`，产生源码树绑定锁；
3. `project config resolve`；
4. CMake configure；
5. CMake build；
6. Manifest 要求 Unit 时执行 CTest，并用 `--no-tests=error` 拒绝“零测试通过”；
7. 存在 ROS 2 Adapter 时强制执行 `colcon build/test/test-result`。

ROS 2 阶段继承当前终端环境，因此运行前仍须 source 对应 ROS 2发行版和产品依赖 overlay。存在
已登记 ROS 2 Adapter 时不能通过选项静默跳过。额外 CMake 定义使用可重复的
`--cmake-argument=-DNAME=VALUE`，不会写入项目模板。

框架 CI 在 Windows 和 Linux 都会先安装机器人 SDK，再创建一个全新的产品仓库、生成
`robot-module`，并通过安装后的 `pdr.py` 完成 configure/build/CTest 流水线。这项门禁验证的是
“外部产品可消费已安装 SDK”，不是仅在框架源码树内链接成功。

## 执行、续跑和状态

项目仓库必须已经初始化 Git 并提交候选基线；构建目录应由 `.gitignore` 排除：

```powershell
python $Pdr project pipeline run `
  --plan build/qualification/plan.json `
  --state build/qualification/state.json --confirm-run

python $Pdr project pipeline resume `
  --plan build/qualification/plan.json `
  --state build/qualification/state.json --confirm-run

python $Pdr project pipeline status `
  --plan build/qualification/plan.json `
  --state build/qualification/state.json
```

新执行要求 `--confirm-run` 且拒绝覆盖已有状态。失败或中断后只能在计划、Git commit 和未提交
工作区摘要都未改变时续跑；已完成阶段的声明输出会重新核对大小和 SHA-256。源码或计划改变后
应使用新的状态路径重新执行，不能把旧证据嫁接到新候选。

## 自动证据与外部证据边界

计划 `metadata` 根据 `acceptance.unit/sil/hil/soakHours` 明确列出自动门禁和外部门禁。框架只会
自动声明它真正执行过的检查：

- CTest 可以证明项目构建树中的自动测试；
- ROS 2阶段可以证明当前环境中的 colcon 构建和测试；
- SIL 必须提供具体模拟器、场景和确定性结果；
- HIL 必须提供真实硬件拓扑、双向业务闭环和故障注入结果；
- 长稳必须提供实际时长、资源增长、错误预算和恢复记录。

因此，自动阶段全部完成但仍有 SIL/HIL/长稳要求时，`project pipeline status` 返回 2，
`releaseReady=false`。这不是流水线失败，而是候选尚缺外部验收；不得手改计划元数据绕过。外部证据
使用 `project-sil`、`project-hil`、`project-soak` 三种签名类型。模板必须绑定自动阶段生成的项目锁、
Git commit 和产品版本；长稳还必须绑定 Manifest 要求的最小时长：

```powershell
$Commit = git rev-parse HEAD
python $Pdr release external-template --type project-hil `
  --version 1.0.0 --git-commit $Commit `
  --artifact-manifest build/qualification/pdr-project.lock.json `
  --output build/acceptance/hil-template.json

python $Pdr release external-template --type project-soak `
  --version 1.0.0 --git-commit $Commit `
  --artifact-manifest build/qualification/pdr-project.lock.json `
  --requirement minimumHours=72 `
  --output build/acceptance/soak-template.json
```

实验室按模板的每一个 Check ID 提供附件并执行 `release external-approve`。发布端必须固定 Trust
Policy ID、Policy SHA-256 和原生签名校验器，再把报告与签名汇入状态：

```powershell
python $Pdr project pipeline status `
  --plan build/qualification/plan.json `
  --state build/qualification/state.json `
  --external-evidence hil=build/acceptance/hil-approved.json `
  --external-signature hil=build/acceptance/hil-approved.sig.json `
  --trust-policy site/project-approvers.json `
  --expected-trust-policy-id project-qa-2026 `
  --expected-trust-policy-sha256 <approved-policy-sha256> `
  --signature-check-executable $env:PDR_SDK_PREFIX/bin/pdr-signature-check.exe
```

报告类型、产品版本、Git commit、项目锁摘要、最小时长、附件摘要、Approver/Key 权限、有效期或
吊销状态任一不匹配都会拒绝。所有外部门禁均验证为 `APPROVED` 后才返回
`releaseReady=true`。
