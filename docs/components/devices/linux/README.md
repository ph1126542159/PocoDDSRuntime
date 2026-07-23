# Linux GPIO/LED 设备

## 实现过程

`LinuxSysfsGpioDevice` 通过 sysfs 导出、设置方向并读写 GPIO；`LinuxSysfsLedDevice` 写入 Linux LED class 的 brightness 路径。

## 用法

GPIO 使用 `pdr.gpio.pin`、`direction`、`sysfsRoot` 和 `manageExport`；LED 使用 `pdr.led.id` 与 `pdr.led.path`。设置对应的 `enabled=true` 后启动运行时。

该组件依赖 Linux 内核导出的节点和进程权限。新内核若关闭旧 GPIO sysfs ABI，需要新增字符设备后端。
