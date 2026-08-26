# SDK API 与 ABI 兼容门禁

PocoDDSRuntime 以安装后的 SDK 为兼容性事实源，而不是以源码目录或某个示例能否编译作为结论。`sdk-public-surface-compatibility` 会先将当前构建安装到隔离目录，再与 `contracts/compatibility/sdk-surface-0.1.0.json` 比较。

## 保护边界

- 跨平台 API：自动发现 `include/PocoDDS` 下全部公共 C/C++ 头文件，去除注释和空白后计算 token 摘要。注释与格式调整不会误报；声明、签名、宏或类型的 token 变化会被识别。
- CMake SDK：自动发现已安装包导出的全部 `PocoDDS::` library target，阻止同一主版本删除 target。
- Windows ABI：在与基线相同的 ABI key 下，通过 `dumpbin /exports` 比较全部已安装 `PDR*.dll` 的导出符号集合。Windows 测试要求 ABI 证据存在。
- Linux：当前只执行公共头文件与 CMake target 门禁。Windows 的 MSVC 导出符号基线不能当作 Linux ELF ABI 验收；Linux ABI 需要在 Linux CI 中建立独立基线后才算覆盖。
- 头文件自包含：完整 Server 安装树把每个 `include/PocoDDS` 头文件作为独立翻译单元编译，防止公共 API 依赖调用方的 include 顺序或仓库内部搜索路径。

新增头文件、CMake target 或 DLL 是兼容扩展并会记录在报告中。删除公共头文件、修改现有头文件 token、删除 CMake target、删除 DLL 或改变 DLL 导出符号，在主版本不变时失败。提升 Runtime 主版本只是必要条件；破坏性变更还必须通过下面的弃用生命周期门禁。

## 弃用与移除生命周期

公共 SDK 不能“升级主版本后直接删除”。每个计划移除的表面必须在 `contracts/sdk-deprecations.json` 注册，并绑定首次发布弃用公告的完整 SDK 快照：

1. 公共头文件先加入标准标记，例如 `[[deprecated("PDR-DEP-0001: use CoreAPI")]]`。标记 ID 必须与目录中的 header 和 Owner 一致；未注册标记会失败。
2. 生成当前 SDK 快照后，用 `sdk_deprecation_guard.py register` 记录 `deprecatedSince` 和 `noticeSurfaceSha256`。CMake target 与 ABI artifact 没有源码标记，但同样需要目录记录。
3. 包含弃用公告的快照必须以 `contracts/compatibility/sdk-surface-<version>.json` 作为已发布快照保留；构建门禁会自动加载全部此类快照。仅存在于当前未发布候选中的公告，不能作为删除依据。
4. `removalAllowedFrom` 必须晚于弃用版本且属于更高主版本。到期后将条目显式改为 `removed`，才允许删除或改变该表面。
5. 已移除表面仍保留为历史记录。未排期、仍为 `active`、公告未发布或提前移除都会阻断发布测试。

当前头文件快照以“整个公共头文件的 token 摘要”为治理粒度，并不是 C++ 单个声明级 ABI 模型。因此修改或删除头文件内任一既有声明时，需要该头文件级生命周期记录；报告不会伪称已经精确识别某个 C++ symbol。标准 `PDR-DEP` deprecated 属性本身从 token 摘要中排除，以便先发布警告而不把警告误判为破坏性变更；其他未治理的 deprecated 属性仍按表面变化处理。

注册示例：

```powershell
python tools/sdk_deprecation_guard.py register `
  --catalog contracts/sdk-deprecations.json `
  --snapshot build/profiles/server/reports/sdk-public-surface.json `
  --install build/profiles/server/sdk-surface-install `
  --id PDR-DEP-0001 --kind header `
  --surface include/PocoDDS/SDK/SDK.h `
  --symbol LegacyAPI --replacement CoreAPI `
  --owner team/sdk --removal-allowed-from 2.0.0
```

## 本地验证

```powershell
cmake --build build/profiles/server --config Release
ctest --test-dir build/profiles/server -C Release -R "sdk-public-surface-compatibility" --output-on-failure
```

报告写入：

- `build/profiles/server/reports/sdk-public-surface.json`
- `build/profiles/server/reports/sdk-public-surface-compatibility.json`
- `build/profiles/server/reports/sdk-deprecation-policy.json`

需要接受兼容性破坏时，先完成至少一个已发布版本的弃用公告，再到目录约定的后续主版本执行移除；随后从实际安装树生成新版本基线并由 SDK 所有者评审。不能手工只改摘要；工具会校验总摘要、逐文件记录、目录和发布快照身份的一致性。
