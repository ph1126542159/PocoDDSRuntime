# BtLE 协议组件

## 实现过程

`platform/protocols/BtLE` 定义 `PeripheralBrowser`、`GattClient`、服务、特征、描述符和值事件等跨平台接口。目前 CMake 目标是 INTERFACE，仓库未提供具体蓝牙栈后端。

## 用法

业务代码面向这些接口编程，由目标平台注入扫描器和 GATT 客户端实现。连接前选择等待/非等待模式和安全级别，再发现服务、订阅特征或读写值。

仅链接该组件不会获得可工作的蓝牙适配器；部署前必须补充并验证平台后端。

## 接口与配置边界

`PeripheralBrowser` 提供扫描启停、发现和完成回调；`GattClient` 定义连接状态、安全级别、服务/特征/描述符发现、读写以及 notification/indication/error 回调。

仓库没有 Windows Bluetooth、BlueZ 或其他具体后端，也没有 `pdr.btle.*`。投入使用前必须实现平台工厂，并配置适配器、目标地址、服务 UUID、安全级别、超时和重连策略。当前组件只能作为上层代码的接口契约，不能独立进行真机扫描。

## 后端实现清单

平台 `GattClient` 需要实现连接/断开、当前 State、SecurityLevel、服务发现、特征/描述符发现、读写和订阅。异步错误调用 error handler，通知与 indication 分别调用对应 handler。`ConnectMode::Wait` 应在超时或结果明确后返回，`NoWait` 由状态回调报告结果。

```powershell
ctest --test-dir build -C Release -R btle-smoke --output-on-failure
```

现有 smoke 只验证接口模型，不会访问蓝牙适配器。后端完成后还需增加断电重连、配对失败、通知突发和多外设并发测试。
