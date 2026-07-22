# Completion acceptance matrix

The framework is complete only when every gate below has executable evidence.

| Area | Required evidence | Current state |
|---|---|---|
| Core lifecycle | GoogleTest covers install/start/stop/uninstall and dependency order | Partial |
| Process supervisor | Real child start, heartbeat/exit observation, bounded restart and shutdown | Core passed; DDS heartbeat integration pending |
| Configuration | Atomic multi-key apply, validation, observer notification and rollback | Core passed; admin API integration pending |
| Fast-DDS | Two processes discover and exchange typed data using SHM on one host | Windows passed, 14-test suite |
| Cross-host DDS | Two hosts exchange with non-SHM transport and retain trace context | Network-only loopback passed; two-host evidence pending |
| OpenTelemetry | One business trace crosses processes and correlates spans and logs in OTLP backend | Missing |
| Bundle loading | Shared library install/resolve/start/stop/unload and atomic replacement | Missing |
| Admin plane | Authenticated topology, logs, config, lifecycle and trace APIs plus UI | Missing |
| Qt/OpenGL demo | Embedded/rendered child, DDS control, trace, crash/restart and cleanup | Partial |
| Portability | Windows, Linux and macOS CI plus platform-specific integration evidence | Missing |
