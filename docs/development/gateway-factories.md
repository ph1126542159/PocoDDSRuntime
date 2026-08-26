# Gateway 工厂扩展

`PocoDDS::GatewayAPI` 是产品 Bundle 向 DeviceGateway 和 ProtocolGateway 注册具体实现的
公共管理层接口。它不属于 DeviceCore 或 ProtocolCore，避免基础抽象反向依赖 OSP。

## 生命周期

1. 设备工厂 Bundle 使用 run level `090`；协议工厂必须早于 ProtocolGateway 的 run level
   `110`。OSP 按字符串比较 run level，因此必须使用三位零填充格式。
2. Bundle 注册 `DeviceFactoryService` 或 `ProtocolFactoryService`，并同时设置
   `pdr.gateway.factory.kind` 与 `pdr.gateway.factory.type`。
3. Gateway 按 Service 名称排序发现工厂，拒绝空描述、属性/类型不一致和重复类型。
4. Gateway 展开 indexed configuration，负责公共 `required`、重连、服务注册和关闭顺序。
5. 工厂只解析类型专属配置并返回对象；返回空指针会导致启动失败。
6. Provider 必须在所有已创建实例关闭后才能注销，正常关机依靠反向 run-level 顺序保证。

## 设备脚手架

```powershell
python tools/pdr.py new device TemperatureProbe --output devices
```

版本 5 会生成核心设备库、`FactoryBundleActivator.cpp` 和 run level `090` 的 `.bndlspec`。
部署该 `.bndl` 并配置：

```properties
pdr.temperatureprobe.count = 1
pdr.temperatureprobe.0.id = temperature-probe-1
pdr.temperatureprobe.0.enabled = true
pdr.temperatureprobe.0.required = true
```

新增设备类型不需要改动 `services/DeviceGateway`。协议提供者使用同一规则注册
`ProtocolFactoryService`，Gateway 继续统一管理 `required`、`autoReconnect` 和退避时间。

框架自带实现也遵守同一边界：`BuiltinDeviceFactories`（run level `090`）和
`BuiltinProtocolFactories`（run level `105`）分别拥有具体设备/协议构造代码；两个 Gateway
不再链接这些具体实现库。设备团队、协议团队和 Gateway/运行时团队因此可以在独立目录、
独立 Bundle 和独立构建 Target 上工作。
