# WebUI 业务追踪组件

## 实现过程

`webui/tracing` 从追踪 HTTP 接口读取业务及步骤快照，把一条 trace 渲染为可点击流程图，并显示耗时、状态和经过清洗的输入输出字段。

## 用法

先以 `PDR_ENABLE_OBSERVABILITY=ON` 构建并启用追踪服务，再构建 `webui/tracing`：

```powershell
Set-Location webui/tracing
npm install
npm run build
```

启动运行时后进入“业务追踪”页面。若没有数据，先确认业务代码调用了追踪 API、DDS Topic `pdr.observability.span` 可达且追踪 HTTP 服务已启动。

## 数据接口和配置

页面每 2 秒请求 `GET /api/v1/business-traces` 和 `GET /api/v1/business-traces/{traceId}`，分别获取摘要列表和节点数组，并携带 sessionStorage Bearer token。

- URL：`/tracing/`
- symbolic name：`pdr.webui.tracing`
- run level：`460-webui`
- 构建开关：`PDR_ENABLE_OBSERVABILITY=ON`
- 导出配置：`observability.otlpHttpEndpoint`

OTLP endpoint 为空不会关闭本地页面。无数据时依次检查业务代码创建 span、TraceStore 收到快照、REST API 返回以及浏览器请求。敏感字段必须在后端清洗。
