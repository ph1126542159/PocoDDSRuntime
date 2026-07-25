# 兼容矩阵

| 资产 | 当前版本 | 兼容规则 |
| --- | --- | --- |
| Runtime | 0.1.0 | 语义化版本 |
| HTTP API | 0.1.0 | OpenAPI 删除/收紧字段为不兼容 |
| Event Contract | 0.1.0 | AsyncAPI 地址或必填字段变化为不兼容 |
| Configuration Schema | 0.1.0 | 删除 key、改变类型或收紧范围为不兼容 |
| Database | 尚未统一 | 引入 Migration 后登记 |
| Firmware | 设备定义 | 必须由设备适配器报告 |

每次 Release 必须更新此表，并保存构建、测试和契约检查证据。
