# 新增协议

1. 在 `platform/protocols/<Name>` 分离 Codec 与 Transport。
2. 对非法长度、边界值、重复帧和超时编写测试。
3. 使用统一 Deadline、Retry、Circuit Breaker 和错误分类。
4. Topic/API/帧字段、单位、范围、超时和幂等语义写入契约。
5. 协议组件不得直接编排产品业务。
