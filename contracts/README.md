# PocoDDSRuntime 契约

本目录是跨入口契约的唯一文档入口：

- `schemas/runtime-config.schema.json`：运行时配置类型、范围和必填项。
- `schemas/runtime-resource.schema.json`：Host → Runtime → Process → Bundle → Service 的作用域、所有权和生命周期所有者公共契约。
- `schemas/release-trust-policy.schema.json`：发布允许密钥、有效期与吊销列表格式。
- `schemas/plugin-trust-policy.schema.json`：插件发布者、允许命名范围、Ed25519 公钥、有效期和吊销契约。
- `schemas/plugin-host-state.schema.json`：隔离插件宿主向 Runtime/Web 暴露的跨进程状态快照。
- `schemas/release-qualification.schema.json`：自动化测试、制品、Git 与外部验收的统一发行资格证据。
- `schemas/external-acceptance.schema.json`：目标板、物理协议、生产身份、现场网络和长稳的候选绑定验收证据。
- `schemas/external-approver-trust-policy.schema.json`：外部验收批准者、Ed25519 密钥、允许类型、有效期及吊销契约。
- `schemas/evidence-bundle.schema.json`：可移植发行证据 ZIP 内部文件、角色、大小和摘要清单。
- `schemas/release-pipeline.schema.json`：一键发行阶段、命令参数、超时和输入输出检查点契约。
- `openapi/runtime.yaml`：HTTP 管理接口契约入口。
- `GET /api/v1/devices`：当前活跃设备适配器的版本化清单。
- `asyncapi/runtime.yaml`：DDS/MQTT/事件契约入口。
- `compatibility/0.1.0.json`：已发布公共 SDK 和通信契约的兼容基线。
- `pdr-plugin-runtime.json`（安装到 Runtime `bin`）：插件 API、ABI、目标平台和工具链契约；
  Bundle Manifest 使用四个 `PDR-*` 字段声明其构建兼容范围。
- DDS 数据结构仍以 `platform/DDS/idl` 中的 IDL 为代码生成来源；新增 Topic 必须同时登记到 AsyncAPI。

契约变更规则：

1. 删除字段、收紧范围或改变单位属于不兼容变更，必须提升主版本。
2. 新增可选字段属于兼容变更。
3. `requestId`、`traceId`、`deviceId` 是跨入口公共元数据，不得复用为业务字段。
4. CI 的 `contract-files` 保证契约文件完整，`configuration-contract` 对照 C++ Validator 检查全局数值范围、全部索引族、协议边界及已发布必填项的兼容子集，`compatibility-baseline` 阻止同一主版本删除或收紧已发布契约。历史 Schema 未要求 `pdr.subprocess.shutdownTimeoutMilliseconds`，同一主版本只发布其类型和范围；Runtime 与离线校验仍要求实际部署提供该字段。
5. 插件 API 或 ABI 版本变化属于破坏性变更；同一 Runtime 主版本不得静默修改，ABI 指纹由构建平台和编译器主版本生成。
