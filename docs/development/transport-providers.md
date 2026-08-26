# 动态 Transport Provider

Transport Provider 把消息传输实现从 Runtime Core 和业务 Bundle 中剥离。业务侧只通过
`pdr.service.transportRegistry` 查询能力并创建传输实例；MQTT、Fast DDS 以及后续新增的
传输由各自 Bundle 注册 `TransportFactoryService`。

## 组件边界

| 组件 | 职责 | 禁止承担 |
|---|---|---|
| `RuntimeCore` | `IMessageTransport`、描述符、线程安全工厂目录 | OSP Bundle 生命周期、具体协议配置 |
| `TransportProviderAPI` | OSP 工厂服务和 Registry 服务契约 | MQTT/Fast DDS 依赖 |
| `TransportProviderCore` | 将 Provider 服务安全适配到 Runtime Core | 具体 Provider 实现 |
| `pdr.service.transportRegistry` | 动态发现、校验、注册和卸载 Provider | 协议实现 |
| `pdr.transport.factories.builtin` | 发布 MQTT/Fast DDS 工厂服务 | 业务编排和设备管理 |

因此不同团队可以分别维护 Runtime Core、Provider、业务 Bundle；Provider 的新增不要求修改
Registry Runtime，也不要求业务模块链接具体传输库。

## Provider 注册

Provider Bundle 实现 `TransportFactoryService`，并使用以下服务属性注册：

- `pdr.transport.factory.kind=message`
- `pdr.transport.factory.type=<descriptor.id>`

`descriptor.id` 只能包含小写字母、数字、`-` 和 `.`。同一 ID 的重复 Provider 会被拒绝并记录
错误，不会覆盖已运行实现。Provider 卸载时 RAII 注册令牌立即禁止新实例创建；已创建实例必须
在卸载 Provider Bundle 前由其所有者停止并释放，这是跨 DLL 虚函数对象的生命周期约束。

```cpp
auto registry = Poco::OSP::ServiceFinder::find<
    PocoDDS::TransportProviders::TransportRegistryService>(context);
auto created = registry->create("mqtt", {
    {"serverUri", "ssl://broker.example:8883"},
    {"clientId", "edge-a"}
});
```

工厂异常由 Registry 转换为 `internalError`，不会穿透到调用方；Provider 返回的可重试错误则保留
原始错误码和 `retryable` 标志。注册、创建、枚举和卸载均可并发调用。

## 生命周期与协作规则

1. Provider 只解析自身配置并创建传输，不访问业务 Bundle 内部对象。
2. 业务 Bundle 保存传输实例，并在自身 `stop()` 中先停止/释放实例。
3. 部署升级时先停止消费者，再停止 Provider；启动顺序相反。
4. 新 Provider 使用独立目录、CMake 目标、Bundle symbolic name 和测试，避免修改公共 Registry。
5. 密码和私钥不写入描述符或日志；使用现有安全配置/环境变量注入路径。

当前内置目录发布 `inproc`、`mqtt` 和 `fastdds`。这只是默认实现集合，不是核心层硬编码白名单。
