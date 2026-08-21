# ADR 0001：Runtime 资源作用域与所有权

- 状态：Accepted
- 日期：2026-08-21

## 背景

现有 WebUI 同时展示主机资源、Runtime 聚合健康、进程、OSP Bundle、OSP Service、设备、
协议、指标和追踪，但部分接口缺少显式作用域和所有者。例如 `/api/v1/topology.resources`
实际来自主机采样，Service 清单没有进程和提供方 Bundle，`modules` 则没有对应运行时实体。
前端只能根据“是否主进程”推断归属，容易把整机、Runtime 和进程数据混为一谈。

## 决定

运行时对象层级固定为：

```text
Deployment（可选的外部控制面）
└─ Host
   └─ Runtime
      ├─ Process
      │  └─ Bundle
      │     └─ Service
      └─ Device / Protocol（由 Service 或 Bundle 提供的运行实例）
```

所有运行时资源必须包含稳定的 `kind`、`id`、`scope` 和 `owner` 信息：

- Host 资源只放在 `hostResources`，不再作为进程资源使用。
- Runtime 是当前 HTTP 管理端点的聚合边界；它不等于多机 Deployment。
- Process 资源只描述一个 OS 进程。主进程不能通过自身管理 API停止自己；受管子进程由父
  Runtime 的 `SubprocessManager` 控制。
- Bundle 是一个进程内 OSP 容器的部署和生命周期单元。Bundle 之间只有依赖关系，没有
  “子 Bundle”关系。
- Service 是 Bundle 注册的进程内能力。通用状态为 `registered`，健康状态单独表达；Service
  没有通用启停，生命周期由提供方 Bundle 控制。
- C++ 库、源码模块和页面组件不是运行时实体。现有 `modules` 字段废弃，WebUI 不再把它作为
  独立生命周期层级。
- 指标、告警和追踪必须携带或派生明确的 Host、Runtime、Process、Bundle、Service 作用域，
  不允许无定义的“系统级”标签。

`/api/v1/topology` 保留已有字段用于兼容，同时增加 `schemaVersion`、`scope`、`runtime`、
`hostResources`、资源的 `scope/owner/lifecycleOwner`。旧 `resources` 标记为 deprecated，
新 WebUI 不再读取它。

`/api/v1/process-detail` 增加当前进程的 `services`，服务清单不再由前端从主 Runtime 全量
拓扑中推断。子进程没有权威服务状态时返回空清单和明确的 `serviceInventoryAuthority`。

Runtime 身份、权限、管理审计、幂等账本和异步管理任务属于 Runtime 控制面，即使它们当前
物理运行在主进程，也不放进普通“进程配置”语义中。

## 可选方案

1. 只重排 WebUI：不能解决后端缺少所有权和资源混用，拒绝。
2. 立即删除全部 `/api/v1`：会破坏已有工具和测试，拒绝。
3. 将 Service 视为独立部署单元：与 OSP Registry 和 Bundle 生命周期不符，拒绝。
4. 将 Bundle 依赖显示成父子树：依赖可形成多对多图，不是所有权树，拒绝。

## 后果

- API 响应会略微增大，但每个页面可以根据服务端事实确定作用域。
- 旧客户端仍可读取兼容字段；新客户端必须优先使用显式作用域字段。
- 旧 OSP 基础服务若没有 `pdr.bundle` 属性，将明确标记 `ownerKnown=false`，不得猜测所有者。
- 多机 Deployment 页面只有在存在真正的聚合控制面后才能启用。

## 验证方式

1. 契约测试验证 Host 与 Process 资源字段不会互相代用。
2. 每个 Bundle 必须带 `processId`，每个 Service 必须带 `processId`；已知提供方还必须带
   `bundleId` 和 Bundle 生命周期所有者。
3. 子进程详情不得继承主进程 Service、Bundle、配置或治理数据。
4. WebUI 中 Runtime 治理与进程配置分离；Service 页面不显示通用启停。
5. 构建 Web/系统监控/Home Bundle，并在真实 Runtime 上检查 API、DOM 和页面截图。

## 回滚条件

若显式字段导致已有客户端无法兼容，可暂时保留旧字段和旧页面入口，但不得重新把 Host 数据
标记为 Process 数据，也不得恢复无所有者的隐式前端推断。完整回滚需由新的 ADR 说明替代模型。
