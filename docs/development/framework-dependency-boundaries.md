# 框架源码与 CMake 链接依赖边界

`contracts/framework-components.json` 不只是变更影响目录，其中每个组件的 `requires` 同时是生产源码
允许使用的直接组件依赖。`tools/framework_dependency_boundary.py` 从所有组件的 `include/` 目录建立
公共头文件所有权索引，再扫描 `.h/.hpp/.c/.cpp` 生产源码中的 `#include`。

```powershell
python tools/framework_dependency_boundary.py validate `
  --root . `
  --catalog contracts/framework-components.json `
  --report build/reports/framework-dependency-boundary.json
```

校验遵循以下边界：

- 组件可以包含自己的公共头文件；
- 跨组件头文件只能来自该组件直接列出的 `requires`，不能借用传递依赖；
- 即使已经声明 `requires`，也只能包含 Provider 的公共 `include/` 头文件；通过相对路径或仓库路径直接包含其他组件的 `src/`、内部头文件会无条件失败；
- 同一 include 名称由两个组件发布时 fail-closed；
- `tests`、`testsuite`、`samples`、`examples`、`tools` 和 benchmark 目录不计入生产依赖；
- 报告保留 Consumer、Provider、源码文件、行号和 include 名称，便于 Owner 直接定位。

新增依赖时，优先把稳定接口下沉到较低层组件。只有业务上确实存在直接依赖时才修改 `requires`；
不得为了让门禁变绿而添加双向依赖或把所有组件加入允许列表。Catalog 自身拒绝依赖环。

当前目录把 OSP 核心与 OSP 管理扩展、协议与设备、低层平台适配器与 DDS/进程集成分别建模，
避免用一个粗粒度“platform”组件隐藏反向依赖。测试代码可以组合多个组件，但不能改变生产依赖方向。

## CMake target 直接链接边界

源码没有 `#include` 不代表没有链接耦合。顶层配置结束时，
`cmake/PDRFrameworkLinkManifest.cmake` 会从 CMake 的 `BUILDSYSTEM_TARGETS`、`LINK_LIBRARIES`
和 `INTERFACE_LINK_LIBRARIES` 导出当前 Profile 的真实直接链接清单，并解析工程内 Alias target。
随后执行：

```powershell
python tools/framework_link_dependency_boundary.py validate `
  --root . `
  --catalog contracts/framework-components.json `
  --manifest build/profiles/server/reports/framework-link-manifest.json `
  --expect-profile server `
  --report build/profiles/server/reports/framework-link-dependency-boundary.json
```

链接门禁遵循同一份 `requires` 直接依赖图，并额外保证：

- 生产 target 必须由组件路径或唯一 `buildTargets` 声明归属；
- 一个 target 混入多个组件的源码时 fail-closed；
- 直接链接不能借用传递依赖；
- Target 不能把其他组件的源码根、`src/` 或内部目录加入自己的直接 include directory；跨组件只能暴露包含 `include/` 边界的公共目录；
- 无法解析的 include-directory 生成表达式与无法解析的链接表达式一样 fail-closed；
- 无法解析的工程链接生成表达式不能静默跳过；
- manifest 的 Profile 身份必须与当前验收 Profile 一致，禁止复用其他构建的旧报告；
- Utility、测试、示例和工具 target 不污染生产链接边界；
- 报告保留 Consumer/Provider component、双方 target 和源码目录证据。

`sdk` 与 `plugin-sdk` 是显式聚合组件，不再藏在全局目录中。前者聚合公共 C++ SDK，后者聚合
OSP 插件开发接口；修改它们会沿反向依赖图选择真实消费者。链接清单是构建输入证据，边界报告才是
验收证据，两者都由 CI 保存。

CI 的便携任务分别在 `desktop-distributed`、`robotics` 配置后立即执行门禁；full-stack 任务还会
配置 `desktop-lite`、`desktop-distributed`、`robotics`、`embedded`、`edge-industrial`、
`edge-test` 和 `server`，并汇总完整矩阵。每个 Profile 保存自己的 manifest 与 boundary report。
便携 Profile 在顶层提前返回前也必须生成清单，因此不会再绕过链接架构检查。

全部命名 Profile 完成后，用矩阵命令收口证据：

```powershell
python tools/framework_link_dependency_boundary.py matrix `
  --required-profile desktop-lite --profile-report build/profiles/desktop-lite/reports/framework-link-dependency-boundary.json `
  --required-profile desktop-distributed --profile-report build/profiles/desktop-distributed/reports/framework-link-dependency-boundary.json `
  --required-profile robotics --profile-report build/robotics/reports/framework-link-dependency-boundary.json `
  --required-profile embedded --profile-report build/profiles/embedded/reports/framework-link-dependency-boundary.json `
  --required-profile edge-industrial --profile-report build/profiles/edge-industrial/reports/framework-link-dependency-boundary.json `
  --required-profile edge-test --profile-report build/profiles/edge-test/reports/framework-link-dependency-boundary.json `
  --required-profile server --profile-report build/profiles/server/reports/framework-link-dependency-boundary.json `
  --output build/reports/framework-link-dependency-matrix.json
```

矩阵要求 Profile 集合精确匹配；缺失、重复、意外 Profile、报告内部状态不一致或任一边界失败都会
返回非零。它是“所有命名构建路径均受控”的最终机器证据，不用单个 server PASS 代替矩阵验收。
