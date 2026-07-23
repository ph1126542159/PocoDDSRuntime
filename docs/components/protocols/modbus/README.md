# Modbus TCP 协议组件

## 实现过程

`ModbusTcpCodec` 编解码 MBAP 头、功能码、寄存器数据和异常响应；`ModbusTcpClient` 管理 TCP 连接、事务 ID、请求发送和响应校验。

## 用法

创建设备网关时设置：

```properties
pdr.modbus.enabled = true
pdr.modbus.host = 192.168.1.10
pdr.modbus.port = 502
pdr.modbus.unitId = 1
```

设备层的 `ModbusRegisterDevice` 在此客户端之上读写寄存器。配置地址前必须确认协议文档使用 PDU 0 基地址还是界面 1 基地址，并确认数值占用一个还是多个寄存器。

## 类与报文处理

| 类 | 作用 |
| --- | --- |
| `ModbusTcpCodec` | 构造 0x03、0x04、0x06 请求并校验/解析响应 |
| `ModbusTcpClient` | TCP 连接、事务 ID、互斥串行事务、超时和完整收发 |
| `Response` | transactionId、unitId、功能码、异常码和数据 |

客户端从事务 ID 1 开始递增。一次事务在互斥锁内完成，避免多线程响应交叉。功能码最高位为 1 时，响应转换为 `exception=true` 和 Modbus exception code。

## C++ 用法

```cpp
using namespace PocoDDS::Protocols::Modbus;
auto client = std::make_shared<ModbusTcpClient>(
    Poco::Net::SocketAddress("192.168.1.10", 502),
    Poco::Timespan(2, 0));
client->open();
auto values = client->readHoldingRegisters(1, 0x006E, 2);
client->writeSingleRegister(1, 0x0070, 100);
client->close();
```

`address` 是 PDU 0 基地址。显示地址 `40001` 通常对应 PDU 地址 `0`，但必须以设备协议为准。多寄存器浮点还需在设备层明确 ABCD/BADC/CDAB/DCBA 字序。

## DeviceGateway 配置

| 键 | 默认值 | 含义 |
| --- | --- | --- |
| `pdr.modbus.enabled` | `false` | 是否创建设备 |
| `pdr.modbus.host` | `127.0.0.1` | Modbus TCP Server |
| `pdr.modbus.port` | `502` | TCP 端口 |
| `pdr.modbus.unitId` | `1` | Unit Identifier |

当前配置创建一个 `modbus-1` 设备；寄存器地址由设备操作载荷传入。验收应同时检查请求 PDU、响应 PDU 和最终设备值。
