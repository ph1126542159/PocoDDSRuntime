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

## 自动兼容性门禁

当前 `0.1.0` 兼容基线位于 `contracts/compatibility/0.1.0.json`。执行：

```powershell
python tools/check_compatibility.py
```

门禁检查已发布的 `PocoDDS::` CMake Target、公共 SDK 头文件和类型、配置属性
类型与范围、OpenAPI 方法和路径，以及 AsyncAPI Channel 名称和地址。

同一主版本允许增加可选配置、HTTP 操作、Channel 和公共类型。删除或改变既有契约
时检查会失败；必须提升 Runtime 主版本、提供迁移说明，并经过评审后建立新基线。
不能仅通过修改基线文件绕过不兼容变更。

## 升级、健康检查与回滚

`docs/compatibility/releases.json` 是发布兼容矩阵。升级工具默认只允许同一主版本升级；
跨主版本必须明确传入 `--allow-major-upgrade`，并先更新迁移说明和兼容矩阵。

```powershell
python tools/upgrade_manager.py apply `
  --package C:/release/pdr-runtime `
  --manifest C:/release/SHA256SUMS.json `
  --target C:/deploy/pdr-runtime `
  --audit C:/deploy/audit/upgrades.jsonl `
  --health-url https://127.0.0.1:9443/health/ready `
  --health-timeout 30
```

工具先验证清单中的每个 SHA-256，再复制到目标同盘的暂存目录并二次校验。旧目录先改名
为备份，暂存目录再原子改名为正式目录。健康检查失败时立即恢复备份。手动回滚：

```powershell
python tools/upgrade_manager.py rollback `
  --target C:/deploy/pdr-runtime `
  --audit C:/deploy/audit/upgrades.jsonl
```

审计日志使用 JSON Lines，记录来源/目标版本、预检、暂存校验、激活、健康检查和回滚。
升级前必须停止仍占用 DLL/可执行文件的进程；板端 A/B 分区切换仍由具体设备适配器实现。
