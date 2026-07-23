# pdr-runtime 主程序

## 职责

`server/src/MacchinaServer.cpp` 是单一 OSP 服务器入口。它初始化日志和 OSP 子系统，启动 Bundle 管理器，再按 `pdr-subprocesses.properties` 的编号顺序启动子进程。

## 实现过程

1. 由 `Poco::Util::ServerApplication` 完成命令行和配置加载。
2. 建立 OSP Bundle 仓库、加载器及服务注册表。
3. 启动 `BundleManager`，监视本进程 `bundles/`。
4. 启动 OSP Bundles。
5. 创建 `SubprocessManager`，按配置启动外部进程。
6. 退出时逆序停止子进程，再停止 OSP。

## 用法

```powershell
Set-Location build/bin
./pdr-runtime.exe
```

Windows 使用 `/option=value`，Unix 使用 `--option=value`。默认配置来自同目录的 `pdr-runtime.properties` 和 `pdr-subprocesses.properties`。

## 验证

检查控制台/`logs/` 中的 Bundle 启动信息，并执行：

```powershell
ctest --test-dir build -C Release --output-on-failure
```

## 关键源码和调用顺序

| 文件/组件 | 作用 |
| --- | --- |
| `server/src/MacchinaServer.cpp` | 进程入口、日志格式、OSP/DDS/追踪初始化 |
| `platform/BundleManagement` | 运行期 Bundle 仓库监视 |
| `platform/ProcessManagement` | 读取配置并启动外部子进程 |
| `config/pdr-runtime.properties` | 主进程配置模板 |
| `config/pdr-subprocesses.properties` | 子进程清单模板 |

`initialize()` 阶段先扩大 Poco 默认线程池，再创建 Fast DDS Runtime；启用追踪时创建 TraceStore、HTTP 查询服务和可选 OTLP 导出器。随后初始化 OSP，启动 Bundle 热更新管理器，最后启动配置中的子进程。关闭顺序与之相反，避免 Bundle 已卸载但子进程仍向它发送请求。

## 配置参考

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `poco.threadPool.default.capacity` | `32` | Poco 默认线程池最小容量 |
| `osp.bundleRepository` | `${application.dir}bundles/` | Bundle 仓库；建议保留末尾 `/` |
| `osp.bundleMonitor.enabled` | `true` | 是否监视 Bundle 变化 |
| `osp.bundleMonitor.intervalMilliseconds` | `1000` | 扫描周期，毫秒 |
| `osp.codeCache` | `${application.dir}codeCache` | OSP 动态库展开/缓存目录 |
| `osp.data` | `${application.dir}data` | Bundle 数据目录 |
| `pdr.fastdds.domainId` | `0` | 所有 DDS 参与者必须一致 |
| `pdr.subprocess.configuration` | `${application.dir}pdr-subprocesses.properties` | 子进程配置文件 |
| `pdr.subprocess.shutdownTimeoutMilliseconds` | `5000` | 每个子进程退出等待时间 |
| `observability.otlpHttpEndpoint` | 空 | 空值只保留本地追踪；非空时导出 OTLP |

日志配置使用 Poco Logging 属性。默认同时输出控制台和 `${application.dir}logs/pdr-runtime.log`，单文件 10 MB，保留 10 个归档。

## 常用启动方式

```powershell
# 使用 build/bin 中的默认配置
Set-Location E:\PocoDDSRuntime\build\bin
.\pdr-runtime.exe

# 使用另一个配置文件；Windows 参数以 / 开头
.\pdr-runtime.exe /config-file=C:\deploy\pdr-runtime.properties
```

Linux：

```bash
cd build/host-install/bin
./pdr-runtime --config-file=../etc/pdr-runtime.properties
```

## 故障定位

- 启动即报 Bundle 解析错误：检查 `bundles/` 中是否有复制未完成或版本依赖不满足的包。
- DDS 客户端无响应：核对 `pdr.fastdds.domainId`、网卡发现和防火墙。
- 子进程未启动：检查 `pdr-subprocesses.properties` 路径、`subprocess.count` 和相对工作目录。
- WebUI 无法访问：检查 `osp.web.server.host/port`，以及 Web/登录/主页 Bundle 是否已加载。
