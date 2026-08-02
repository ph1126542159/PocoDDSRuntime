# WebUI 主页与管理组件

## 实现过程

`webui/home` 提供进程、服务、模块、Bundle、受控配置、日志和生命周期操作界面。React 页面调用运行时 REST API；静态资源打包为 `pdr-webui-home` OSP Bundle。服务和模块清单是只读视图；页面把基础 `/api/v1/topology` 清单与 `/api/v1/process-detail` 返回的权威 `manageable` 标记合并，只有后端 allowlist 放行的 Bundle 才显示启动或重启操作，不会为不存在的后端能力显示配置或卸载按钮。

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
| `POST /api/v1/process-config` | 事务式修改后端白名单中的 Runtime 配置项 |
| `POST /api/v1/process-lifecycle` | 本机子进程生命周期操作 |
| `POST /api/v1/bundle-lifecycle` | 可管理 Bundle 的启动、停止或重启 |
| `GET /api/v1/logs?...` | 日志查询 |
| `GET /api/v1/diagnostic-events` | 最近结构化故障检测与恢复事件 |
| `GET /api/v1/alerts` | 告警状态及生效的去抖、升级和静默策略 |
| `GET /api/v1/alert-history?limit=20` | 最近持久化告警转换，当前进程无告警时用于跨重启展示 |
| `GET /api/v1/alert-sinks` | 已注册告警 Sink 的名称、类型和静默接收策略，不返回密钥 |
| `GET /api/v1/identity` | 当前身份快照代次、身份数量和认证状态，不返回 ID、路径或令牌 |
| `POST /api/v1/identity` | 经 `identity.manage` 授权和二次确认后原子重载文件型令牌 |
| `GET /api/v1/heartbeat-businesses` | 当前业务执行列表，最多返回最近 1000 条 |
| `GET /api/v1/business-trace-history?...` | 按时间、名称和状态分页查询业务历史 |

请求使用 sessionStorage 中的 Bearer token。主页只是客户端；真实操作由 `platform/OSP/Web` 的 dispatcher 执行。
同一 Bearer token 也会随配置、协议、进程和 Bundle 写请求发送。配置卡明确显示后端当前是
“管理写操作已认证”还是“开发模式未认证”；该提示来自后端生效状态，不根据浏览器是否
保存 token 推测。生产部署看到未认证提示时不得继续验收。
主页为每个管理写请求自动生成 `X-PDR-Request-Id`；浏览器或代理重试同一请求时，后端
返回缓存结果而不会再次执行。直接调用 API 的客户端也必须自行保存该 ID，直到操作得到
确定结果；生产 Runtime 会拒绝缺少请求 ID 的写请求。
配置卡读取后端 `managementSession`，显示当前 Principal，并按其权限禁用 Bundle 与配置
操作按钮。权限判断以服务端为准：未认证返回 401，已认证但缺少对应 `*.manage` 权限返回
403；页面禁用只是易用性提示，不是安全边界。
具有 `audit.read` 权限时，配置卡还会请求 `GET /api/v1/management-audit?limit=20`，展示
最近管理操作的身份、类型、目标、结果、HTTP 状态和耗时；没有查询权限时不发起请求。
具有 `task.read` 权限时，同一区域显示最近异步管理任务及其状态；同时具有
`task.cancel` 时可立即取消 `queued` 任务，也可向 `running` 任务发出协作停止请求。
具有 `identity.manage` 权限时，配置卡显示当前身份快照代次和重载按钮。页面要求先原子
替换 Secret 文件；成功后立即清除 sessionStorage 中的旧令牌，下一次管理请求必须输入
新令牌。页面不读取、展示或回显 Secret 文件路径及令牌值。
任务区同时显示快照持久化健康状态、worker 使用、排队数、资源等待数和调度降级状态；
等待资源的任务会标出资源键及占用任务 ID。`interrupted` 任务会明确提示先核对目标真实
状态再重新提交，不提供一键自动重放。
当任务快照或幂等账本要求恢复时，页面显示离线 `pdr persistence inspect/recover` 指引；
出于重复执行风险，页面不提供自动或一键回退按钮。

配置编辑不是仅修改浏览器状态：后端先把新值放入当前完整配置副本并执行
`ConfigurationValidator`，通过后写入同目录 `.new` 文件、重新读取确认，再保留
`pdr-runtime.properties.rollback` 并替换正式配置。随后才更新 Preferences、日志级别
或重启所属 Bundle。任一应用步骤失败会恢复正式文件、运行态值和原 Bundle active
状态，并返回 HTTP 409 及 `rolledBack=true`；预校验失败返回 HTTP 400，且不会写盘。
Web 成功提示会明确显示“已校验、持久化并应用”或“已校验、持久化并重启所属 Bundle”。
主进程配置卡还会读取 `GET /api/v1/process-config`，显示最近五条 committed、rejected
或 rolled-back 事务。只有后端同时存在匹配的回退元数据与快照时才显示“回退”按钮；
点击时必须提交页面刚读取到的 `transactionId`，服务端会拒绝过期事务或外部改写后的
配置，防止旧页面覆盖新配置。审计记录不保存配置值和敏感信息。

主页中的业务执行列表采用单行紧凑布局；业务历史记录查询面板可按起止时间、
业务名称和状态筛选，每页显示 100 条。历史数据由运行时的 Poco SQLite 小时分库
提供，默认保留 10 天。

运行总览的告警区同时展示已注册 AlertSink、逐 Sink 健康状态和成功/失败次数，以及 `pdr.alert.delivery` 的全局成功、失败、丢弃计数；连续失败的 Sink 标为 degraded，悬停可查看最近错误。
Sink API 或指标暂时不可用时该区域降级为空清单和零计数，不阻断首页其余运行状态刷新。

概览健康卡右侧展示最近 4 条告警，包括状态、级别、实例、稳定错误码、静默标志和观察次数，并显示当前去抖与升级阈值；完整事件及其 Trace 仍以运行时 API 为准。

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
