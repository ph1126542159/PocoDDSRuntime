# PocoDDSRuntime 契约

本目录是跨入口契约的唯一文档入口：

- `schemas/runtime-config.schema.json`：运行时配置类型、范围和必填项。
- `openapi/runtime.yaml`：HTTP 管理接口契约入口。
- `GET /api/v1/devices`：当前活跃设备适配器的版本化清单。
- `asyncapi/runtime.yaml`：DDS/MQTT/事件契约入口。
- `compatibility/0.1.0.json`：已发布公共 SDK 和通信契约的兼容基线。
- DDS 数据结构仍以 `platform/DDS/idl` 中的 IDL 为代码生成来源；新增 Topic 必须同时登记到 AsyncAPI。

契约变更规则：

1. 删除字段、收紧范围或改变单位属于不兼容变更，必须提升主版本。
2. 新增可选字段属于兼容变更。
3. `requestId`、`traceId`、`deviceId` 是跨入口公共元数据，不得复用为业务字段。
4. CI 的 `contract-files` 保证契约文件完整，`compatibility-baseline` 阻止同一主版本删除或收紧已发布契约。
