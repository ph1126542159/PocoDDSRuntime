# Linux GPIO/LED 设备

## 实现过程

`LinuxSysfsGpioDevice` 通过 sysfs 导出、设置方向并读写 GPIO；`LinuxSysfsLedDevice` 写入 Linux LED class 的 brightness 路径。

## 用法

GPIO 使用 `pdr.gpio.pin`、direction、sysfsRoot、manageExport 和 exportTimeoutMilliseconds；LED 使用 `pdr.led.id` 与 `pdr.led.path`。设置对应的 `enabled=true` 后启动运行时。

该组件依赖 Linux 内核导出的节点和进程权限。新内核若关闭旧 GPIO sysfs ABI，需要新增字符设备后端。

## GPIO 操作和路径

启用 `manageExport=true` 时，如果 `gpioN/` 尚不存在，start 会向 `${sysfsRoot}/export` 写 pin，并在配置超时内等待节点出现；随后向 direction 写 `in/out`。如果节点启动前已经存在，框架不会声明其所有权，停止时也不会误写 unexport。value 文件用于读写。

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
pdr.gpio.exportTimeoutMilliseconds = 1000
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

## 状态、诊断与恢复

- GPIO 方向配置成功、LED max_brightness 有效后进入 `ready`。
- value/brightness 节点读取或写入失败时进入 `fault`，错误写入设备诊断；节点恢复后下一次成功读写可自动回到 `ready`。
- `snapshot()` 在设备停止或节点消失时不再向 API 抛异常，而是返回 `offline`/`fault` 及错误 payload。
- 成功/失败次数、连续失败和最近错误通过 `/api/v1/devices` 可见；必需设备故障会使 `/health/ready` 返回 503。
- GPIO value 与 LED snapshot 回调异常被隔离，不会让设备操作失败。

`linux-sysfs-recovery` 使用临时 sysfs 树覆盖节点消失、恢复、回调异常和“预先存在的 GPIO 不得 unexport”；`runtime-linux-sysfs-reference-smoke` 覆盖 DeviceGateway、API、诊断和 readiness。真实 Linux 内核 ABI、权限、pinmux、电气方向和物理 LED 仍需目标板验证。
