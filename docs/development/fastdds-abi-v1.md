# Fast DDS 稳定 ABI v1

`PocoDDS::FastDDSAbiV1` 是 Fast DDS Runtime 面向外部组件的版本化二进制边界。它只公开
`PocoDDS/DDS/AbiV1.h` 中的 C ABI，不把 Fast DDS、POCO、STL 类型或 C++ 对象布局传给调用方。
旧的 `PDRFastDDS.dll` 与 `PDRFastDDSCore.dll` 暂时保留用于兼容，不能再作为新插件的 ABI
依赖。

## 使用边界

- 用 `pdr_fastdds_abi_version_v1()` 在加载时确认 ABI 版本。
- 用 `pdr_fastdds_envelope_size_v1()` 与调用方的 `sizeof(PdrFastDdsEnvelopeV1)` 比较，拒绝
  编译器布局不一致的组合。
- Runtime 通过 `PdrFastDdsRuntimeV1*` 不透明句柄持有，只能由对应的 `create`/`destroy`
  函数创建和释放。
- 每个操作返回 `PdrFastDdsStatusV1` 数值，并可写入调用方提供的定长错误缓冲区；异常不会跨
  DLL 边界。
- `PdrFastDdsEnvelopeV1.struct_size` 必须初始化为 `sizeof(PdrFastDdsEnvelopeV1)`。实现接受更大
  的结构体，为同一 v1 尾部扩展保留空间。
- 订阅回调中的字符串指针只在本次回调期间有效；需要异步使用时由调用方复制。
- 回调不得阻塞 DDS 接收线程。长任务应投递到调用方自己的执行器。
- `subscribe` 返回独立的 `PdrFastDdsSubscriptionV1*`。插件卸载前必须先调用
  `pdr_fastdds_subscription_unsubscribe_v1()`，它会禁止新回调并等待其他线程中已经进入的回调
  完成；随后调用 `pdr_fastdds_subscription_destroy_v1()` 释放句柄。Runtime 的 `stop`/`destroy`
  也会先排空全部订阅。
- 取消订阅立即撤销插件回调，但底层 Fast DDS Reader 由既有 Runtime 统一拥有，只在 Runtime
  `stop`/`destroy` 时释放。频繁更换 Topic 的长期进程应在受控窗口重启该 ABI Runtime，避免
  累积已禁用 Reader。
- 允许在当前回调内部取消自身订阅；该调用禁止后续回调，但当前回调自然执行到返回。Runtime
  句柄本身不得在其回调内部销毁，也不得与其他 ABI 调用并发销毁；同一个订阅句柄的
  `unsubscribe` 与 `destroy` 也不得并发执行。

```cmake
find_package(PocoDDSRuntime CONFIG REQUIRED)
target_link_libraries(my_plugin PRIVATE PocoDDS::FastDDSAbiV1)
```

Windows 构建通过 `fastdds-abi-v1-exports` 将 DLL 精确锁定为十二个 C 符号；新增、删除或意外
导出任何符号都会失败。`fastdds-abi-v1-smoke` 验证创建、启动、订阅、发布、回调、停止和销毁
完整闭环，并证明取消订阅返回后新样本不再调用插件函数。`sdk-external-consumer` 还会使用只启用 C 语言的独立工程，从安装树配置、编译、链接
并运行该 ABI，阻止 `cxx_std_*` 或私有 C++ 类型泄漏到 target 接口。

## 迁移规则

新组件只允许依赖 `PocoDDS::FastDDSAbiV1`。既有 C++ ABI 在完成正式弃用公告、发布快照和主
版本迁移前继续保留；不得修改兼容性基线来掩盖自动导出漂移。将来需要不兼容变化时新增
`AbiV2.h`、`PDRFastDDSAbiV2` 和独立 CMake target，v1 按弃用策略并行保留。
