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

payload 两项均按无符号整数解析，数量错误、非法数值或未知 operation 会抛异常。每次操作都会更新 sequence 和 SnapshotHandler；失败时状态进入 `fault`，成功恢复后回到 `ready`。

## 生命周期与配置

`start()` 打开共享 `ModbusTcpClient` 并把状态设为 ready；`stop()` 关闭客户端并进入 offline。网关支持旧式单实例配置，也支持 `pdr.modbus.count` 和 `pdr.modbus.N.*` 多实例配置；一个设备实例对应一个 Unit ID。

`timeoutMilliseconds` 控制连接和响应超时，`readRetryAttempts` 与 `retryDelayMilliseconds` 控制安全读操作的断线重连。读操作失败后连接会被废弃并重新建立；写寄存器不自动重放，因为连接中断时无法可靠判断设备是否已经执行该写入。调用方应先读取设备状态或寄存器值，再按业务幂等规则决定是否补写。

设备实现 `DiagnosticDevice`，通过 `/api/v1/devices` 暴露成功/失败操作数、连续失败、重连次数、最后成功/失败时间和最后错误。仓库中的 `modbus-device-recovery` 验证“首次断线、读重连成功、写不重放”，`runtime-modbus-reference-smoke` 验证该诊断信息确实穿过 Bundle 边界进入运行时 API。

地址是 PDU 0 基地址，当前设备只返回原始 `uint16_t`，不自动组合 float/int32 或应用比例。
