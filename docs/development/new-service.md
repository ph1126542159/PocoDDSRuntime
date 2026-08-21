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

独立验证：

```powershell
./tools/pdr.ps1 verify services/TemperatureService `
  --prefix build/install --config Release `
  --report build/reports/temperature-service-verify.json
```
