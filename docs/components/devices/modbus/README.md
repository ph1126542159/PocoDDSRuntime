# Modbus 寄存器设备

## 实现过程

`ModbusRegisterDevice` 在 `ModbusTcpClient` 上把寄存器读写映射为统一设备状态和控制操作，设备层负责寄存器语义，协议层负责报文和连接。

## 用法

先配置并启用 `pdr.modbus.*`，再由网关创建 Modbus 设备。调试时同时记录请求 PDU、响应 PDU 和最终设备值。

寄存器地址、字节序、数据类型和缩放必须来自设备协议；不能仅凭界面显示地址推断 PDU 地址。

## 支持的操作

| operation | payload | 返回值 |
| --- | --- | --- |
| `readHolding` | `address,count` | 逗号分隔的 16 位无符号数 |
| `readInput` | `address,count` | 逗号分隔的 16 位无符号数 |
| `writeRegister` | `address,value` | 写入后的结果字符串 |

示例：

```cpp
auto result = device.execute("readHolding", "16,2");
// 可能返回 "100,200"
device.execute("writeRegister", "18,300");
```

payload 两项均按无符号整数解析，数量错误、非法数值或未知 operation 会抛异常。每次成功操作都会更新 `_lastPayload`、sequence 和 SnapshotHandler。

## 生命周期与配置

`start()` 打开共享 `ModbusTcpClient` 并把状态设为 ready；`stop()` 关闭客户端并进入 offline。网关固定创建 ID `modbus-1`，配置来自 `pdr.modbus.host/port/unitId`。当前一个设备对应一个 Unit ID；多从站部署需要扩展网关为设备列表。

地址是 PDU 0 基地址，当前设备只返回原始 `uint16_t`，不自动组合 float/int32 或应用比例。
