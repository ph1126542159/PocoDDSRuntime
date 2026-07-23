# OSP 服务组件总览

每个 `services/*` 目录构建独立 OSP Bundle。标准实现顺序是：Bundle Activator 创建服务实现、注册到本地 OSP Registry、创建 Fast DDS `ServiceEndpoint`、处理请求并发布响应/事件；停止时先停止端点，再注销服务。

| 服务 | Request | Response | Event |
| --- | --- | --- | --- |
| UnitsOfMeasure | `pdr.units.request` | `pdr.units.response` | — |
| NetworkEnvironment | `pdr.network.request` | `pdr.network.response` | `pdr.network.environment` |
| DeviceStatus | `pdr.status.request` | `pdr.status.response` | `pdr.device.status` |
| WebEvent | `pdr.web.request` | `pdr.web.response` | `pdr.web.event` |
| MobileConnection | `pdr.mobile.request` | `pdr.mobile.response` | `pdr.mobile.state` |

DeviceGateway 使用独立的 `pdr.device.*` Topic。

## Bundle 实现模板

```text
BundleActivator::start
├─ 创建 ServiceImpl
├─ registerService("pdr.service.*")
├─ 读取 pdr.fastdds.domainId
├─ 创建 ServiceEndpoint
└─ 订阅本地事件并 publishEvent

BundleActivator::stop
├─ 取消本地事件订阅
├─ stop ServiceEndpoint
└─ unregisterService
```

所有服务通过 `myiot_add_osp_bundle()` 构建，`.bndlspec` 声明 symbolic name、版本、activator 和 run level。服务顺序为 Units 200、Network 210、DeviceStatus 220、WebEvent 230、Mobile 240；DeviceGateway 为 100。

公共配置是 `pdr.fastdds.domainId`。业务专用配置目前包括 `deviceStatus.messages.maxAge`、`mobile.backend` 和 `mobile.legato.cmPath`。

跨进程客户端必须根据 response status 和 correlation ID 判断结果；event 只表示异步变化，不替代响应。
