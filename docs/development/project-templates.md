# 项目模板版本与安全升级

新产品项目在 `pdr-project.yaml.template` 中记录模板 ID 和版本，并在
`.pdr/template-state.json` 保存渲染上下文与受管文件基线。当前只管理以下脚手架文件：

- `CMakeLists.txt`；
- `CMakePresets.json`；
- `README.md`；
- `.gitignore`。

业务组件、项目配置、部署参数和测试代码永远不属于模板受管范围。模板升级不能借机修改业务
源码。模板状态和备份目录属于项目仓库；`.pdr/template-backups/` 默认忽略，状态文件应提交。

## 日常检查

```powershell
pdr project template status pdr-project.yaml --check `
  --report build/template-status.json
```

`--check` 在以下情况返回 2，适合作为 CI 门禁：有新模板版本、Manifest 渲染上下文改变、受管
文件被修改或删除、目标模板文件被从状态中移除。已经明确选择 `--keep-project` 的文件列在
`unmanagedFiles`，不会伪装成模板受管文件，也不会阻止后续检查。

## 旧项目采用

旧项目没有模板元数据时，必须明确告诉 CLI 它最接近哪个历史模板：

```powershell
pdr project template adopt pdr-project.yaml --version 1 `
  --report build/template-adopt.json
```

采用过程只把内容与历史模板逐字节一致的文件登记为受管文件。缺失或已经定制的文件登记为
`unmanagedFiles`，不会被当作“干净基线”从而在下一次升级中静默覆盖。采用操作同时更新
Manifest、组合文件和状态，并写入可恢复事务备份。

## 升级与冲突选择

```powershell
pdr project template upgrade pdr-project.yaml `
  --report build/template-upgrade.json
```

未修改的受管文件自动升级；当前内容已等于目标模板时只更新基线。定制文件产生冲突，且在所有
冲突被明确处理前不会修改任何文件：

```powershell
# 保留产品自己的 CMake，转为不受模板管理
pdr project template upgrade pdr-project.yaml `
  --keep-project CMakeLists.txt

# 明确放弃定制 README，接受模板版本
pdr project template upgrade pdr-project.yaml `
  --accept-template README.md
```

两个选项都可以重复使用，但同一路径不能同时选择。只允许选择当前报告中的真实冲突，避免拼写
错误造成意外处理。升级写入前会重新核对 Manifest、状态、组合文件和全部模板文件摘要；计划
后发生并发修改时立即失败。

## 事务恢复

每次采用或升级先在 `.pdr/template-backups/<transaction-id>/` 保存原文件，并在每次写入前
记录 `attempted`。正常异常会自动回滚；进程中断后执行：

```powershell
pdr project template recover pdr-project.yaml `
  --journal .pdr/template-backups/<transaction-id>/journal.json
```

恢复只处理该事务已经尝试写入的文件，并验证备份摘要和备份目录边界。`rollback-failed` 修复
外部原因后需显式增加 `--retry-rollback`，不得把部分恢复状态标为成功。
