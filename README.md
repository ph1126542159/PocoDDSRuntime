# PocoDDSRuntime

PocoDDSRuntime is a C++17 OSP service container derived from the macchina.io
composition model. OSP owns local Bundle lifecycle and service registration;
Fast DDS replaces the former RemotingNG cross-process proxy/skeleton layer.

PocoDDSRuntime 是面向复杂 C++ 应用的通用运行时框架，以多进程隔离、OSP Bundle 模块化和 Fast DDS 分布式通信为核心，支持桌面、边缘、设备控制及分布式服务系统快速构建。

The project deliberately does not contain RemotingNG-generated `RemoteObject`,
`Skeleton`, `ServerHelper` or `EventDispatcher` code.

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
