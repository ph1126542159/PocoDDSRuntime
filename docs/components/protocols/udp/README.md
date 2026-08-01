# UDP 协议组件

## 实现过程

`UdpChannel` 使用 Poco 网络 Socket 封装 UDP 绑定、发送和接收，并纳入统一协议启动/停止语义。打开、关闭、发送、接收和地址查询会串行化，避免并发关闭与 Socket 操作竞争。

## 用法

配置本地绑定地址/端口和目标地址/端口后启动通道，注册接收处理函数并发送数据报。应用层必须自行处理分片、顺序、重复、超时和校验。

UDP 不保证送达；需要请求/响应可靠性时应在业务层增加序号与重试，或选择 TCP 类协议。

## C++ 用法

```cpp
using PocoDDS::Protocols::UDP::UdpChannel;
UdpChannel::Options options{
    Poco::Net::SocketAddress("0.0.0.0", 5000),
    Poco::Net::SocketAddress("192.168.1.50", 5001)};
UdpChannel channel(std::move(options));
channel.open();
const std::uint8_t payload[] = {0x10, 0x20};
channel.send(payload, sizeof(payload));
auto packet = channel.receiveDatagram(2048, Poco::Timespan(1, 0));
if (packet.received) {
    // packet.bytes 与 packet.sender
}
channel.close();
```

`receiveDatagram(capacity, timeout)` 同时返回 payload、发送端地址和 `received` 标志，因此可以区分“收到合法零长度 UDP 数据报”和“等待超时”。原有 `receive()` 保持兼容，但空 vector 不能区分这两种情况。空 capacity、负超时、空指针非零发送以及超过底层 int 范围的长度会被明确拒绝。

`diagnostics()` 返回公共 `ProtocolDiagnostics`，用于读取成功/失败操作、收发数据报与字节、超时和最近错误；快照读取与收发操作均有线程保护。

capacity 太小仍可能由操作系统截断数据报；生产配置必须按协议最大报文设置上限。当前没有 `pdr.udp.*`，调用者应配置 bind address、local/remote port、最大报文和超时后自行构造。

## 故障排查

- `open()` 地址占用：检查同一 IP/端口是否被其他进程绑定。
- 只能发送不能接收：检查本地 bind address、防火墙和对端返回端口。
- 丢包：检查接收处理是否阻塞、Socket 缓冲区以及应用层序号。
- 大包异常：避免超过路径 MTU，必要时在业务层分片并校验。

UDP 没有连接状态握手，`isOpen()` 只表示本地 Socket 已打开，不代表远端在线。

`udp-smoke` 使用两个真实本地 UDP Socket 验证二进制 payload、发送端地址、超时语义、容量校验和关闭状态；它不证明跨主机防火墙、MTU、组播、突发丢包或长期吞吐。
