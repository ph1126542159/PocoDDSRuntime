# 新增设备

1. 在 `platform/devices/<Name>` 实现设备抽象，不暴露协议实现给业务层。
2. 配置项加入 properties 和 JSON Schema，并提供范围校验。
3. 断线重连使用 Reliability Policy；危险设备必须实现安全复位。
4. 提供仿真实现、边界测试和健康贡献者。
5. 真实板卡验收单独记录，不能用主机 Smoke Test 代替。
