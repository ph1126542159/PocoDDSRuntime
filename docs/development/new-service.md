# 新增服务

1. 在 `services/<Name>` 建立库、Bundle、测试和 README。
2. 公共接口放入 `include/`，实现放入 `src/`。
3. 业务入口调用 Application 用例，不在 Bundle Activator 中编排业务。
4. 注册健康贡献者，记录结构化错误码。
5. 新增 CTest，并登记 REST/DDS 契约。
