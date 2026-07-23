# GNSS 设备

## 实现过程

`NmeaGnssDevice` 从串口接收 NMEA 文本，解析定位信息并形成 GNSS 设备快照。串口传输由协议/平台串口组件提供。

## 用法

```properties
pdr.gnss.enabled = true
pdr.gnss.port = COM18
pdr.gnss.baudRate = 9600
```

Linux 将端口改为实际设备节点。验证应检查串口原始 NMEA、定位有效标志和网关发布的设备状态，室内无定位不等于串口故障。

## 解析流程

后台线程按行读取串口，先校验 `$...*HH` XOR checksum，再解析支持的 NMEA 定位语句。经纬度从 `ddmm.mmmm/dddmm.mmmm` 转十进制度，并根据 N/S/E/W 添加符号。有效定位更新快照和回调。

## 操作

| operation | 返回 |
| --- | --- |
| `position` | 当前位置 JSON/载荷 |
| `hasFix` | 当前是否有有效定位 |

```cpp
NmeaGnssDevice gnss("gnss-1", "COM18", 9600);
gnss.start();
auto fixed = gnss.execute("hasFix", "");
auto position = gnss.execute("position", "");
gnss.stop();
```

测试也可使用只传 ID 的构造函数，然后调用 `ingestSentence()` 注入 NMEA，而不打开真串口。

配置只有 enabled、port、baudRate。数据位/校验和 NMEA 更新频率由 GNSS 模块自身配置决定。
