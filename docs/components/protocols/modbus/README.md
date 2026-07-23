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
