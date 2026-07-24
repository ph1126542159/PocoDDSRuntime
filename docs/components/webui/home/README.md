# WebUI 主页与管理组件

## 实现过程

`webui/home` 提供进程、服务、模块、Bundle、配置、日志和生命周期操作界面。React 页面调用运行时 REST API；静态资源打包为 `pdr-webui-home` OSP Bundle。

## 用法

启动 WebServer 相关 Bundle 和 `pdr-runtime` 后，从配置的 HTTP 地址进入主页。开发构建：

```powershell
Set-Location webui/home
npm install
npm run build
```

涉及启动、停止、安装或删除的管理操作应由后端做权限检查和目标校验。

## REST API 和打包

| API | 用途 |
| --- | --- |
| `GET /api/v1/topology` | 进程、模块、Bundle、服务拓扑 |
| `GET /api/v1/config?kind=...` | 分类配置 |
| `/api/v1/lifecycle` | 生命周期操作 |
| `GET /api/v1/logs?...` | 日志查询 |
| `GET /api/v1/heartbeat-businesses` | 当前业务执行列表，最多返回最近 1000 条 |
| `GET /api/v1/business-trace-history?...` | 按时间、名称和状态分页查询业务历史 |

请求使用 sessionStorage 中的 Bearer token。主页只是客户端；真实操作由 `platform/OSP/Web` 的 dispatcher 执行。

主页中的业务执行列表采用单行紧凑布局；业务历史记录查询面板可按起止时间、
业务名称和状态筛选，每页显示 100 条。历史数据由运行时的 Poco SQLite 小时分库
提供，默认保留 10 天。

- URL：`/home/`
- symbolic name：`pdr.webui.home`
- run level：`450-webui`

```powershell
Set-Location webui\home
npm install
npm run build
Set-Location ..\..
cmake --build build --config Release --target pdr_webui_home
```

页面未更新时检查新 `.bndl` 是否进入实际运行目录，并确认热更新日志和 Bundle active 状态。
