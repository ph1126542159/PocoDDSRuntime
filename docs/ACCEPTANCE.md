# Completion acceptance matrix

The framework is complete only when every gate below has executable evidence.

| Area | Required evidence | Current state |
|---|---|---|
| Core lifecycle | GoogleTest covers install/start/stop/uninstall and dependency order | Bundle lifecycle, registry states and dependency ordering passed |
| Process supervisor | Real child start, heartbeat/exit observation, bounded restart and shutdown | Core passed; DDS discovery lease passed |
| Configuration | Atomic multi-key apply, validation, observer notification and rollback | HTTP-to-DDS remote apply, revision conflict and rollback passed |
| Fast-DDS | Two processes discover and exchange typed data using SHM on one host | Windows passed, 22-test suite plus 10x transport repeat |
| Cross-host DDS | Two hosts exchange with non-SHM transport and retain trace context | Network-only loopback passed; two-host evidence pending |
| OpenTelemetry | One business trace crosses processes and correlates spans and logs in OTLP backend | SDK/W3C and OTLP HTTP receiver passed with business fields/logs; durable Collector backend and real-process evidence pending |
| Bundle loading | Shared library install/resolve/start/stop/unload and atomic replacement | Runtime watcher and admin install/stop/restart/uninstall/reinstall passed with real DLL |
| Admin plane | Authenticated topology, logs, config, lifecycle and trace APIs plus UI | Real runtime discovers and controls remote process over DDS; durable storage and RBAC pending |
| Qt/OpenGL demo | Embedded/rendered child, DDS control, trace, crash/restart and cleanup | Partial |
| Portability | Windows, Linux and macOS CI plus platform-specific integration evidence | Missing |
