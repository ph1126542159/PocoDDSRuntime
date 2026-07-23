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
