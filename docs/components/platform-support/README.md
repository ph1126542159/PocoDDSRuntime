# 平台辅助组件

## 组件

- [CodeGeneration](code-generation/README.md)：基于代码模型和模板生成 C++ 文件。
- [Geo](geo/README.md)：角度、经纬度及地理计算。
- [Serial](serial/README.md)：跨平台串口底层封装。
- [WebTunnel](web-tunnel/README.md)：本地/远程端口转发。

## 实现与用法

这些组件从 Poco/macchina.io 体系迁移为可独立链接的库，由根 CMake 统一构建并导出相应 `Poco::*` 目标。消费端在 CMake 中链接所需目标，在代码中包含对应 `include/Poco/...` 头文件。具体实现和使用方法见各自 README。

设备串口通信通常优先使用更上层的 `PocoDDS::SerialProtocol`；只有需要直接控制串口参数时才使用 `Poco::Serial`。WebTunnel 的业务服务描述接口位于协议适配层，实际转发实现位于平台库。

## 构建和配置边界

这些库均由根 `CMakeLists.txt` 无条件加入，安装头文件和库到统一 prefix。它们不直接读取 `pdr-runtime.properties`；上层协议、设备或 Bundle 负责把配置转换为构造参数。

```cmake
find_package(PocoDDSRuntime CONFIG REQUIRED)
target_link_libraries(my_target PRIVATE
    Poco::CodeGeneration
    Poco::Geo
    Poco::Serial
    Poco::WebTunnel)
```

应只链接实际使用的库。跨平台部署时重点验证 Serial 的 Win32/POSIX 差异和 WebTunnel 的网络权限。
