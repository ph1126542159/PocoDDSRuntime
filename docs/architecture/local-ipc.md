# 本机 IPC Adapter

`PocoDDS::LocalIpc` 是 `desktop-distributed` 的本机跨进程传输边界。Windows 使用 Named
Pipe，Linux 使用 Unix Domain Socket；业务 Service 仍只依赖 `IMessageTransport`，不包含
Win32、POSIX、ROS 2、Fast DDS 或 Poco/OSP 头文件。

## 适用与不适用

- 适用：桌面 UI、算法、渲染、插件沙箱等同机多进程拓扑；
- 不适用：跨主机通信、强持久化队列、DDS QoS、ROS 2 Action、互联网暴露端点；
- 需要 Bundle 热管理、进程看护和统一治理时使用 `edge-test`/`edge-industrial`，不要把
  Desktop Host 扩成第二套 OSP。

## 使用

```cpp
#include <PocoDDS/LocalIpc/LocalIpcTransport.h>

using namespace PocoDDS::LocalIpc;

LocalIpcTransport server({"inspection-station", EndpointRole::server,
                          "load-from-secret-store"});
auto started = server.start();
if (!started) {
    // 记录 started.error().code / message，再决定退出或降级为单进程。
}
```

Consumer CMake：

```cmake
find_package(PDRRuntimeCore CONFIG REQUIRED)
find_package(PDRLocalIpc CONFIG REQUIRED)
target_link_libraries(my_process PRIVATE PocoDDS::RuntimeCore PocoDDS::LocalIpc)
```

同一端点只能有一个 Server，可有多个 Client。Server 接收 Client 消息后投递本地订阅者，
并转发给其他 Client；发送者自己的订阅在 `publish()` 时本地执行，不依赖 IPC 回环。

## 协议和约束

- 帧头：4 字节小端长度；外层认证封装为 `PDRI/2`，内部统一消息帧为 `PDRM/1`；
- 传输 Topic 契约、消息类型/Schema、Header、Payload 和 `MessageContext`；
- `steady_clock` 绝对时间不能跨进程，线上传输的是剩余截止毫秒；
- 默认最大帧 16 MiB，可用 `maximumFrameBytes` 下调；超限消息计入 `dropped`；
- 错误签名、错误版本、错误令牌、截断帧或超限帧会关闭对应 Peer，不能污染其他连接；
- 当前交付语义是进程内可靠投递加本机流式 IPC；没有落盘、确认重放或 exactly-once。

## 安全边界

`authenticationToken` 必须从受控配置或 Secret Store 注入，不能写死在业务源码。它用于
拒绝误连进程，但协议当前不加密，不能替代 Named Pipe/Unix Socket 的操作系统访问控制。
实现会拒绝远程 Named Pipe Client，并把 Unix Socket 权限设为 `0600`；Unix 部署仍应把
Socket 放入仅服务账户可访问的目录，Windows 安装器仍应限制服务账户和端点权限。跨用户、
提权边界或不可信插件需要独立安全评审。

## 验收

```powershell
cmake --preset desktop-distributed
cmake --build --preset desktop-distributed
ctest --preset desktop-distributed -C Release --output-on-failure
```

`local-ipc-smoke` 验证同进程两端的真实 OS 通道；`local-ipc-cross-process` 会创建真实子进程，
验证请求/响应双向闭环、子进程退出码与清理。Linux 实现仍必须由 Linux CI 编译并运行同一
测试后，才可作为 Linux 交付证据。
