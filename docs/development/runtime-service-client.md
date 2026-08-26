# 跨 Runtime Service Client 韧性 SDK

`PocoDDS::ServiceClientCore` 把 Service Directory 的“选择一个端点”扩展为一次有界、可审计的调用尝试。`PocoDDS::ServiceClientAPI` 和独立 `ServiceClientRuntime` Bundle 再提供动态协议 Provider、异步提交、ResourceGovernor 隔离和安全卸载。实际 HTTP、DDS、MQTT 或业务协议调用仍由协议 Bundle 注入。

## 职责边界

- Service Directory：发现并选择 `ready`、Membership 合格的显式端点。
- Service Client：编排选择、调用尝试、退避、重试安全和实例熔断。
- CapabilityRuntime：在进入资源队列前按调用主体、service 和 operation 作准入决策与审计。
- 调用 Provider：建立协议连接、认证、序列化、发送、接收并把结果分类。
- ResourceGovernor：控制本地线程、并发、队列和执行隔离；Service Client 不创建工作线程或队列。
- Lifecycle/Outbox：分别处理 Bundle 排空和需要持久化的异步投递；Service Client 不提供 durable delivery。

该组件不代理流量、不保存凭据、不自动认定业务操作幂等，也不把晚到响应当作成功。

## 最小用法

```cpp
using namespace PocoDDS::ServiceClient;

Policy policy;
policy.maximumAttempts = 3;
policy.timeout = std::chrono::seconds(2);

Client client(policy, [directoryService](const auto& route) {
    return directoryService->route(route);
});

InvocationRequest request;
request.route.serviceName = "orders.v1";
request.route.requiredTags = {"json"};
request.operation = "get-order";
request.idempotent = true;

auto result = client.invoke(request, [](const AttemptContext& attempt) {
    // 协议 Provider 必须把 attempt.remaining 传递到连接/请求超时。
    return invokeHttp(attempt.instance.advertisement.endpoint,
                      attempt.remaining);
});
```

调用回调返回：

- `AttemptResult::success(payload)`：成功并关闭该实例熔断。
- `AttemptResult::retryable(code, detail)`：端点暂时不可用，可在安全条件下退避并换实例。
- `AttemptResult::permanent(code, detail, endpointHealthy)`：本次不重试；例如 HTTP 4xx 通常说明端点可达，可把 `endpointHealthy` 保持为 `true`。

回调抛出的异常会转换为 retryable `invoker-exception`，不会穿透 Client 边界。

## Runtime Provider 插件

协议 Bundle 实现 `ServiceInvocationProvider`，并用以下 OSP 属性注册：

```text
pdr.serviceInvocation.provider.kind = runtime
pdr.serviceInvocation.provider.id = <stable-provider-id>
pdr.serviceInvocation.provider.protocol = <directory-protocol>
```

属性必须与 `providerId()`、`protocol()` 返回值完全一致。同一 Runtime 内一个 protocol 只允许一个 Provider；重复 ID、协议冲突或身份漂移会拒绝注册。Provider 接收共享的不可变 payload/metadata、选中实例、当前 attempt、相对剩余预算 `attempt.remaining`、绝对墙钟截止时间 `deadlineUnixMicroseconds` 和取消回调。一次逻辑调用的绝对截止时间在全部重试中保持不变；Provider 本地设置连接/I/O timeout 时仍以 `attempt.remaining` 为权威，绝对值用于跨进程传播和远端拒绝过期请求。

`ProviderRegistry` 在 Provider 注销时先停止接收新调用，再等待在途调用归零；注销回调返回后不会再执行该 Provider 代码。Provider 不得在自身活动回调中注销自己，该行为会被拒绝以避免 Bundle 卸载死锁或执行已卸载代码。

业务 Bundle 通过 `ServiceClientRuntimeService::submit()` 异步提交：

```cpp
RuntimeInvocationRequest call;
call.workId = "order-query-42";
call.principal = "bundle.order-query";
call.invocation.route.serviceName = "orders.v1";
call.invocation.operation = "get-order";
call.invocation.idempotent = true;
call.input.payload = encodeRequest();

auto submission = runtime->submit(std::move(call));
if (!submission) handleAdmissionFailure(submission.admission);
auto completion = submission.completion.get();
```

`admission` 表示 ResourceGovernor 是否接收，`completion.governance` 表示排队/执行/取消结果，`completion.invocation` 才是远端调用结果。队列超时或治理熔断可能没有 invocation 结果，不能把“提交成功”等同于“业务调用成功”。Provider 异常还会使治理 WorkItem 失败，从而进入本地 owner lane 的故障统计；普通远端业务错误不会错误打开本地执行 lane。

当 `pdr.serviceClient.authorizationRequired=true` 时，调用方必须设置稳定的 `principal`。Runtime 在提交 ResourceGovernor 之前请求 CapabilityRuntime 的短期 decision lease，资源名为 `<serviceName>/<operation>`、动作是 `service/use`；默认拒绝、显式 deny 以及授权服务异常都 fail-closed，且不会占用远端调用队列。策略可用 `orders.v1/*` 授权整个服务，也可精确限制到 `orders.v1/get-order`。状态接口只公开允许、拒绝和授权异常计数，不公开策略内容或凭据。

每次新的实际执行会获得独立 `invocationId`；同一幂等请求的并发加入和完成结果重放返回原执行 ID，明确表示它们没有产生第二次远端执行。核心协调器通过 `InvocationAuditSink` 发布 `received → authorization → idempotency → admitted → attempt → completed` 结构化事件；这是回调契约，因此 Service Client API 不依赖日志、数据库或 Observability。Runtime Bundle 的默认适配器将事件写成 `runtime.service-invocation` Business Trace，`businessInstanceId` 等于 invocation ID。HTTP Provider 同时把该值放入 `X-PDR-Invocation-Id`，便于远端日志继续关联。事件只含主体、目标 service/operation、实例身份、稳定错误码和策略 generation，不包含 payload、metadata、endpoint、Authorization 或凭据文件路径。Audit sink 异常只增加 `auditErrors`，不能改变调用结果。

```properties
pdr.serviceClient.audit.enabled = true
pdr.serviceClient.audit.maximumActiveTraces = 4096
```

## 幂等 Journal 与崩溃边界

`idempotencyKey` 不再只是“允许重试”的标志。启用 Runtime Journal 后，框架按 `principal + service + operation + idempotencyKey` 的 SHA-256 scope 建账，并对业务 payload 与非追踪 metadata 计算请求指纹：

- 同一进程中的相同并发请求加入已有 future，Provider 只执行一次；
- 已完成记录直接重放完整 `InvocationCompletion`，不占用 ResourceGovernor；
- 同一 key 改变 payload 或业务 metadata 返回 `SERVICE_CLIENT_IDEMPOTENCY_CONFLICT`；
- SQLite 记录只保存 scope/request digest、invocation ID 和完成结果，不保存 Principal、原始 key、请求 payload、metadata、endpoint 或凭据；
- Runtime 在远端结果完成后、向调用方兑现 future 前以 WAL/FULL 提交完成记录；提交失败会保持 in-flight 状态，使后续重复请求 fail-closed；
- 重启后遗留的 in-flight 记录视为不确定结果。默认返回 `SERVICE_CLIENT_IDEMPOTENCY_INDETERMINATE`；只有业务方显式设置 `idempotent=true` 才释放旧 claim 并重新执行。

`traceparent` 和 `tracestate` 不参与请求指纹，因此同一业务请求可以在新的追踪上下文中安全重放。没有 `idempotencyKey` 的调用不进入 Journal。`InvocationJournal` 是 Service Client API 的 SPI；SQLite 实现位于 Runtime Bundle 私有适配层，其他宿主可替换为自己的数据库实现。

```properties
pdr.serviceClient.idempotency.enabled = true
pdr.serviceClient.idempotency.maximumEntries = 10000
pdr.serviceClient.idempotency.retentionMilliseconds = 86400000
# 省略 database 时使用 Bundle persistentDirectory
# pdr.serviceClient.idempotency.database = D:/PocoDDSRuntime/data/service-client-invocations.sqlite
```

容量满时只淘汰最早的已完成记录，绝不自动删除 in-flight claim；如果容量全部由 in-flight 占用，新请求 fail-closed。数据库应位于受 Runtime 服务账户保护的目录。`GET /api/v1/service-client` 输出 backend、durable/healthy、entries、in-flight、replay、join、conflict、recovery 与 error 计数。

## 重试安全

只有满足以下任一条件才允许自动重试：

1. 调用方显式设置 `idempotent=true`；
2. 提供非空 `idempotencyKey`；Runtime Journal 负责本地并发合并和完成结果重放，Provider 仍应把该 key 传给支持远端去重的系统。

否则即使 Provider 返回 retryable，Client 也只执行一次，并在结果中标记重试被抑制。框架不能替业务方猜测“创建、扣款、控制动作”是否安全重放。

deadline 覆盖选路、调用和退避的完整时间预算。Provider 应主动遵守 `AttemptContext::remaining`，并在联网或产生外部副作用前拒绝已取消或已过期请求；如果 Provider 阻塞超过预算，Client 无法强制终止外部代码，但会丢弃晚到成功并返回 `deadline-exceeded`。需要强制隔离时应把 Provider 放入 ResourceGovernor lane 或独立子进程。

## 实例熔断与故障切换

熔断键绑定：

```text
serviceName + instanceId + runtimeId + runtimeIncarnation
```

因此 Runtime 重启后的新 incarnation 不继承旧进程的故障状态。达到阈值后实例进入 open；reset timeout 后只允许一个 half-open 探测；成功关闭，失败重新打开。同一次调用优先排除已失败实例并选择其他 ready 实例，只有没有替代实例时才允许在仍关闭的实例上再次尝试。

熔断表有固定容量和空闲保留期。容量已满且只有 open 状态不可淘汰时，新实例调用 fail-closed 为 `circuit-capacity-exceeded`，避免不受信任的实例 ID 造成无界内存增长。`snapshot()` 输出调用、尝试、重试、deadline、路由失败和熔断状态，可由拥有该 Client 的业务 Bundle 接入自身健康或指标。

## 配置与运维

Runtime 配置前缀为 `pdr.serviceClient.*`，覆盖 Provider 注册容量、总调用 timeout、最大尝试次数、退避、实例熔断、payload/metadata 上限。Provider 注册表默认最多 256 个本地协议 Provider，避免错误 Bundle 造成无界状态增长。Service Client 的 timeout 应小于对应 ResourceGovernor owner lane 的 cooperative execution timeout；否则治理层可能先发出取消信号。

`GET /api/v1/service-client` 是只读状态接口，需要 `resource.read`，输出 Provider、实例熔断、调用统计和 ResourceGovernor lane 状态；它不提供通用远程调用 POST，避免把 Runtime 变成未受业务授权约束的任意代理。零 Provider 对未使用远程调用的部署是合法空闲状态。

## HTTP Invocation Provider

`services/HttpInvocationProvider` 是第一个独立的实际传输 Provider。它仅依赖公共 `ServiceClientAPI`，通过 OSP 服务注册 `https`，并且只有在 `allowPlainHttp=true` 时才额外注册 `http`；核心 Client、Directory 和 Runtime Bundle 都不依赖该实现。

Provider 默认关闭。启用时必须配置非空 `allowedHosts` 与 `allowedPorts`。主机支持精确名称/IP及 `*.example.com` 形式的 DNS 后缀；端口、loopback、私网、link-local 与明文 HTTP 分别受独立策略控制。DNS 名称的全部解析结果必须通过地址策略，实际连接固定到已校验 IP，HTTP Host 和 HTTPS 证书/SNI 仍使用原始主机名，避免校验后再次解析造成 DNS rebinding。

调用固定使用 `POST` 访问广告中的 endpoint，operation 放入 `X-PDR-Operation`，不会拼接为路径。仅 `content-type`、`accept`、`traceparent`、`tracestate` 四个调用 metadata 可转发；调用方不能注入 Authorization。凭据规则按 `service + operation + host + port` 绑定，值来自操作员指定的环境变量或受限权限文件；最具体规则优先，同等具体的歧义匹配会 fail-closed。启用 `credentials.required` 后，无匹配规则也会在联网前拒绝，避免把某个服务的凭据带到另一目标。旧的全局 `authorizationEnvironment` 仅保留兼容，不应在多目标部署使用。

文件凭据按 `credentials.reloadIntervalMilliseconds` 在调用路径上惰性检查，不创建额外 watcher 线程。新文件必须完整读取、为单行非空 HTTP header 值并通过 ACL/权限策略，之后才原子替换该规则的内存快照；半写入、空文件或权限变宽会使当前调用返回 `http-credential-reload-failed`，不会发送旧值或损坏值。修复文件后下一次检查自动恢复。每条规则独立加锁，不阻塞其他目标；Health Contributor 只报告 generation、成功/失败计数与健康状态，不暴露密钥或文件路径。生产轮换应使用同目录临时文件写完并设置权限后原子替换。

Provider 不跟随 3xx，限制请求/响应字节数，并将 408、425、429、5xx 交给 Client 的重试、故障转移与实例熔断。连接和 HTTP I/O timeout 取本次 attempt 剩余时间与 Provider 上限的较小值。它把 `X-PDR-Attempt`、`X-PDR-Invocation-Id`、`X-PDR-Timeout-Milliseconds`、`X-PDR-Deadline-Unix-Microseconds` 和 `Idempotency-Key` 作为标准调用上下文传到远端；远端应以绝对 deadline 拒绝排队后才到达的过期请求。取消在 DNS 前后及响应分块读取期间协作检查；操作系统 DNS 调用本身通常不可中断，若它晚于 deadline 返回，Client 会将结果收敛为 deadline-exceeded。

示例：

```properties
pdr.serviceClient.httpProvider.enabled = true
pdr.serviceClient.httpProvider.allowedHosts = api.example.com,*.svc.example.com
pdr.serviceClient.httpProvider.allowedPorts = 443
pdr.serviceClient.httpProvider.credentials.required = true
pdr.serviceClient.httpProvider.credentials.count = 1
pdr.serviceClient.httpProvider.credentials.0.service = orders.v1
pdr.serviceClient.httpProvider.credentials.0.operation = get-*
pdr.serviceClient.httpProvider.credentials.0.host = api.example.com
pdr.serviceClient.httpProvider.credentials.0.port = 443
pdr.serviceClient.httpProvider.credentials.0.authorizationFile = C:/ProgramData/PocoDDS/secrets/orders.authorization
pdr.serviceClient.httpProvider.credentials.requireRestrictedFiles = true
pdr.serviceClient.httpProvider.credentials.reloadIntervalMilliseconds = 1000
```

## 多人协作约束

协议团队只实现 Provider，不修改 Client/RuntimeCoordinator 状态机；治理团队维护路由、重试、熔断、Provider Registry 和资源隔离语义；业务团队声明幂等性与错误分类。公共依赖只使用 `PocoDDS::ServiceClientCore/API`、`PocoDDS::ServiceDirectoryCore/API`，不得包含其他组件的 `src/` 或 Bundle 私有头文件。

每个协议 Provider 的测试目标应额外链接 `PocoDDS::ServiceClientTesting`，用 `runProviderConformance()` 和本地受控 fixture 计数器执行统一 TCK。TCK 验证身份稳定、请求夹具、无效输入、预取消、过期 deadline、单次外部副作用、结果分类、输入不可变性及调用后身份；协议团队还需补充自身的序列化、认证、网络错误映射和安全策略测试。安装 SDK 时通过 `find_package(PocoDDSRuntime COMPONENTS ServiceClientAPI ServiceClientTesting)` 获取该套件。
