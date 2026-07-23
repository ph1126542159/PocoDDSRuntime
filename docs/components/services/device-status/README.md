# DeviceStatus 服务

## 实现过程

服务维护状态更新、消息和设备状态变化，通过 ActiveDispatcher 串行处理异步更新。Activator 注册 OSP 服务，并将请求、响应和状态事件映射到 DDS。

## 用法

进程内获取 `DeviceStatusService` 发布/查询状态；跨进程使用 `pdr.status.request`、`pdr.status.response`，并订阅 `pdr.device.status`。

状态 class/标识必须稳定；同类状态的替换规则由服务接口定义。

## 配置和生命周期

```properties
# 消息最大保留时间，单位为小时
deviceStatus.messages.maxAge = 720
pdr.fastdds.domainId = 0
```

Bundle run level 为 220。Activator 创建 `DeviceStatusServiceImpl`，注册 `pdr.service.deviceStatus`，再启动 DDS Endpoint。状态变化通过 Poco event 转成 `pdr.device.status` 的 `updated` 事件。

## DDS 操作

支持 `status`、`statusOfSource`、`post`、`clear`、`clearSource`、`acknowledge`、`acknowledgeUpTo`、`remove`、`messages` 和 `reset`。这些操作的 payload 是 JSON，字段与 `StatusUpdate`、`StatusMessage`、source、id 及时间范围对应。

写操作会更新 SQLite 并产生事件；客户端必须使用响应 status 判断成功，不能只等事件。数据库位于该 Bundle 的 OSP persistent directory，文件名为 `devicestatus.sqlite`。启动时自动创建 `messages` 表，`messages.maxAge` 按小时清理旧消息。

## 使用建议

状态 source 使用稳定设备/子系统 ID，class 用于分类，message ID 用于确认和删除。先通过 `post` 建立一条测试状态，再用 `statusOfSource`/`messages` 查询，最后测试 acknowledge 和 clear。
