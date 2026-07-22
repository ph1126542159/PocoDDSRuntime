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

Upstream Poco is never vendored. CMake first searches the build-local prefix and the system, while
the dependency superbuild obtains the pinned current Poco release when it is missing. Framework-only
OSP and contract-generation code lives under `framework/` and remains separate from upstream Poco.

## Discovery and data path

Fast-DDS participant discovery identifies processes and endpoints. A retained component-manifest
topic describes services, bundles, versions, health and control capabilities. Fast-DDS transport
descriptors enable shared memory and UDP; same-host endpoints prefer shared memory while remote
participants use UDP. Security, stable domain IDs, topic ACLs and schema compatibility are mandatory
for production deployments.

Automatic discovery does not remove the need for an interface contract. Every business topic must
have a versioned IDL/schema, QoS profile and ownership definition.

## Desktop child windows

The `QtOpenGLMultiProcess` acceptance demo exercises this boundary. Qt child processes must render
into a platform-supported embedding surface or use streamed/offscreen
rendering. Native window re-parenting is platform-specific and not a cross-platform framework
contract. The reusable contract is process lifecycle + surface handle negotiation + input/resize
events; each OS/graphics backend supplies its own adapter.
