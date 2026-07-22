# PocoDDSRuntime architecture

PocoDDSRuntime retains macchina.io's useful OSP concepts (bundle, activator, service registry and
controlled lifecycle) without inheriting RemotingNG's generated proxy/skeleton/ORB coupling.

## Layers

1. **Core** owns components, bundles, services, configuration, tasks and lifecycle state. It has no
   dependency on Fast-DDS, Qt, OpenGL or HTTP.
2. **Transport** defines typed publish/subscribe and request/reply conventions. The in-memory
   transport supports deterministic tests; Fast-DDS is the production adapter.
3. **Observability** injects/extracts W3C trace context into every transport envelope and exports
   traces, metrics and logs through OpenTelemetry OTLP.
4. **Supervisor** starts child processes, observes heartbeats and applies restart policy. Processes
   publish component manifests and health samples through built-in discovery topics.
5. **Bundle runtime** installs, resolves, starts, stops and uninstalls modules. In-process bundles are
   shared libraries; isolated bundles run in supervised child processes and use the same DDS API.
6. **Admin plane** is a separately bindable, authenticated HTTP service. Its UI consumes only admin
   APIs for topology, live configuration, logs, lifecycle actions and trace graphs.
7. **Application adapters** integrate Qt, OpenGL or headless services without leaking those
   dependencies into Core.

The current administration implementation is split into `AdminService`, which owns bounded topology,
log and trace query/control behavior, and `AdminHttpServer`, which exposes the behavior through Poco
Net. It binds to loopback by default, rejects short tokens, compares bearer credentials without an
early exit, limits request bodies and emits anti-framing/content-type headers. The embedded SPA has no
external assets and all data/control endpoints require authentication.

Observability uses the official OpenTelemetry SDK for span creation and processing. The optional
OTLP/HTTP JSON exporter serializes standard `resourceSpans`, `scopeSpans`, Base64 trace/span IDs,
nanosecond timestamps, attributes, events and status to `/v1/traces`. It targets a local or sidecar
Collector over HTTP; production TLS, buffering and retry policy belong at the Collector boundary.

Upstream Poco is never vendored. CMake first searches the build-local prefix and the system, while
the dependency superbuild obtains the pinned current Poco release when it is missing. Framework-only
OSP and contract-generation code lives under `framework/` and remains separate from upstream Poco.

## Discovery and data path

Fast-DDS participant discovery identifies processes and endpoints. A retained component-manifest
topic describes services, bundles, versions, health and control capabilities. Fast-DDS transport
descriptors enable shared memory and UDP; same-host endpoints prefer shared memory while remote
participants use UDP. Security, stable domain IDs, topic ACLs and schema compatibility are mandatory
for production deployments.

`FastDDSTransport` uses a versioned `PocoDDS.Wire.v1` envelope and exposes three explicit modes:
automatic SHM+UDP, SHM-only and network-only UDP. Acceptance runs SHM-only and network-only in two
independent processes, so a passing SHM test cannot silently fall back to loopback UDP. Logical topic,
payload type and W3C trace context are serialized in the envelope. Production IDL contracts remain
the authority for each business payload carried inside it.

Automatic discovery does not remove the need for an interface contract. Every business topic must
have a versioned IDL/schema, QoS profile and ownership definition.

The control plane uses versioned binary contracts for component manifests, configuration
transactions, lifecycle commands and command results. `DiscoveryAgent` broadcasts leased component
manifests and removes expired remote entries. `ControlPlaneAgent` applies validated configuration
transactions immediately, rejects stale revisions without partial changes, executes lifecycle
handlers and returns correlated results while preserving the incoming trace context.

`ControlPlaneClient` is the matching request side. It creates unique correlation IDs, tracks
concurrent pending commands, enforces response deadlines and ignores unrelated or malformed results.
The runtime administration service uses it for targeted remote configuration and lifecycle actions;
local runtime configuration remains an atomic direct path. A process-level acceptance test launches a
runtime and a remote worker, waits for DDS discovery, then drives configuration and restart through the
HTTP API and verifies the remote result revision.

Acceptance uses an application-level READY handshake before publishing volatile control data. A DDS
matched count alone is not treated as liveness because stale shared-memory endpoints can remain
visible briefly after an abruptly terminated process.

## Desktop child windows

The `QtOpenGLMultiProcess` acceptance demo exercises this boundary. Qt child processes must render
into a platform-supported embedding surface or use streamed/offscreen
rendering. Native window re-parenting is platform-specific and not a cross-platform framework
contract. The reusable contract is process lifecycle + surface handle negotiation + input/resize
events; each OS/graphics backend supplies its own adapter.
