# RuntimeCore 稳定边界与使用

RuntimeCore 是所有软件模型共享的稳定内核，不依赖 Poco/OSP、Fast DDS、ROS 2、Qt 或设备
SDK。业务 Module/Service 只依赖这里的契约；通信中间件和操作系统 API 必须停留在 Adapter。

## 已提供的核心能力

- `Contract.h`：统一 `Outcome<T>`、错误码、关联/因果/Trace/Deadline 消息上下文；
- `Codec.h`：确定性 `PDRM/1` 二进制消息编码，统一 Topic、Schema、Header、Payload、
  Deadline 和尺寸/数量限制，供所有跨边界 Adapter 复用；
- `Executor.h`：Inline 与有界 Thread Pool，支持拒绝最新、丢弃最旧、阻塞发布者三种背压；
- `Transport.h`：消息、Topic、订阅生命周期和能力声明；
- `InProcessTransport.h`：零拷贝 Payload 的同步/异步进程内投递，单个订阅异常不会中断其他订阅；
- `TransportRegistry.h`：Adapter 工厂注册、能力枚举、配置化创建和 RAII 卸载；
- `Host.h` / `StaticHost.h`：组件依赖图、确定性拓扑顺序、配置/启动/停止、失败逆序回滚和健康聚合。
- `PocoDDS::RuntimeCoreTesting`：可安装的 Transport Conformance Kit，统一检查 ID/能力、
  投递、故障隔离、订阅生命周期、类型契约、Deadline 和参数校验。

## 最小程序

```cpp
#include <PocoDDS/RuntimeCore/InProcessTransport.h>
#include <PocoDDS/RuntimeCore/StaticHost.h>
#include <PocoDDS/RuntimeCore/TransportRegistry.h>

using namespace PocoDDS::RuntimeCore;

TransportRegistry transports;
auto inprocRegistration = registerInProcessTransport(transports);
auto transport = transports.create("inproc");

StaticHost host;
// registerComponent(...) -> configure(...) -> start() -> stop()
```

`IHostedComponent::stop()` 必须幂等，并能处理 configure/start 只完成一部分的情况。Host 不会
提供全局 Service Locator；组件依赖只表达生命周期顺序，业务依赖通过构造函数/Port 注入，
避免把 Registry 变成隐式耦合中心。

## 并发语义

默认 `InProcessTransport` 使用 Inline Executor，适合简单桌面程序。耗时订阅必须显式注入
`ThreadPoolExecutor`。队列容量和溢出策略必须由项目设置，不能依赖无界队列：

```cpp
ThreadPoolExecutor::Options options;
options.workerCount = 4;
options.queueCapacity = 1024;
options.overflowPolicy = OverflowPolicy::rejectNewest;
auto executor = std::make_shared<ThreadPoolExecutor>(options);
InProcessTransport transport(executor);
```

`publishAsync()` 的 `submission` 表示任务是否进入执行器，`completion` 表示最终订阅投递结果。
Deadline 在真正投递前再次检查。关闭模式可选择排空或取消尚未运行的任务。

## 完成门槛

```powershell
cmake --preset desktop-lite
cmake --build --preset desktop-lite
ctest --preset desktop-lite -C Release --output-on-failure
python tools/check_compatibility.py
python tools/check_architecture.py --root .
```

公共类型与 `PocoDDS::RuntimeCore` CMake Target 已进入兼容性基线。破坏性变更需要提升 Runtime
主版本并有意更新基线，不能通过修改测试掩盖。
