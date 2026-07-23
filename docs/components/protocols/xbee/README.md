# XBee 协议组件

## 实现过程

`XBeeFrame` 负责 API 帧构造、转义和增量解析；`IoSample` 表示数字量/模拟量采样；`XBeePort` 通过串口发送和接收 XBee 帧。

## 用法

设置串口、波特率及是否为 escaped API mode，再按源地址和通道解析 IO Sample。设备网关相关配置为 `pdr.xbee.*`。

模块的 AP 参数必须与 `escapedApiMode` 一致，否则帧边界或转义解析会失败。
