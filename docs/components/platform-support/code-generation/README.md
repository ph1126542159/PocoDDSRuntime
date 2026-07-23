# CodeGeneration 组件

## 实现过程

`platform/CodeGeneration` 由 `CodeGenerator`、`CppGenerator`、`GeneratorEngine`、方法属性过滤器和工具函数组成。生成引擎读取代码模型和模板，再由 C++ 生成器输出目标文件。

## 用法

在 CMake 中链接 `Poco::CodeGeneration`，包含 `Poco/CodeGeneration/...` 头文件，配置生成器输入、输出目录及过滤规则后执行生成。生成文件应写入构建目录，避免无意覆盖人工维护的源码。

本项目不再生成 RemotingNG 的 RemoteObject、Skeleton、ServerHelper 或 EventDispatcher。
