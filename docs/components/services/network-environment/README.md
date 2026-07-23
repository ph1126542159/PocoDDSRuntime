# NetworkEnvironment 服务

## 实现过程

服务枚举网络接口、地址和状态；Linux 下通过 netlink 监视变化。变化被转换为服务事件并发布到 DDS。

## 用法

加载 Bundle 后，进程内查询 `NetworkEnvironmentService`，或通过 `pdr.network.request/response` 查询；订阅 `pdr.network.environment` 获取变化事件。

容器和目标板看到的是其所在网络命名空间的接口，不一定等同于宿主机。

## DDS 操作

| operation | payload | 说明 |
| --- | --- | --- |
| `findActive` | `{"version":0}` | 0=IPv4/IPv6，4=仅 IPv4，6=仅 IPv6 |
| `enumerate` | `{"options":0}` | 返回接口数组 |

接口对象包含名称、显示名、适配器地址、状态和地址元组等实现可获得字段。网络变化发布到 `pdr.network.environment`，event operation 为 `changed`，payload 中 `changeType` 是枚举整数。

## 实现与配置

Linux 实现使用 netlink socket 监听链路/地址变化；其他平台使用对应枚举能力。服务没有独立配置，只有公共 `pdr.fastdds.domainId`。如果部署在容器内，需要给容器正确网络命名空间和权限。

验证时应先用 `ip addr`/`Get-NetAdapter` 建立基线，再比较 `enumerate` 返回，而不是只检查事件是否触发。
