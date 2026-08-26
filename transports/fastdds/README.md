# Fast DDS Transport Adapter

`PocoDDS::FastDDSTransport` 将通用 `RuntimeCore::IMessageTransport` 映射到现有 Fast DDS
`Envelope` 数据面。业务代码只依赖 RuntimeCore；Adapter 将 `PDRM/1` 以 Base64 封装在 Envelope
Payload 中，并通过 `TransportRegistry` 以 `fastdds` ID 创建。

## 什么时候使用

- 大型桌面/边缘应用需要跨主机低延迟发布订阅、自动发现时，可选 Fast DDS；普通单进程桌面程序
  仍使用 `inproc`，同机多进程优先 `ipc`。
- 机器人管理面可复用本 Adapter，但机器人强类型接口、Action/Service、生命周期与安全控制应使用
  `robotics/ros2_ws` 中的原生 ROS 2 包，不能把通用 Envelope 当作完整 ROS 2 模型。
- WebUI 继续通过 Host 的 HTTP/WebSocket 管理面访问，不直接链接 Fast DDS。

## 配置

```cmake
find_package(PocoDDSRuntime CONFIG REQUIRED COMPONENTS FastDDSTransport)
target_link_libraries(my_service PRIVATE PocoDDS::FastDDSTransport)
```

Registry 工厂继续只负责实例级 `domainId`、`participantName`、`topicPrefix` 和
`maximumFrameBytes`。未知 key 和越界数字会直接拒绝，避免多人维护时拼写错误静默退回默认行为。
网络发现属于进程部署边界：复制安装包中的
`share/PocoDDSRuntime/examples/fastdds-deployment.properties.example`，在进程启动前把
`PDR_FASTDDS_PROFILE` 指向该文件。这样不会改变业务模块 API，也不会让不同 Bundle 各自链接或配置
Fast DDS。

| Profile key | 默认值 | 作用 |
|---|---:|---|
| `profileVersion` | 必填 `1` | Profile 契约版本 |
| `interfaceWhitelist` | 空 | 逗号分隔的 UDPv4 接口地址/名称 |
| `initialPeers` | 空 | 逗号分隔的 `IPv4` 或 `IPv4:port` |
| `avoidBuiltinMulticast` | `false` | 禁止内建组播；启用时必须提供 Peer |
| `sharedMemory` | `false` | 在 UDPv4 之外增加 Fast DDS SHM 数据通道 |
| `maxInitialPeersRange` | `4` | Peer 未写端口时扫描的 Participant 通道数，范围 1..32 |

```properties
profileVersion=1
interfaceWhitelist=192.168.10.20
initialPeers=192.168.10.21,192.168.10.22:25610
avoidBuiltinMulticast=true
sharedMemory=true
maxInitialPeersRange=4
```

```powershell
$env:PDR_FASTDDS_PROFILE = "C:\deploy\fastdds-deployment.properties"
& "C:\deploy\pdr-runtime.exe"
```

部署或重启进程前，先用安装包内的无网络预检命令验证同一文件：

```powershell
pdr-fastdds-profile-check --profile C:\deploy\fastdds-deployment.properties
```

受控部署应同时固定文件内容摘要：

```powershell
$digest = (Get-FileHash -Algorithm SHA256 C:\deploy\fastdds-deployment.properties).Hash.ToLowerInvariant()
pdr-fastdds-profile-check --profile C:\deploy\fastdds-deployment.properties --sha256 $digest
$env:PDR_FASTDDS_PROFILE_SHA256 = $digest
```

Runtime 对最多 64 KiB 的文件执行单次二进制读取，解析和 SHA-256 基于同一份内存字节。摘要必须是
64 位小写十六进制；摘要缺失时保持兼容模式，设置后内容不一致会在 Participant 创建前失败。

校验器只构造 Runtime 配置对象，不启动 Participant、不打开 UDP/SHM 传输。成功时输出脱敏摘要，
失败时返回非零退出码，适合 Launcher、CI 和部署脚本作为启动前门禁。不传 `--profile` 时校验当前
进程的 `PDR_FASTDDS_PROFILE`；未设置变量会明确报告 `configured=false`。

Profile 未设置时保持原有 `UDPv4 + 组播发现`。Profile 文件未知 key、重复 key、非法布尔值、非法
IPv4/端口、版本错误以及“无 Peer 却关闭组播”都会在 Participant 创建前失败。Peer 不写端口时，
Fast DDS 按 `maxInitialPeersRange` 和 Domain 端口规则展开；写端口时只使用指定端口。
`sharedMemory=true` 不会取消 UDP 元流量，也不能绕过防火墙或替代跨主机发现。

## 当前语义边界

- 每个逻辑 Topic 映射为一个 Fast DDS Topic；消息体统一为 `PDRM/1`。
- Adapter 抑制自身 DDS 回环，但先执行本进程投递，因此本地和远端订阅具有同一业务契约。
- 现有底层 `PocoDDS::FastDDS::Runtime` 使用 Fast DDS 默认端点 QoS；因此本 Adapter 当前不宣称
  durable，也不把 `TopicSpec::durable` 映射为持久化历史。需要可靠性、History、Deadline、Liveliness
  的项目，应先扩展显式 QoS Profile，再进行项目级性能与故障验收。
- 底层 Runtime 暂不支持物理 DataReader 单独删除；逻辑取消订阅会立即移除业务 Handler，物理
  Reader 在本次 Runtime 生命周期内保留，并在 `stop()` 时统一回收。

`fastdds-transport-smoke` 使用同一 OS 进程内的两个独立 DomainParticipant 验证跨 Participant
下发、二进制 Payload、回环抑制、严格配置解析、部署策略快照、注册表和 7 项 Transport
Conformance。它不是独立进程或跨设备证明；防火墙、丢包、多网卡和实时性仍需单独验收。
