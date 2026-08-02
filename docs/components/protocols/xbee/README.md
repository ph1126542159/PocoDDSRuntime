# XBee 协议组件

## 实现过程

`XBeeFrame` 负责 API 帧构造、转义和增量解析；`IoSample` 表示数字量/模拟量采样；`XBeePort` 通过可注入串口通道发送和接收 XBee 帧。接收缓冲会跨超时保留分片，并能连续取出同一批字节中的多帧。

## 用法

设置串口、波特率及是否为 escaped API mode，再按源地址和通道解析 IO Sample。设备网关相关配置为 `pdr.xbee.*`。

模块的 AP 参数必须与 `escapedApiMode` 一致，否则帧边界或转义解析会失败。

## 帧处理

串口字节依次经过 0x7E 帧头、两字节长度、数据和 checksum 校验，再转换为 `XBeeFrame`；`IoSample::decode()` 提取数字和模拟通道。escaped 模式下 0x7E、0x7D、0x11、0x13 使用 0x7D 转义。

```cpp
using namespace PocoDDS::Protocols::XBee;
auto serial = std::make_shared<PocoDDS::Protocols::Serial::SerialChannel>(
    "COM18", 9600);
XBeePort port(serial, false);
port.open();
XBeeFrame frame;
if (port.receive(frame, Poco::Timespan(2, 0))) {
    auto sample = IoSample::decode(frame);
    if (sample.hasAnalog(0)) auto raw = sample.analog(0);
}
port.close();
```

配置由 DeviceGateway 读取。`sourceAddress` 按无分隔符十六进制解析；转换支持 `raw`、`millivolts`、`temperature`、`humidity`。温湿度换算必须与实际传感器电路匹配。
