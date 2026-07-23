# WebUI 登录组件

## 实现过程

`webui/login` 使用 React/Vite 实现登录界面，`manifest.json` 描述页面资源，`extensions.xml` 将页面注册到 OSP Web 扩展点，最终打包为 `pdr-webui-login` Bundle。

## 用法

```powershell
Set-Location webui/login
npm install
npm run build
```

再从项目根目录执行 CMake 构建。认证结果必须由服务端校验，前端页面不能作为安全边界。

## 页面行为和配置

登录页校验本地默认账号密码，成功后将用户名写入
`sessionStorage["pdr.webui.user"]` 并进入 `/home/`。

- 默认用户名：`admin`
- 默认密码：`admin`
- 使用范围：仅用于监听在 `127.0.0.1` 的本地管理页面

- URL：`/login/`
- symbolic name：`pdr.webui.login`
- run level：`400-webui-entry`
- OSP extension：`osp.web.server.directory`

本地默认 `osp.web.authServiceName` 为空，处于无服务端认证模式。生产环境必须启用
服务端认证并更换默认凭据；前端页面不能充当安全边界。

验证时访问 `http://127.0.0.1:9080/login/`，分别测试空密码、错误密码和
`admin`/`admin`。
