# Geo 组件

## 实现过程

`platform/Geo` 提供 `Angle` 与 `LatLon`，集中处理角度表示、规范化和经纬度计算，并通过 `Poco::Geo` 目标导出。

## 用法

在 CMake 中链接 `Poco::Geo`，包含 `Poco/Geo/Angle.h` 或 `Poco/Geo/LatLon.h`。输入坐标前明确度/弧度和经纬顺序，边界场景用 `platform/Geo/testsuite` 验证。

## 使用边界

`Angle` 封装角度解析、格式化、规范化和度/弧度转换；`LatLon` 保存纬度/经度并提供地理计算。库不读取配置文件，也不负责 GNSS NMEA 解析。

```cmake
target_link_libraries(my_target PRIVATE Poco::Geo)
```

```cpp
#include <Poco/Geo/LatLon.h>
Poco::Geo::LatLon position(latitudeDegrees, longitudeDegrees);
```

经度范围、纬度范围、跨 180° 经线和极区输入必须加测试；不要把 `[lon,lat]` JSON 顺序直接当作构造参数顺序。

## 验证

仓库测试位于 `platform/Geo/testsuite`，覆盖 Angle 和 LatLon 的常规计算。新增算法时至少增加零点、负角度、±180°、两极和相同坐标用例，并使用已知地理工具结果交叉核对。

该库只做数学计算，不选择 WGS84 之外的坐标基准，也不进行 GCJ-02/BD-09 等转换。调用方应在接口层明确坐标系。
