# CodeGeneration 组件

## 实现过程

`platform/CodeGeneration` 由 `CodeGenerator`、`CppGenerator`、`GeneratorEngine`、方法属性过滤器和工具函数组成。生成引擎读取代码模型和模板，再由 C++ 生成器输出目标文件。

## 用法

在 CMake 中链接 `Poco::CodeGeneration`，包含 `Poco/CodeGeneration/...` 头文件，配置生成器输入、输出目录及过滤规则后执行生成。生成文件应写入构建目录，避免无意覆盖人工维护的源码。

本项目不再生成 RemotingNG 的 RemoteObject、Skeleton、ServerHelper 或 EventDispatcher。

## 主要类

| 类 | 作用 |
| --- | --- |
| `CodeGenerator` | 生成器公共接口和 Properties |
| `CppGenerator` | C++ 输出规则 |
| `GeneratorEngine` | 遍历代码模型、选择模板并写入文件 |
| `MethodPropertyFilter` | 按方法属性过滤生成内容 |
| `Utility` | 名称和类型处理辅助函数 |

```cmake
target_link_libraries(my_generator PRIVATE Poco::CodeGeneration)
```

调用方准备代码模型和 `CodeGenerator::Properties`，再交给 GeneratorEngine。布尔、字符串、UInt32 属性通过引擎的严格解析工具读取。输出目录应设为构建树；需要纳入源码管理的生成结果应通过评审后单独复制。

该组件没有运行时 properties 配置，也不参与 `pdr-runtime` 启动；它是构建期工具库。
