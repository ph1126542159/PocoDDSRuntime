# 新增服务

先生成与传输无关的服务核心：

```powershell
./tools/pdr.ps1 new service TemperatureService --output services
```

1. 公共接口放入 `include/`，实现放入 `src/`，测试放入 `tests/`。
2. 依赖从构造函数或 Port 注入；服务接口不包含 Qt、Fast DDS、OSP 或具体设备类型。
3. 需要 Runtime 动态发现时，再建立独立 Bundle 适配器；Bundle Activator 只创建、注册和释放服务。
4. 超时、取消、重试和补偿由 Application/Policy 表达，不在 Activator 或协议回调里编排。
5. 注册健康贡献者，使用稳定错误码，并登记 REST/DDS 契约。
6. `services/` 会自动发现新的直接子目录，不需要修改 `services/CMakeLists.txt`。
7. 对外提供或消费 Runtime Service 时，在 Bundle 的 `bundle/service-contracts.json` 声明
   Provider/Requirement，并在 bndlspec 中包含 `<files>bundle/*</files>`；不要修改中央服务表。

Service Contract 的 Owner 由 Bundle 自动推导。Provider 必须使用相同 `serviceName` 注册
Service，并设置正确的 `pdr.bundle` 属性。格式、版本范围和 Readiness 规则见
[Service 依赖契约](../architecture/service-dependency-contracts.md)。
声明为必需的 Requirement 会参与 Bundle 启动准入；停止 Provider 也会在 BundleLoader 执行点
检查当前 Active Consumer。开发者不得通过其他入口直接绕过生命周期守卫。

如果服务会成为其他 Bundle 的 Active Consumer，并且需要支持 Provider 在线维护，还必须接入
`PocoDDS::LifecycleCore`：每个业务请求和调度任务持有 `DrainGate::Lease`，并以本 Bundle Owner
注册 `DrainParticipantService`。卸载顺序必须是“注销参与者 -> 取消并等待调度 ->
`closeAndWait()` -> 注销业务 Service”。详细规则见
[Bundle 事务式排空与恢复](../architecture/lifecycle-maintenance.md)。

独立验证：

```powershell
./tools/pdr.ps1 verify services/TemperatureService `
  --prefix build/install --config Release `
  --report build/reports/temperature-service-verify.json
```
