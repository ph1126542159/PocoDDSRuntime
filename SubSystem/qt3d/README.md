# Qt3D 子进程架构测试

`pdr-qt3d-subprocess` 是独立于 `pdr-runtime` 的 Qt 6/Qt3D 业务进程。它创建并
显示一个旋转立方体，同时把“子进程启动 → 创建 Qt3D 场景”作为业务步骤发布到
`pdr.observability.span`，因此可以在业务追踪 WebUI 中按 Trace 查看进程 PID、
输入、输出和日志。

构建时给 CMake 指定 Qt 6，例如：

```powershell
cmake -S . -B build -DCMAKE_PREFIX_PATH=C:\Qt\6.8.2\msvc2022_64
cmake --build build --config Release --target pdr-qt3d-subprocess pdr-qt3d-multiprocess-test
ctest --test-dir build -C Release -R qt3d-multiprocess-business-trace --output-on-failure
```

要让主进程自动启动 Qt3D，在 `config/pdr-subprocesses.properties` 中启用：

```properties
subprocess.count = 1
subprocess.0.enabled = true
subprocess.0.name = qt3d
subprocess.0.path = processes/pdr-qt3d-subprocess/pdr-qt3d-subprocess.exe
subprocess.0.workingDirectory = processes/pdr-qt3d-subprocess
subprocess.0.argument.count = 1
subprocess.0.argument.0 = --instance=main-qt3d
```

CTest 会并行启动两个无窗口 Qt3D 实例，并确认协调进程和两个子进程 PID 不同、
两个子进程继承同一 W3C Trace ID 与同一业务实例 ID，且场景创建步骤成功。
