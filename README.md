# PocoDDSRuntime

PocoDDSRuntime is a C++17 OSP service container derived from the macchina.io
composition model. OSP owns local Bundle lifecycle and service registration;
Fast DDS replaces the former RemotingNG cross-process proxy/skeleton layer.

PocoDDSRuntime 是面向复杂 C++ 应用的通用运行时框架，以多进程隔离、OSP Bundle 模块化和 Fast DDS 分布式通信为核心，支持桌面、边缘、设备控制及分布式服务系统快速构建。

The project deliberately does not contain RemotingNG-generated `RemoteObject`,
`Skeleton`, `ServerHelper` or `EventDispatcher` code.

## Experimental embodied robotics runtime

The `robotics-runtime` development branch adds a transport-neutral robot core
and a ROS 2 workspace without changing the stable legacy-runtime default. Use
the `robotics` CMake preset to build Lifecycle, Action, behavior orchestration,
simulation/hardware ports and fail-closed safety logic with Qt, WebUI, Poco/OSP
and direct Fast-DDS integrations disabled. See
[docs/architecture/robotics-runtime.md](docs/architecture/robotics-runtime.md).
The preset also builds `pdr-robot-sim`, a no-Qt deterministic local robot SIL
scenario that is included in CTest. `pdr-business-sim` provides replaceable
warehouse, inspection and pick/place workflows; run
`python robotics/tools/robotics_web_server.py --open-browser` to execute those
real C++ workflows from a local WebUI and inspect every node's parameters,
status, duration and logs. Each mission is also shown as an OpenTelemetry trace
with standard Trace/Span IDs, parentage, a timing waterfall, W3C `traceparent`
and optional OTLP/HTTP JSON export to a Collector.

## Directory layout

- `platform/` — migrated platform/runtime infrastructure:
  - `DDS`, `observability`, `CodeGeneration`, `Geo`, `OSP`, `Serial` and
    `WebTunnel`;
  - `protocols/` for BtLE, CAN, Modbus, MQTT, ROS Bridge, Serial, UDP,
    WebTunnel and XBee;
  - `devices/` for common device interfaces plus CAN, GNSS, Linux, Modbus,
    Serial, Simulation and XBeeSensor implementations.
- `services/` — independently packaged OSP Bundles: `DeviceGateway`,
  `UnitsOfMeasure`, `NetworkEnvironment`, `DeviceStatus`, `WebEvent` and
  `MobileConnection`.
- `SubSystem/` — subprocess implementations. It currently contains the
  `launcher/` watchdog/service wrapper that starts and relaunches `pdr-runtime`;
  the launcher is intentionally separate from the OSP server process.
- `server/` — `MacchinaServer.cpp`, the single process entry point.
- `webui/` — embedded runtime administration UI and REST API for processes,
  services, modules, Bundles, configuration, logs and lifecycle operations.
- `cmake/` — third-party discovery, download/build/install superbuild and
  compatibility patches.
- `scripts/` — Linux host and PetaLinux SDK build entry points.
- `config/` — runtime configuration.
- `build/` — all generated dependency, native, cross and install trees.

## Communication boundary

Fast DDS replaces RemotingNG only for communication between processes or
machines. It does not replace physical/device protocols such as CAN, Modbus,
MQTT, serial, XBee or Bluetooth.

The device gateway uses:

- `pdr.device.state`
- `pdr.device.request`
- `pdr.device.response`

Migrated services use:

| Service | Request | Response | Event |
| --- | --- | --- | --- |
| UnitsOfMeasure | `pdr.units.request` | `pdr.units.response` | — |
| NetworkEnvironment | `pdr.network.request` | `pdr.network.response` | `pdr.network.environment` |
| DeviceStatus | `pdr.status.request` | `pdr.status.response` | `pdr.device.status` |
| WebEvent | `pdr.web.request` | `pdr.web.response` | `pdr.web.event` |
| MobileConnection | `pdr.mobile.request` | `pdr.mobile.response` | `pdr.mobile.state` |

OSP remains responsible for local Bundle startup, shutdown, reload and service
registry ownership.

## OpenTelemetry business tracing

Business tracing is optional (`-DPDR_ENABLE_OBSERVABILITY=ON`). Applications use
`BusinessTracer::startBusiness()` and `BusinessSpan::startStep()` to record the
business flow, sanitized input/output fields, success or failure, duration and
step logs. W3C trace context is carried in the Fast DDS Envelope, and completed
or running span snapshots are aggregated over `pdr.observability.span`.

The administration WebUI contains a **业务追踪** page that renders each trace as
a clickable flow graph. See [docs/BUSINESS_TRACING.md](docs/BUSINESS_TRACING.md)
for the API, cross-process propagation and data-safety rules.

The same observability module provides OpenTelemetry Metrics for Runtime, DDS,
devices, workflows, protocols, HTTP and host resources. Metrics are available
through `/api/v1/metrics`, summarized on the Home WebUI, and optionally exported
to an OTLP/HTTP Collector. See [docs/METRICS.md](docs/METRICS.md).

## Third-party dependencies

Third-party sources are not copied into the repository. The superbuild pins and
installs:

- Poco 1.15.3
- Fast DDS 3.6.2 and its Fast-CDR/foonathan dependencies
- Eclipse Paho MQTT C 1.3.15

OpenTelemetry business tracing and GoogleTest remain optional:

```powershell
cmake -S cmake -B build/dependencies `
  -DPDR_BUILD_GOOGLETEST=ON
```

Offline or restricted-network builds can provide:

- `PDR_POCO_ARCHIVE`
- `PDR_FASTDDS_SOURCE_DIR`
- `PDR_FASTCDR_SOURCE_DIR`
- `PDR_FOONATHAN_MEMORY_SOURCE_DIR`
- `PDR_PAHO_MQTT_SOURCE_DIR`

Dependencies and PocoDDSRuntime are installed into one prefix per target
architecture. On a normal Windows build that single prefix is `build/install`.

## Public SDK and developer CLI

Installed applications consume the stable foundation through one CMake target:

```cmake
find_package(PocoDDSRuntime 0.1 CONFIG REQUIRED COMPONENTS SDK)
target_link_libraries(my_application PRIVATE PocoDDS::SDK)
```

省略 `COMPONENTS` 与请求 `SDK` 等价，保留已有项目兼容性；基础 SDK 不会查找 Paho MQTT。

`PocoDDS::SDK` exposes Application, DeviceCore, typed configuration, shared identity,
reliability, health, persistence and SDK version APIs without requiring business code to include
Fast DDS, Qt, OSP or OpenTelemetry implementation headers. The
`sdk-external-consumer` test installs the framework and builds a separate CMake
project against that installed package.

Protocol applications can link one protocol or the complete installed protocol SDK:

```cmake
find_package(PocoDDSRuntime 0.1 CONFIG REQUIRED COMPONENTS SDK MQTT UDP)
target_link_libraries(my_application PRIVATE PocoDDS::MQTT PocoDDS::UDP)
# Or, when the product genuinely uses the complete protocol set:
find_package(PocoDDSRuntime 0.1 CONFIG REQUIRED COMPONENTS SDK Protocols)
target_link_libraries(my_application PRIVATE PocoDDS::Protocols)
```

The package exports `BtLE`, `CAN`, `Modbus`, `MQTT`, `ROS`, `SerialProtocol`,
`UDP`, `WebTunnelProtocol` and `XBee` targets with their transitive dependencies.
The external-consumer test compiles protocol headers and links the aggregate target
from an isolated install tree.

Deployable OSP plugins use the installed `Plugins` component and packaging helper:

```cmake
find_package(PocoDDSRuntime CONFIG REQUIRED COMPONENTS Plugins)
pdr_add_osp_bundle(MyPlugin SYMBOLIC_NAME pdr.plugin.myplugin
  BUNDLE_SPEC MyPlugin.bndlspec SOURCES src/BundleActivator.cpp)
```

External code links `PocoDDS::Plugins`, not the internal OSP target. The generated
versioned `.bndl` is covered by an external build, package and isolated Runtime-load gate.

Use the developer command to check the environment or create a standard module:

```powershell
./tools/pdr.ps1 doctor --prefix build/install `
  --report build/reports/developer-doctor.json
./tools/pdr.ps1 validate-config config/pdr-runtime.properties `
  --prefix build/install --report build/reports/config-validation.json
./tools/pdr.ps1 new service TemperatureService --output services
./tools/pdr.ps1 new device CanTemperatureSensor --output platform/devices
./tools/pdr.ps1 new workflow BoardPowerOnTest --output application/workflows
./tools/pdr.ps1 new plugin AcmeDiagnostics --output plugins
./tools/pdr.ps1 verify platform/devices/CanTemperatureSensor `
  --prefix build/install --config Release `
  --report build/reports/can-temperature-sensor-verify.json
./tools/pdr.ps1 verify plugins/AcmeDiagnostics --prefix build/install `
  --config Release --artifact-output build/plugin-dist `
  --report build/reports/acme-diagnostics-verify.json
```

Generated modules contain a public header, implementation, CMake target, smoke
test and integration README. Existing non-empty output directories are never
overwritten unless `--force` is explicitly supplied.
The device template implements the real `PocoDDS::Devices::Device` lifecycle,
snapshot and command interfaces and includes indexed multi-instance configuration.
`pdr doctor` validates the selected installed SDK prefix, exported `PocoDDS::SDK`
target, Poco package, Python, CMake and CTest. Failed checks include actionable
remedies, and the optional JSON report can be attached to CI or support evidence.
Split SDK deployments use `--prefix` for PocoDDSRuntime and
`--dependency-prefix` for the Poco development package.
`pdr validate-config` uses the same C++ validator as Runtime to check layered base
and site configuration without starting OSP, protocols, listeners or subprocesses.
`pdr identity inspect` reports non-secret identity-source and token-file permission evidence;
`pdr identity check` is the production gate and fails unless authentication is required,
at least one file-backed principal exists, every permission check completes and no broad
ACL/mode is detected.
`pdr persistence inspect` validates Runtime management snapshots and their verified
`.previous` recovery material. `pdr persistence recover` performs hash-bound,
audited offline recovery while preserving the original current file for forensics.
`pdr persistence backup` atomically publishes a stopped-Runtime recovery point for
configuration, task, idempotency and audit state; `verify-recovery-point` validates
its manifest and every artifact independently before transfer or restore drills.
`restore-recovery-point` archives the complete destination state, stages every
artifact, performs a rollback-capable replacement transaction and records the
operation in an external audit stream.
`validate-restored-runtime` binds that transaction to live health and management
inventory evidence, requires explicit dispositions for interrupted operations and
emits the authoritative management-write `APPROVED` or `DENIED` verdict.
Runtime smoke now requires graceful shutdown with exit code zero and records the
shutdown mode and duration. Forced termination is opt-in and reserved for explicit
crash-recovery evidence.
The legacy `/webevent` WebSocket is protected by the OSP Web dispatcher and rejects
anonymous clients before constructing its request handler.
`PocoDDS::Security::ReloadablePrincipalStore` supplies the same environment- or file-backed identities
to management APIs and the built-in OSP AuthService/TokenValidator bridge.
`pdr upgrade apply` verifies the release manifest, compatibility and disk capacity,
requires a trusted detached Ed25519 (or compatibility HMAC-SHA256) manifest signature for production use,
uses an exclusive lock plus durable transaction journal, preserves mutable Runtime
state, discards stale code cache, and requires a post-activation health gate.
Transient Windows sharing violations during directory activation or rollback use a
bounded, audited rename retry window instead of an unbounded wait.
Failed health checks restore and hash-verify the old release. `pdr upgrade recover`
reconciles interrupted directory switches fail-closed, while manual rollback carries
the latest mutable state back to the prior binaries.
The install tree includes `bin/pdr.py`, `bin/pdr.ps1`, `bin/pdr-config-check`,
`bin/release_manifest.py`, `bin/upgrade_manager.py`, Runtime smoke, soak, device
acceptance, protocol acceptance and security-gate tools;
the installed CLI automatically uses its own package root as the default prefix.
`pdr verify` consumes the installed SDK, then configures, builds and runs CTest in
an isolated temporary directory. Its optional JSON report retains commands, exit
codes and output without leaving build artifacts beside the generated source. For a
plugin, verification also requires a real `.bndl`, records its SHA-256 and can copy
the verified artifact with `--artifact-output`.

Stopped-Runtime plugin publication is handled by `pdr plugin preflight/install/recover/rollback`.
Installation requires an approved SHA-256 and explicit `--confirm-runtime-stopped`, rejects unsafe
archives, incompatible `Require-Bundle` ranges, or mismatched plugin API/ABI/runtime contracts,
atomically publishes the artifact, retains the
previous version under `bin/plugin-backups`, and writes a durable JSONL audit trail. Rollback is
guarded by both the current and backup digests. `recover` reconciles a durable interrupted-install
journal while the Runtime remains stopped. Runtime startup and the Web plugin-governance page remain
the post-publication acceptance boundary.
Production plugin preflight also requires a detached Ed25519 publisher attestation governed by a
pinned plugin trust policy with symbolic-name scopes, validity windows, and revocation. An explicit
unsigned diagnostic bypass is recorded in both the report and audit trail.

Development builds may generate release evidence from a dirty worktree, and the
manifest records `cleanRequired: false` plus the actual `dirty` state. A governed
production release must use the `release` presets; its release-artifact test
refuses to generate a manifest unless the Git worktree is clean:

```powershell
cmake --preset release
cmake --build --preset release
ctest --preset release
```

## Windows build

With Visual Studio 2022:

```powershell
cmake -S cmake -B build/dependencies -G "Visual Studio 17 2022" -A x64 `
  -DPDR_DEPENDENCY_INSTALL_PREFIX="$PWD/build/install"
cmake --build build/dependencies --config Release --parallel 2

cmake -S . -B build -G "Visual Studio 17 2022" -A x64
cmake --build build --config Release --parallel 2
ctest --test-dir build -C Release --output-on-failure
cmake --install build --config Release
```

Start the build-tree runtime:

```powershell
Set-Location build/bin
./pdr-runtime.exe
```

### Web 登录信息

启动后访问 <http://127.0.0.1:9080/>，程序会跳转到登录页面。

| 登录项 | 当前值 |
| --- | --- |
| 用户名 | `admin` |
| 密码 | `admin` |

该默认凭据仅用于绑定在 `127.0.0.1` 的本地管理页面。当前
`osp.web.authServiceName` 为空且 `auth.simple.enable = false`，因此它不是远程部署
所需的服务端安全边界；开放到其他网卡前必须接入服务端认证并更换凭据。

Other long-running executables are placed below the shared subprocess root:

```text
build/bin/
├─ pdr-runtime.exe
├─ pdr-runtime.properties
├─ pdr-subprocesses.properties
├─ logs/
├─ bundles/
└─ processes/
   └─ pdr-launcher/
      ├─ pdr-launcher.exe
      ├─ pdr-launcher.properties
      ├─ logs/
      └─ bundles/
```

`PDRBundleManagement.dll` monitors the owning process's `bundles/` directory.
After a changed directory snapshot remains stable across two scans, it performs
the complete OSP lifecycle: stop, unload, repository reload, dependency
resolution and start. This handles added, atomically replaced and deleted
Bundle packages without loading partially copied files.

`pdr-runtime` reads `pdr-subprocesses.properties` after its own initialization
and starts enabled subprocess entries in ascending numeric order. Executable
paths and optional working directories are relative to `build/bin/`. On startup
failure, already-started children are stopped. Normal shutdown stops children in
reverse order.

```properties
subprocess.count = 1
subprocess.0.enabled = true
subprocess.0.name = worker
subprocess.0.path = processes/worker/worker.exe
subprocess.0.workingDirectory = processes/worker
subprocess.0.argument.count = 1
subprocess.0.argument.0 = --config=worker.properties
```

`pdr-launcher` remains available below `processes/`, but it is not enabled in
the default child-process configuration because its watchdog role is to launch
another command; configuring it to launch `pdr-runtime` from `pdr-runtime`
would create a parent/child cycle.

Poco uses `/option=value` syntax on Windows and `--option=value` on Unix.

## Linux host build

```bash
./scripts/bootstrap-cmake.sh
./scripts/build-host.sh
cd build/host-install/bin
./pdr-runtime --config-file=../etc/pdr-runtime.properties
```

The script keeps separate build trees but installs both dependencies and the
runtime into the single `build/host-install` prefix.

## PetaLinux SDK build

The default SDK environment is
`/data/petalinux/bin/petalinux-sdk-env.sh`. Override it with
`PDR_PETALINUX_SDK_ENV`. The Bundle creator is executed through qemu-aarch64;
override its location with `MYIOT_QEMU_ARM`.

```bash
./scripts/bootstrap-cmake.sh
./scripts/build-petalinux.sh
```

Target dependencies and runtime artifacts are both installed under the single
`build/petalinux-install` prefix. It never reuses the host prefix.

## Runtime devices

The portable default configuration enables only `simulation-1`. Physical
backends are opt-in in `config/pdr-runtime.properties`:

- `pdr.modbus.*`
- `pdr.serial.*`
- `pdr.gnss.*`
- `pdr.gpio.*`
- `pdr.led.*`
- `pdr.xbee.*`
- `pdr.can.*`

The installed process layout is:

```text
bin/
├─ pdr-runtime
├─ pdr-runtime.properties
├─ pdr-subprocesses.properties
├─ bundles/
│  ├─ osp.core_1.7.0.bndl
│  ├─ poco.net_1.11.6.bndl
│  ├─ pdr.device.gateway_0.1.0.bndl
│  ├─ pdr.service.units_1.0.0.bndl
│  ├─ pdr.service.network_1.0.0.bndl
│  ├─ pdr.service.deviceStatus_1.0.0.bndl
│  ├─ pdr.service.webEvent_1.0.0.bndl
│  └─ pdr.service.mobile_1.0.0.bndl
└─ processes/
   └─ pdr-launcher/
      ├─ pdr-launcher
      └─ pdr-launcher.properties
include/Poco/
include/fastdds/
include/fastcdr/
lib/PocoFoundation...
lib/fastdds...
lib/cmake/Poco/
lib/cmake/fastdds/
include/
lib/
```
