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
