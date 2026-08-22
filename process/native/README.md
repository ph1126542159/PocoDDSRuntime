# Native Desktop Process Supervisor

`PocoDDS::NativeProcess` 为 `desktop-distributed` 提供不依赖 Poco/OSP 的本机子进程监管。
它只负责 Host 拥有的操作系统进程，不加载 Bundle，也不允许子进程访问主进程内 Registry。

## 能力

- Windows `CreateProcessW + Job Object`，在主线程恢复前加入 Job，关闭时清理整个进程树；
- Linux/POSIX `fork/exec + process group`，停止时对整个进程组发送 `SIGTERM/SIGKILL`；
- 可执行文件和工作目录默认限制在 `processRoot` 内，拒绝 `..` 或绝对路径逃逸；
- 参数不经过 Shell；Windows 使用与 `CommandLineToArgvW` 兼容的转义；
- 继承父进程环境并覆盖 `ProcessSpec.environment`；
- 支持 stdout/stderr 追加文件、依赖排序、部分启动回滚、逆序停止和显式重启；
- 支持 `never/onFailure/always` 重启策略、滑动时间窗与重启预算；预算耗尽进入
  `quarantined`，不会无限崩溃循环。

## 使用

```cpp
#include <PocoDDS/NativeProcess/NativeProcessSupervisor.h>

using namespace PocoDDS::NativeProcess;
using namespace PocoDDS::RuntimeCore;

NativeProcessSupervisor processes({"E:/Product/bin/processes"});
ProcessSpec worker;
worker.id = "vision-worker";
worker.executable = "vision-worker.exe";
worker.arguments = {"--ipc", "vision"};
worker.restartPolicy = RestartPolicy::onFailure;
worker.maximumRestarts = 3;
worker.restartWindow = std::chrono::seconds(60);

auto registered = processes.registerProcess(worker);
auto started = processes.startAll();
```

Consumer CMake：

```cmake
find_package(PDRNativeProcess CONFIG REQUIRED)
target_link_libraries(my_desktop_host PRIVATE PocoDDS::NativeProcess)
```

## 边界

- `GenerateConsoleCtrlEvent`/`SIGTERM` 是尽力而为的正常退出请求；超时后强制清理进程树；
- 产品若有 IPC Shutdown/ACK，应先通过业务控制 Port 完成握手，再调用 `stop()` 作为所有权
  回收门槛；
- Desktop Supervisor 不提供 OSP Bundle、WebUI 管理面、跨机调度或持久任务队列；需要这些
  能力应升级到 `edge-test`/`edge-industrial`；
- `allowOutsideProcessRoot=true` 会扩大执行边界，只能由部署层显式开启并进行安全评审。

`native-process-smoke` 使用真实子进程验证环境覆盖、启动/停止/重启、崩溃重启预算、隔离和
依赖门禁。Windows 与 Linux CI 都必须通过后，才能作为双平台交付证据。
