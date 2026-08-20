# WebUI 业务追踪组件

## 实现过程

`webui/tracing` 从追踪 HTTP 接口读取业务及步骤快照，把一条 trace 渲染为可点击流程图，并显示耗时、状态和经过清洗的输入输出字段。机器人开发分支还会从本机 9096 控制服务读取真实 C++ SIL 任务，使运行时 Trace 与机器人仿真 Trace 进入同一个列表并复用同一套流程图、节点详情和日志交互。

## 用法

先以 `PDR_ENABLE_OBSERVABILITY=ON` 构建并启用追踪服务，再构建 `webui/tracing`：

```powershell
Set-Location webui/tracing
npm install
npm run build
```

启动运行时后进入“业务追踪”页面。需要机器人仿真时，同时运行 `python robotics/tools/robotics_web_server.py --port 9096`。若没有运行时数据，先确认业务代码调用了追踪 API、DDS Topic `pdr.observability.span` 可达且追踪 HTTP 服务已启动；若仿真面板显示未连接，则检查 9096 服务及允许的 WebUI origin。

## 数据接口和配置

页面轮询 `GET /api/v1/business-traces` 和 `GET /api/v1/business-traces/{traceId}` 获取原运行时摘要与节点，并携带 sessionStorage Bearer token。机器人记录来自本机 `/api/v1/robotics-simulation/runs`，前端只合并展示，不改变原运行时 API 契约；启动、取消和节点详情仍由 9096 控制服务负责。

- URL：`/tracing/`
- symbolic name：`pdr.webui.tracing`
- run level：`460-webui`
- 构建开关：`PDR_ENABLE_OBSERVABILITY=ON`
- 导出配置：`observability.otlpHttpEndpoint`

OTLP endpoint 为空不会关闭本地页面。无数据时依次检查业务代码创建 span、TraceStore 收到快照、REST API 返回以及浏览器请求。敏感字段必须在后端清洗。
