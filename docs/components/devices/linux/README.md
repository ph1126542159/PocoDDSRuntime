# Linux GPIO/LED 设备

## 实现过程

`LinuxSysfsGpioDevice` 通过 sysfs 导出、设置方向并读写 GPIO；`LinuxSysfsLedDevice` 写入 Linux LED class 的 brightness 路径。

## 用法

GPIO 使用 `pdr.gpio.pin`、`direction`、`sysfsRoot` 和 `manageExport`；LED 使用 `pdr.led.id` 与 `pdr.led.path`。设置对应的 `enabled=true` 后启动运行时。

该组件依赖 Linux 内核导出的节点和进程权限。新内核若关闭旧 GPIO sysfs ABI，需要新增字符设备后端。

## GPIO 操作和路径

启用 `manageExport=true` 时，start 会向 `${sysfsRoot}/export` 写 pin，并等待 `gpioN/` 出现；随后向 direction 写 `in/out`。value 文件用于读写。

| operation | payload | 说明 |
| --- | --- | --- |
| `read` | 空 | 返回 `0/1` |
| `write` | `0` 或 `1` | 仅输出 GPIO |
| `toggle` | 空 | 读取后反转，仅输出 GPIO |

```properties
pdr.gpio.enabled = true
pdr.gpio.pin = 17
pdr.gpio.direction = out
pdr.gpio.sysfsRoot = /sys/class/gpio
pdr.gpio.manageExport = true
```

## LED 操作

LED 路径下必须存在 `brightness`，实现用 0.0–1.0 归一化亮度：

| operation | payload |
| --- | --- |
| `read` | 空 |
| `on` / `off` | 空 |
| `set` | 浮点亮度 |

```properties
pdr.led.enabled = true
pdr.led.id = status-led
pdr.led.path = /sys/class/leds/status
```

目标板验收需同时读取 sysfs 节点并观察物理引脚/LED，软件返回成功不是物理闭环证据。
