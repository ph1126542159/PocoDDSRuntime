# Runtime Service Directory 与健康感知路由

Service Directory 为多个 `pdr-runtime` 实例提供显式服务实例发现和无副作用路由选择。它解决“哪个 Runtime 当前提供哪个远程端点”的问题；OSP Service Registry 仍只负责单进程内的 C++ Service 生命周期。

## 边界

- 只有配置项或注册为 `ServiceAdvertisementProvider` 的端点会被发布。普通 OSP Service 不会被自动暴露为远程服务。
- Directory 只保存服务名、实例 ID、端点、协议、区域、标签和 Runtime 代际，不保存凭据。
- Router 只选择端点，不代理请求、不建立连接、不重试业务调用，也不把标签当作授权声明。
- Membership 提供 Runtime 在线资格与精确 incarnation；本组件不提供选主、法定人数、共识或全局强一致。
- `SystemMonitoring` 不参与目录状态机、发布或路由。

## 分层与协作接口

`PocoDDS::ServiceDirectoryCore` 包含传输无关的 `Directory` 和 `Router`；`PocoDDS::ServiceDirectoryAPI` 额外导出 OSP Provider 与 Runtime Service 接口；`ServiceDirectoryRuntime` Bundle 负责 Fast DDS 传播、Membership 过滤、健康贡献和只读 HTTP API。业务团队只依赖公开 API，不包含 Bundle 私有头文件。

Provider 注册属性：

```text
pdr.serviceAdvertisement.provider.kind = directory
pdr.serviceAdvertisement.provider.id = <stable-provider-id>
```

Provider 返回的同一批描述符采用 fail-closed 语义：Provider ID 漂移、实例键重复或与其他 Provider 冲突时，该 Provider 本轮不会部分发布。Provider 卸载会发布带更高 revision 的 withdraw。

## 配置广告

```properties
pdr.serviceDirectory.advertisements.count = 1
pdr.serviceDirectory.advertisements.0.serviceName = pdr.health.v1
pdr.serviceDirectory.advertisements.0.instanceId = edge-a:health
pdr.serviceDirectory.advertisements.0.endpoint = http://edge-a:9080/health
pdr.serviceDirectory.advertisements.0.protocol = http
pdr.serviceDirectory.advertisements.0.zone = plant-a
pdr.serviceDirectory.advertisements.0.tags = health,http
pdr.serviceDirectory.advertisements.0.state = ready
```

实例 ID 在一个服务名内必须稳定且唯一。`ready` 可参与路由；`draining` 保留在可观察目录中但不会接收新选择。TTL 必须至少为发布周期的两倍，过期时间由接收端单调时钟决定。

## 路由策略

- `round-robin`：在满足标签且对应 Runtime incarnation 在线的实例间轮转。
- `rendezvous-hash`：要求 `routingKey`，为相同候选集合提供稳定亲和选择。
- `prefer-local`：优先匹配 `localRuntimeId`，否则回退到可用远端实例。

所有策略都会排除 draining、expired、标签不匹配以及 Membership 中不存在精确 Runtime ID/incarnation 的实例。路由结果区分无实例、无 ready、标签不匹配、无合格成员和缺少 routing key，便于调用方决定降级方式。

## 运维接口与限制

- `GET /api/v1/service-directory?serviceName=...`：目录快照。
- `GET /api/v1/service-directory/route?...`：无副作用选择。
- 健康贡献者：`service-directory`。

需要在选路之上执行有 deadline、幂等重试、故障切换和实例熔断的业务调用时，使用 [Service Client 韧性 SDK](runtime-service-client.md)，不要在各业务 Bundle 内复制重试状态机。

接口需要 `resource.read`；开发配置未要求管理认证时使用本地匿名兼容主体。生产环境必须启用管理身份。当前线协议是进程内实现细节，不承诺跨版本直接兼容；跨版本部署应先通过服务契约和 SDK 兼容门禁。负载、延迟和错误率尚未进入选择模型，业务调用失败重试也由客户端或专门网关负责。
