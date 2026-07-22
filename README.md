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
cmake -S . -B build -DPDR_ENABLE_FASTDDS=ON -DPDR_ENABLE_OPENTELEMETRY=ON `
  -DPDR_ENABLE_ADMIN=ON
```

All third-party install artifacts are isolated under `build/install`; host and cross-compiled build
directories must never share that prefix.

Upstream Poco is detected as a package and otherwise built from the official
`poco-1.15.3-release` tag by the dependency superbuild. Poco source is not copied into this repository.
The optional Qt/OpenGL multi-process acceptance demo is enabled with
`-DPDR_BUILD_QT_OPENGL_DEMO=ON`.

To build and verify the real Fast-DDS adapter after the dependency superbuild:

```powershell
cmake -S . -B build-fastdds -DCMAKE_BUILD_TYPE=Release `
  -DPDR_INSTALL_PREFIX="$PWD/build-deps/install" -DPDR_ENABLE_FASTDDS=ON
cmake --build build-fastdds --parallel 2
ctest --test-dir build-fastdds --output-on-failure
```

The acceptance suite launches independent publisher and subscriber processes twice: once with only
Fast-DDS shared memory enabled and once with only UDP enabled.

## Local administration

The administration plane binds to `127.0.0.1:9080` by default. API access requires a bearer token
of at least 16 characters; the HTML shell contains no runtime data and prompts for the token locally.

```powershell
$env:PDR_ADMIN_TOKEN = "replace-with-a-random-32-byte-token"
$env:PDR_ADMIN_BIND = "127.0.0.1"
$env:PDR_ADMIN_PORT = "9080"
build-fastdds/apps/pdr-runtime.exe
```

Open `http://127.0.0.1:9080/` to inspect topology and logs, apply live configuration, issue lifecycle
commands and inspect trace graphs. Binding to a non-loopback interface should only be done behind TLS
and an authenticated reverse proxy. `PDR_RUN_SECONDS` provides a bounded runtime for CI smoke tests.

See [architecture](docs/ARCHITECTURE.md) and [roadmap](docs/ROADMAP.md).
