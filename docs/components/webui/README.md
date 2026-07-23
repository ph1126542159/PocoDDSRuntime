# WebUI 组件总览

`webui` 中每个页面都是独立 Vite/React 前端，并通过 `.bndlspec` 打包成 OSP Web Bundle。CMake 宏 `pdr_add_webui_bundle` 负责构建前端资源并生成 `.bndl`。

当前正式页面包括登录、运行时管理主页和业务追踪。`bundle/webui` 中是已生成/嵌入资源，源文件位于各组件的 `src/`、`static/` 和 `index.html`。

开发时修改源文件后执行对应 npm build，再执行 CMake 构建打包；不要只修改生成后的 `bundle/webui/assets`。
