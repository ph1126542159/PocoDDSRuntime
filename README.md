# PocoDDSRuntime

A cross-platform C++17 runtime inspired by macchina.io OSP lifecycle concepts, designed for
multi-process applications and backend services using Fast-DDS and OpenTelemetry.

This repository is an independent clean architecture; it does not copy macchina.io web assets or
RemotingNG-generated code.

## Build

```powershell
cmake -S . -B build
cmake --build build --config Release --parallel 2
ctest --test-dir build -C Release --output-on-failure
```

Missing GoogleTest is fetched automatically. For the full native dependency prefix:

```powershell
cmake -S cmake -B build/dependencies -DPDR_SOURCE_DIR=$PWD
cmake --build build/dependencies --config Release --parallel 2
cmake -S . -B build -DPDR_ENABLE_FASTDDS=ON -DPDR_ENABLE_OPENTELEMETRY=ON
```

All third-party install artifacts are isolated under `build/install`; host and cross-compiled build
directories must never share that prefix.

Upstream Poco is detected as a package and otherwise built from the official
`poco-1.15.3-release` tag by the dependency superbuild. Poco source is not copied into this repository.
The optional Qt/OpenGL multi-process acceptance demo is enabled with
`-DPDR_BUILD_QT_OPENGL_DEMO=ON`.

See [architecture](docs/ARCHITECTURE.md) and [roadmap](docs/ROADMAP.md).
