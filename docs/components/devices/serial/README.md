# 串口设备

## 实现过程

`SerialPortDevice` 将 `SerialChannel` 适配为设备模型，对外提供串口设备状态和字节流操作。

## 用法

```properties
pdr.serial.enabled = true
pdr.serial.port = COM18
pdr.serial.baudRate = 115200
```

启动运行时后检查端口打开日志和设备状态。端口不能同时被多个进程独占打开；调试工具使用前应先停用网关中的串口设备。
