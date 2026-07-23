# Modbus 寄存器设备

## 实现过程

`ModbusRegisterDevice` 在 `ModbusTcpClient` 上把寄存器读写映射为统一设备状态和控制操作，设备层负责寄存器语义，协议层负责报文和连接。

## 用法

先配置并启用 `pdr.modbus.*`，再由网关创建 Modbus 设备。调试时同时记录请求 PDU、响应 PDU 和最终设备值。

寄存器地址、字节序、数据类型和缩放必须来自设备协议；不能仅凭界面显示地址推断 PDU 地址。
