# GNSS 设备

## 实现过程

`NmeaGnssDevice` 从串口接收 NMEA 文本，解析定位信息并形成 GNSS 设备快照。串口传输由协议/平台串口组件提供。

## 用法

```properties
pdr.gnss.enabled = true
pdr.gnss.transport = port
pdr.gnss.port = COM18
pdr.gnss.baudRate = 9600
pdr.gnss.reconnectEnabled = true
pdr.gnss.reconnectDelayMilliseconds = 250
pdr.gnss.readTimeoutMilliseconds = 250
pdr.gnss.staleAfterMilliseconds = 5000
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

## 状态、恢复与诊断

- 串口打开后仍是 `offline`，只有校验通过且声明有效定位的 RMC/GGA 才进入 `ready`。
- RMC `V` 或 GGA fix quality `0` 会清除定位有效性并进入 `offline`。
- 串口读异常进入 `fault`；启用恢复后会关闭并重开串口，重连后保持 `offline`，直到收到新的有效 fix。
- 有效定位超过 `staleAfterMilliseconds` 未刷新会进入 `offline`，诊断错误为 `GNSS fix stale`。
- checksum 或字段格式错误会计入失败诊断，但单个坏句不会抹掉仍在新鲜窗口内的最后有效 fix。
- 定位和快照回调的异常被隔离，不会终止采集线程。

`/api/v1/devices` 会公开成功/失败次数、连续失败、重连次数和最近错误。设备默认 `required=true`，因此无 fix、陈旧或故障会使 `/health/ready` 返回 503；可选 GNSS 应显式配置 `required=false`。

## Loopback 与真实验收边界

开发和 CI 可使用 `transport=loopback` 验证 Bundle、API、诊断和 readiness 路径；生产安全门禁禁止 GNSS loopback。该路径不证明真实 GNSS 模块、电平、波特率、天线、卫星可见度、首次定位时间或长期漂移，仍需目标机 HIL 验收。

测试也可使用只传 ID 的构造函数，然后调用 `ingestSentence()` 注入 NMEA，而不打开真串口。

配置只有 enabled、port、baudRate。数据位/校验和 NMEA 更新频率由 GNSS 模块自身配置决定。
