# UDP 协议组件

## 实现过程

`UdpChannel` 使用 Poco 网络 Socket 封装 UDP 绑定、发送和接收，并纳入统一协议启动/停止语义。

## 用法

配置本地绑定地址/端口和目标地址/端口后启动通道，注册接收处理函数并发送数据报。应用层必须自行处理分片、顺序、重复、超时和校验。

UDP 不保证送达；需要请求/响应可靠性时应在业务层增加序号与重试，或选择 TCP 类协议。

## C++ 用法

```cpp
using PocoDDS::Protocols::UDP::UdpChannel;
UdpChannel channel(
    Poco::Net::SocketAddress("0.0.0.0", 5000),
    Poco::Net::SocketAddress("192.168.1.50", 5001));
channel.open();
const std::uint8_t payload[] = {0x10, 0x20};
channel.send(payload, sizeof(payload));
auto packet = channel.receive(2048, Poco::Timespan(1, 0));
channel.close();
```

`receive(capacity, timeout)` 返回一个数据报；capacity 太小会截断。当前没有 `pdr.udp.*`，调用者应配置 bind address、local/remote port、最大报文和超时后自行构造。

## 故障排查

- `open()` 地址占用：检查同一 IP/端口是否被其他进程绑定。
- 只能发送不能接收：检查本地 bind address、防火墙和对端返回端口。
- 丢包：检查接收处理是否阻塞、Socket 缓冲区以及应用层序号。
- 大包异常：避免超过路径 MTU，必要时在业务层分片并校验。

UDP 没有连接状态握手，`isOpen()` 只表示本地 Socket 已打开，不代表远端在线。
