# Geo 组件

## 实现过程

`platform/Geo` 提供 `Angle` 与 `LatLon`，集中处理角度表示、规范化和经纬度计算，并通过 `Poco::Geo` 目标导出。

## 用法

在 CMake 中链接 `Poco::Geo`，包含 `Poco/Geo/Angle.h` 或 `Poco/Geo/LatLon.h`。输入坐标前明确度/弧度和经纬顺序，边界场景用 `platform/Geo/testsuite` 验证。
