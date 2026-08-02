# WebUI 组件总览

`webui` 中每个页面都是独立 Vite/React 前端，并通过 `.bndlspec` 打包成 OSP Web Bundle。CMake 宏 `pdr_add_webui_bundle` 负责构建前端资源并生成 `.bndl`。

当前正式页面包括登录、运行时管理主页和业务追踪。`bundle/webui` 中是已生成/嵌入资源，源文件位于各组件的 `src/`、`static/` 和 `index.html`。

开发时修改源文件后执行对应 npm build，再执行 CMake 构建打包；不要只修改生成后的 `bundle/webui/assets`。

Home 的 JS/CSS 文件名包含内容哈希，`index.html` 由 Vite 自动引用当前版本，避免 Runtime Bundle 更新后浏览器继续使用旧诊断页面。CMake 以 `index.html` 作为前端构建产物，不依赖固定的 `app.js` 或 `app.css`。

## 构建链和服务器配置

```text
src/main.jsx + styles.css + static/manifest.json
→ Vite build
→ bundle/webui/index.html + assets/*
→ extensions.xml 注册 osp.web.server.directory
→ OSPBundleCreator
→ pdr.webui.*.bndl
```

三个 WebUI Bundle 均依赖 `osp.web [1.1.0,2.0.0)`，只包含静态资源。

```properties
osp.web.server.host = 127.0.0.1
osp.web.server.port = 9080
osp.web.server.securePort = 0
osp.web.rootRedirect = /login/
osp.web.authServiceName =
auth.simple.enable = false
```

`127.0.0.1` 只允许本机访问。对外开放时还必须配置认证、TLS、防火墙或反向代理。

各子目录运行 `npm install`、`npm run build`。正式项目通过 `pdr_add_webui_bundle()` 打包；不要直接维护 `bundle/webui/assets` 中带 hash 的生成文件。

## 使用流程

1. 启动 `pdr-runtime` 并确认 `osp.web`、WebServer、login、home Bundle 为 active。
2. 浏览器打开 `http://127.0.0.1:9080/login/`。
3. 登录页验证 API 后进入 `/home/`。
4. 启用 Observability 时可进入 `/tracing/`。

前端没有独立 `.env` 配置，API 使用同源相对路径。前后端分离开发时需要在 Vite 配置中增加受控代理；当前生产 Bundle 假设由 OSP Web Server 同源托管。
