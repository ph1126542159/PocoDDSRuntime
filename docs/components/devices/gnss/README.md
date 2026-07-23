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
