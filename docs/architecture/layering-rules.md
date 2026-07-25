# 分层依赖规则

依赖方向固定为：入口（Qt、HTTP、DDS）→ Application → Port → Platform/Device Adapter。

- 入口只负责鉴权、反序列化、调用用例和序列化结果。
- `application/` 不得包含 Qt、Poco Net、Fast DDS 或具体设备头文件。
- 设备回调转换为领域事件，不得直接联动其他设备。
- 超时、重试、互锁、取消和补偿在 Application/Policy 层表达。
- Platform 提供可靠性、健康、配置、通信和持久化基础能力，不包含产品业务。

新增代码评审必须检查依赖方向；无法遵守时先记录 ADR。
