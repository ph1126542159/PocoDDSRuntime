# OSP 组件

## 职责

`platform/OSP` 提供 Bundle 安装、依赖解析、启动、停止、卸载和本地服务注册表。它负责同一进程内的模块化，不负责跨进程通信；跨进程由 Fast DDS 完成。

## 实现过程

核心库汇总 Bundle、BundleLoader、BundleRepository、ServiceRegistry 和 OSPSubsystem。`Core`、`Web`、`WebServer`、`BundleAdmin` 等子目录构建标准 OSP Bundle 或工具；`BundleCreator` 把 `.bndlspec` 和资源打包为 `.bndl`。

## 用法

业务 Bundle 提供 `BundleActivator`，在 `start()` 中注册服务并在 `stop()` 中注销服务。通过 `.bndlspec` 声明名称、版本、依赖和打包内容，构建后将 `.bndl` 放入运行进程的 `bundles/`。

不要绕过 OSP 直接加载动态库；否则依赖解析、停止和卸载阶段不会完整执行。

## Bundle 结构和配置

`.bndl` 包含 manifest（symbolicName、version、activator、runLevel、依赖）、按系统架构打包的 DLL/SO、资源文件和可选 `extensions.xml`。Activator 的 `start()` 注册服务和监听器，`stop()` 必须逐项撤销。

```properties
osp.bundleRepository = ${application.dir}bundles/
osp.codeCache = ${application.dir}codeCache
osp.data = ${application.dir}data
osp.web.server.host = 127.0.0.1
osp.web.server.port = 9080
osp.web.server.securePort = 0
osp.web.rootRedirect = /login/
osp.web.authServiceName =
auth.simple.enable = false
```

WebServer 还支持 `maxQueued`、`maxThreads`、`keepAlive`、`keepAliveTime` 和 `maxKeepAlive`。

## 新 Bundle 实现步骤

1. 实现 `Poco::OSP::BundleActivator`。
2. 在 `.bndlspec` 填写唯一 symbolicName、版本、activator、runLevel 和 requiredBundles。
   BundleCreator 会把 `<requiredBundles><bundle>...</bundle></requiredBundles>` 写入
   `Require-Bundle` Manifest 字段，同时继续接受旧版 `manifest.dependency` 布局。发布前应解包
   `.bndl` 核对 Manifest；`generated-plugin-consumer` 会以正常和缺失依赖两个插件验证该字段、
   Runtime 依赖清单以及不兼容启动的 HTTP 409 门禁。
3. 用 `myiot_add_osp_bundle()` 增加 CMake 目标。
4. 构建并检查 `.bndl` 内容。
5. 放入 `bundles/`，确认依赖解析和 active 状态。

runLevel 决定启动顺序，停止顺序相反；依赖版本不满足时不能强制跳过解析。

## Web 安全与性能配置

以下键由 `platform/OSP/Web` 和 `WebServer` 实际读取，但默认模板只显式设置其中一部分：

| 配置项 | 代码默认值 | 说明 |
| --- | --- | --- |
| `osp.web.server.maxQueued` | `100` | 等待处理的最大连接数 |
| `osp.web.server.maxThreads` | `8` | HTTP 工作线程数 |
| `osp.web.server.keepAlive` | `true` | HTTP Keep-Alive |
| `osp.web.server.keepAliveTime` | `10` | Keep-Alive 超时 |
| `osp.web.server.maxKeepAlive` | `10` | 每连接最大请求数 |
| `osp.web.cacheResources` | `false` | 是否缓存 Bundle 静态资源 |
| `osp.web.compressResponses` | `false` | 是否压缩响应 |
| `osp.web.compressedMediaTypes` | 空 | 可压缩 MIME，逗号分隔 |
| `osp.web.authServiceName` | 空 | OSP AuthService 名称 |
| `osp.web.tokenValidatorName` | 空 | TokenValidator 服务名称 |
| `osp.web.authMethods` | 空 | 允许的认证方法 |
| `osp.web.addAuthHeader` | `true` | 添加认证相关响应头 |
| `osp.web.addSignature` | `true` | 添加服务器签名 |
| `osp.web.logFullRequest` | `false` | 是否记录完整请求；生产慎用 |
| `osp.web.cors.enable` | `true` | CORS 处理开关 |
| `osp.web.cors.allowedOrigin` | 空 | 允许的 Origin |
| `osp.web.csrfProtectionEnabled` | `true` | CSRF 防护 |
| `osp.web.contentTypeOptions` | `nosniff` | X-Content-Type-Options |
| `osp.web.frameOptions` | 空 | X-Frame-Options |
| `osp.web.hsts.enable` | `false` | HSTS；仅 HTTPS 部署启用 |
| `osp.web.hsts.maxAge` | `21772800` | HSTS max-age |
| `osp.web.hsts.includeSubdomains` | `true` | HSTS includeSubDomains |
| `osp.web.xssProtection.enable` | `false` | 旧式 X-XSS-Protection |
| `osp.web.xssProtection.mode` | `block` | XSS header mode |

会话配置：

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `osp.web.sessionManager.cookiePersistence` | `persistent` | `persistent` 或 `transient` |
| `osp.web.sessionManager.cookieSecure` | `false` | HTTPS 部署应设为 true |
| `osp.web.sessionManager.cookieSameSite` | 空 | `none`、`lax`、`strict` |
| `osp.web.sessionManager.csrfCookie` | `XSRF-TOKEN` | CSRF Cookie 名 |
| `osp.web.sessionManager.verifyAddress` | `true` | 校验会话来源地址 |
| `osp.web.sessionManager.defaultDomain` | 空 | Cookie 默认域 |
| `osp.web.sessionManager.sessionStore` | 空 | 会话存储服务 |

## SimpleAuth

```properties
auth.simple.enable = true
osp.web.authServiceName = osp.auth
auth.simple.salt = <随机盐>
auth.simple.admin.name = admin
auth.simple.admin.passwordHash = <MD5(salt + password) 的十六进制>
auth.simple.user.name = operator
auth.simple.user.passwordHash = <MD5(salt + password) 的十六进制>
auth.simple.user.permissions = view,status
```

当前实现按 `MD5(salt + password)` 验证。这属于兼容性实现，不适合直接暴露到不可信网络；外网部署应接入更强的认证服务、TLS 和限流。

Runtime 自带的共享管理身份 Bridge 是推荐入口：

```properties
pdr.management.authentication.required = true
pdr.management.authentication.principals.count = 1
pdr.management.authentication.principals.0.id = operator
pdr.management.authentication.principals.0.tokenEnvironment = PDR_OPERATOR_TOKEN
pdr.management.authentication.principals.0.permissions = protocol.manage,task.read
osp.web.authServiceName = pdr.auth.management
osp.web.tokenValidatorName = pdr.auth.management.tokens
```

同一环境 Token 此时同时可用于管理 API Bearer 和 OSP WebEvent Bearer；Basic 兼容客户端使用
Principal ID 作为用户名、同一 Token 作为密码。Bridge 不保存明文配置，也不向日志暴露 Token。

## 代理与 WebEvent

```properties
http.proxy.host =
http.proxy.port = 80
http.proxy.username =
http.proxy.password =
http.proxy.nonProxyHosts =

osp.web.event.workers = 4
osp.web.event.maxWebSockets = 0
```

`maxWebSockets=0` 表示使用实现默认/不设显式上限，生产环境应结合资源限制评估。

`/webevent` 会暴露实时 Runtime 事件，因此 Bundle 扩展固定声明 `permission=*`，由 OSP Web
dispatcher 在创建 WebSocket handler 前完成认证。默认开发配置没有认证服务，所以该入口返回
401；需要使用时必须先配置 `osp.web.authServiceName` 和对应 AuthService。SimpleAuth 只适合
本机兼容测试，生产环境应使用强认证服务并通过 HTTPS/WSS 连接。客户端的 Basic、Bearer 或
session 身份通过 dispatcher 后才能进入 WebSocket 握手，handler 本身不再维护第二套认证逻辑。

仓库的 `runtime-webevent-auth-integration` 会生成临时凭据并从环境变量注入，分别证明未认证、
错误 Basic 凭据和错误 Bearer 请求返回 401，正确 Basic 与共享管理 Bearer 请求进入握手校验，并检查所有
凭据不进入 JSON 报告、标准输出或 Runtime 日志。

## 其他 OSP 运行项

| 配置项 | 说明 |
| --- | --- |
| `osp.language` | OSP 资源/本地化语言 |
| `osp.sharedCodeCache` | 共享代码缓存位置 |
| `osp.autoUpdateCodeCache` | Bundle 变化时是否更新代码缓存 |
| `osp.web.server.secureHost` | HTTPS Server 绑定地址 |
| `osp.js.moduleSearchPaths` | JavaScript OSP 模块搜索路径 |
| `osp.js.v8.flags` | V8 启动 flags |

当前根 CMake 没有加入 `platform/OSP/JS`，所以两个 `osp.js.*` 键仅在后续启用 JS Bundle 时生效；不要在当前部署中把它们当作已启用功能。
