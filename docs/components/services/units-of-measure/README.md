# UnitsOfMeasure 服务

## 实现过程

服务从 Bundle 内的 `ucum-essence.xml` 解析 UCUM 前缀和单位，提供单位查找、兼容性判断和规范化换算；Activator 同时注册 OSP 服务并开放 DDS 请求/响应端点。

## 用法

把 Bundle 放入运行时 `bundles/` 后启动。进程内通过 OSP Registry 获取 `UnitsOfMeasureService`；跨进程向 `pdr.units.request` 发送请求并监听 `pdr.units.response`。

换算前必须确认两个单位属于相同量纲。
