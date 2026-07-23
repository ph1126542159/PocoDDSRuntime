# NetworkEnvironment 服务

## 实现过程

服务枚举网络接口、地址和状态；Linux 下通过 netlink 监视变化。变化被转换为服务事件并发布到 DDS。

## 用法

加载 Bundle 后，进程内查询 `NetworkEnvironmentService`，或通过 `pdr.network.request/response` 查询；订阅 `pdr.network.environment` 获取变化事件。

容器和目标板看到的是其所在网络命名空间的接口，不一定等同于宿主机。
