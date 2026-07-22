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

## Phase 3 - observability and administration

- OpenTelemetry SDK wrapper, W3C propagation, OTLP export and trace/log correlation.
- Authenticated loopback-by-default admin API and hidden SPA.
- Topology, logs, atomic configuration, lifecycle control and trace DAG views.
- Use an external observability backend (OpenTelemetry Collector plus Tempo/Jaeger and Loki) for
  durable storage; the framework UI queries it instead of inventing a trace database.

## Phase 4 - application adapters

- Promote the Qt/OpenGL multi-process demo from native-surface smoke test to a full acceptance test:
  discovery, child restart, DDS command/frame exchange, trace continuity and fault injection.
- Qt host and child-process SDK, with Windows/Linux/macOS embedding adapters.
- OpenGL offscreen/shared-texture option for robust cross-process 3D composition.
- Headless service templates, packaging, fault injection and multi-host acceptance tests.
