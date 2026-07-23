# Serial 底层组件

## 实现过程

`platform/Serial` 定义统一 `SerialPort`，并分别由 `SerialPort_WIN32.cpp` 和 `SerialPort_POSIX.cpp` 实现 Windows 与 POSIX 的打开、配置、读写和关闭。

## 用法

在 CMake 中链接 `Poco::Serial`，创建 `SerialPort` 并设置端口、波特率、数据位、停止位和校验。通常业务代码应使用上层 `SerialChannel`，只有需要直接串口控制时才使用本组件。

端口名称和访问权限由操作系统决定，部署前必须在目标机实测。
