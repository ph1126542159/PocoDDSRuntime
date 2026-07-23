# UnitsOfMeasure 服务

## 实现过程

服务从 Bundle 内的 `ucum-essence.xml` 解析 UCUM 前缀和单位，提供单位查找、兼容性判断和规范化换算；Activator 同时注册 OSP 服务并开放 DDS 请求/响应端点。

## 用法

把 Bundle 放入运行时 `bundles/` 后启动。进程内通过 OSP Registry 获取 `UnitsOfMeasureService`；跨进程向 `pdr.units.request` 发送请求并监听 `pdr.units.response`。

换算前必须确认两个单位属于相同量纲。

## 初始化过程

Bundle 启动时从自身资源读取 `ucum-essence.xml`，`UCUMEssenceParser` 把 prefix、base-unit 和 unit 加入 `UnitsOfMeasureServiceImpl`。资源解析成功后才注册 `pdr.service.units` 并启动 DDS Endpoint；资源损坏会使 Bundle 启动失败。

## DDS 操作

| operation | 请求 payload | 响应 |
| --- | --- | --- |
| `format` | `{"code":"Cel"}` | `{"value":"..."}` |
| `canonicalize` | `{"value":100,"code":"cm"}` | 基准值和 code |
| `convert` | `{"value":1,"from":"m","to":"cm"}` | `{"value":100}` |
| `findUnit` | `{"code":"m"}` | found、code、name、print、property |

未知操作返回 status 400；找不到单位时 `findUnit` 返回 status 404 和 `found=false`。Topic 为 `pdr.units.request/response`，Domain 使用 `pdr.fastdds.domainId`。

## 进程内用法

通过 OSP Registry 查找 `pdr.service.units` 或 `UnitsOfMeasureService`，调用 `findUnit()`、`resolve()`、`format()`、`canonicalize()`、`convert()`。本服务没有独立 properties；其业务数据来自 Bundle 内 UCUM 文件。

## 验证与故障

```powershell
ctest --test-dir build -C Release -R units-smoke --output-on-failure
```

Bundle 启动时报资源错误时，检查 `.bndl` 中是否包含 `ucum-essence.xml`。换算失败时先调用 `findUnit`，再核对两个单位的 property/基准维度；大小写必须遵循 UCUM code。
