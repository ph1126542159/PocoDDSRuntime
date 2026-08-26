# 组件 Service 契约独立测试

组件团队不需要启动完整 PocoDDSRuntime，即可验证自己的 `pdr-component.json`、
`bundle/service-contracts.json` 以及依赖 Provider 的真实契约是否兼容。测试只读取显式输入，
不会连接 Service Registry、网络、设备或当前运行中的 Runtime。

## 直接使用 CLI

Consumer 维护自己的组件和 Requirement，Provider 团队提供其版本化的
`service-contracts.json`。Consumer CI 显式固定这些文件：

```powershell
pdr component contract-test components/OrderWorkflow `
  --service-contract components/OrderWorkflow/bundle/service-contracts.json `
  --provider-contract contracts/providers/scheduler/service-contracts.json `
  --report build/reports/order-workflow-contract.json
```

测试检查：

- 组件协作契约的 ID、类型、Owner、平面、Target 和隔离方式；
- Service 契约字段、标识符、语义版本、版本范围、重复声明和 Provider 最小数量；
- 必需 Requirement 是否存在足量兼容 Provider；
- 可选 Requirement 缺失是否保留为可见但不阻断的结果；
- 组件、Consumer 契约和全部 Provider 契约的 SHA-256 输入集合。

必需依赖缺失、版本不匹配或数量不足返回非零。报告符合
`contracts/schemas/component-contract-conformance.schema.json`，可以作为评审和 CI 制品；
改变任意输入后必须重新生成，不能沿用旧报告。

Reviewer 或后续流水线可以重新计算全部输入摘要和匹配结果：

```powershell
pdr component contract-verify build/reports/order-workflow-contract.json
```

输入文件变化、报告字段被修改、输入缺失或原报告本身未通过都会返回非零。

## CMake/CTest 集成

安装包提供 `pdr_add_component_contract_test()`。组件自己的构建只需要安装后的 SDK、Python
解释器和契约文件，不链接 Server，也不启动 OSP：

```cmake
find_package(PocoDDSRuntime 0.1 CONFIG REQUIRED COMPONENTS ServiceDependencyCore)
include(CTest)

pdr_add_component_contract_test(
    NAME order-workflow-contract
    COMPONENT ${CMAKE_CURRENT_SOURCE_DIR}/pdr-component.json
    SERVICE_CONTRACT ${CMAKE_CURRENT_SOURCE_DIR}/bundle/service-contracts.json
    PROVIDER_CONTRACTS
        ${CMAKE_CURRENT_SOURCE_DIR}/fixtures/scheduler.service-contracts.json
    REPORT ${CMAKE_CURRENT_BINARY_DIR}/reports/order-workflow-contract.json)
```

`PROVIDER_CONTRACTS` 可以重复或列出多个文件，以验证 `minimumProviders > 1` 的场景。Provider
契约必须来自明确版本或受控依赖，不应在测试中手写一个永远兼容的宽松替身；否则只能证明替身，
不能证明团队间的真实接口兼容。

## 模板支持

组件模板 v7 开始，新的 Bundle/Plugin 默认生成：

- `bundle/service-contracts.json`；
- Bundle 资源打包声明；
- `pdr.bundle` 与 `pdr.service.readiness` 注册属性；
- 无 Runtime 的组件契约 CTest。

初始模板只声明它实际注册的 Status Service。增加业务 Service 或 Requirement 时，由组件 Owner
修改产品所有的契约文件，并把 Provider 团队发布的契约加入 `PROVIDER_CONTRACTS`。

既有 v1-v6 Bundle/Plugin 升级到 v7 时，模板不会修改产品所有的 Activator，而是创建
`provides=[]`、`requires=[]` 的安全空契约。Owner 必须先确认每个 Service 注册包含正确的
`pdr.bundle` 和 Readiness 属性，再填写 Provider 声明，避免升级本身改变 Runtime Readiness。

## 证据边界

该测试证明静态声明、版本范围和 Provider 数量在给定输入下兼容。它不证明 Service 已在 Runtime
注册、Owner 属性正确、启动顺序、动态重绑定、Readiness 传播或故障恢复。上述行为仍分别由
Service Dependency Runtime 集成测试、生命周期测试和真实运行验收证明。

该能力与 `SystemMonitoring.cpp` 无关。
