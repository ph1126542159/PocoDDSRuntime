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
