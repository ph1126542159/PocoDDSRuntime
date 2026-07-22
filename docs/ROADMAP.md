# Delivery roadmap

## Phase 1 - executable foundation

- Core component registry and bundle lifecycle.
- Transport abstraction and deterministic in-memory implementation.
- Build-local dependency bootstrap and GoogleTest baseline.

## Phase 2 - distributed runtime

- Fast-DDS generated types for manifests, heartbeat, lifecycle command and config transaction.
- Shared-memory-first transport profile and cross-host UDP profile.
- Supervisor with crash loop protection, dependency ordering and graceful shutdown.
- Dynamic library bundle loader with ABI/API version checks.

Implemented core evidence includes native Windows/POSIX launchers, bounded crash restart, heartbeat
timeout restart, controlled termination and transactional configuration rollback. Distributed
heartbeats and admin-driven configuration are covered by the Fast-DDS control plane acceptance tests.

The generic Fast-DDS wire transport now has real two-process SHM-only and UDP-only acceptance on
Windows, including payload and W3C trace-context verification. A physical two-host acceptance run is
still required.

Component manifests, discovery leases, configuration transactions, lifecycle commands and correlated
results are now implemented as versioned control contracts. The SHM and UDP two-process probes verify
component discovery as well as payload delivery. A READY handshake prevents stale SHM discovery state
from causing the first volatile control sample to be sent before the live peer is ready.

The bundle runtime now loads native shared libraries through a versioned C ABI, runs the complete
lifecycle, validates a replacement before switching, rolls back a failed replacement start and unloads
the old library. The Windows loader uses a same-directory shadow copy so a running deployment DLL can
be overwritten. A runtime-process acceptance test verifies directory install, admin stop/restart,
uninstall suppression and file-change reinstall. Dependency-ordered multi-bundle batch updates remain
open.

## Phase 3 - observability and administration

- OpenTelemetry SDK wrapper, W3C propagation, OTLP export and trace/log correlation.
- Authenticated loopback-by-default admin API and hidden SPA.
- Topology, logs, atomic configuration, lifecycle control and trace DAG views.
- Use an external observability backend (OpenTelemetry Collector plus Tempo/Jaeger and Loki) for
  durable storage; the framework UI queries it instead of inventing a trace database.

The official OpenTelemetry C++ SDK is now built by the dependency superbuild. `BusinessTracer` and
`BusinessSpan` add W3C propagation, input/output attributes, outcome, duration and correlated log
events. GoogleTest proves parent-child continuity between independent service tracer providers. A
local HTTP fixture verifies OTLP/HTTP JSON structure, IDs, resource identity, business fields, log
events and authentication headers. The official OpenTelemetry Collector 0.157.0 has also accepted a
real Qt host/child trace with verified parentage, business data and correlated logs. Durable Collector
storage remains an optional deployment integration.

The loopback administration plane now provides bearer-authenticated topology, configuration,
lifecycle, log and trace APIs plus an embedded SPA with a trace graph. Real TCP GoogleTests cover
authorization and every API family; a launched `pdr-runtime` process also passes topology, live config
and restart smoke checks. DDS routing to remote owners is implemented through correlated
`ControlPlaneClient` requests. The
acceptance suite launches the real runtime and a remote worker and validates HTTP-to-DDS configuration
and restart. Durable storage, role-based authorization and TLS deployment remain open.

## Phase 4 - application adapters

- Qt/OpenGL multi-process acceptance: discovery, child restart, DDS command/frame exchange, trace
  continuity and fault injection. Automated headless acceptance and Windows native parent/child
  window relationship verification are complete.
- Installable CMake SDK with exported core, OSP, CodeGeneration, Fast-DDS, observability and admin
  targets, plus an outside-tree consumer acceptance fixture.
- Qt host and child-process SDK, with native-surface embedding adapters.
- OpenGL offscreen/shared-texture option for robust cross-process 3D composition.
- Headless service templates, packaging, fault injection and multi-host acceptance tests.
