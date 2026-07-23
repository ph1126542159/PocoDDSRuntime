# Serial 底层组件

## 实现过程

`platform/Serial` 定义统一 `SerialPort`，并分别由 `SerialPort_WIN32.cpp` 和 `SerialPort_POSIX.cpp` 实现 Windows 与 POSIX 的打开、配置、读写和关闭。

## 用法

在 CMake 中链接 `Poco::Serial`，创建 `SerialPort` 并设置端口、波特率、数据位、停止位和校验。通常业务代码应使用上层 `SerialChannel`，只有需要直接串口控制时才使用本组件。

端口名称和访问权限由操作系统决定，部署前必须在目标机实测。

## 平台实现

- Windows：`SerialPort_WIN32.cpp`，使用 Win32 HANDLE、DCB 和通信超时。
- POSIX：`SerialPort_POSIX.cpp`，使用文件描述符和 termios。
- 公共层：`SerialPort.cpp` 统一参数、状态和异常。

## 直接调用示例

```cpp
#include <Poco/Serial/SerialPort.h>

Poco::Serial::SerialPort port("COM18");
port.setBaudRate(115200);
port.open();
// 使用公共读写 API
port.close();
```

具体可设置项以 `SerialPort.h` 为准。库本身不读取 properties；`pdr.serial.*` 和 `pdr.gnss.*` 是 DeviceGateway 的配置。

构建目标为 `Poco::Serial`。上层 `PocoDDS::SerialProtocol` 已封装常见生命周期，通常应优先使用。
