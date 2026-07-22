# Completion acceptance matrix

The framework is complete only when every gate below has executable evidence.

| Area | Required evidence | Current state |
|---|---|---|
| Core lifecycle | GoogleTest covers install/start/stop/uninstall and dependency order | Partial |
| Process supervisor | Real child start, heartbeat/exit observation, bounded restart and shutdown | Core passed; DDS discovery lease passed |
| Configuration | Atomic multi-key apply, validation, observer notification and rollback | DDS command agent and authenticated HTTP live apply passed |
| Fast-DDS | Two processes discover and exchange typed data using SHM on one host | Windows passed, 22-test suite plus 10x transport repeat |
| Cross-host DDS | Two hosts exchange with non-SHM transport and retain trace context | Network-only loopback passed; two-host evidence pending |
| OpenTelemetry | One business trace crosses processes and correlates spans and logs in OTLP backend | SDK/W3C and OTLP HTTP receiver passed with business fields/logs; durable Collector backend and real-process evidence pending |
| Bundle loading | Shared library install/resolve/start/stop/unload and atomic replacement | ABI/load/start/replace/unload passed with real DLL; dependency-aware file watcher pending |
| Admin plane | Authenticated topology, logs, config, lifecycle and trace APIs plus UI | Loopback HTTP/API/UI and runtime-process smoke passed; durable storage and RBAC pending |
| Qt/OpenGL demo | Embedded/rendered child, DDS control, trace, crash/restart and cleanup | Partial |
| Portability | Windows, Linux and macOS CI plus platform-specific integration evidence | Missing |
