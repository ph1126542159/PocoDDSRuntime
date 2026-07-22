# Completion acceptance matrix

The framework is complete only when every gate below has executable evidence.

| Area | Required evidence | Current state |
|---|---|---|
| Core lifecycle | GoogleTest covers install/start/stop/uninstall and dependency order | Bundle lifecycle, registry states and dependency ordering passed |
| Process supervisor | Real child start, heartbeat/exit observation, bounded restart and shutdown | Core passed; DDS discovery lease passed |
| Configuration | Atomic multi-key apply, validation, observer notification and rollback | HTTP-to-DDS remote apply, revision conflict and rollback passed |
| Fast-DDS | Two processes discover and exchange typed data using SHM on one host | Windows passed, 22-test suite plus 10x transport repeat |
| Cross-host DDS | Two hosts exchange with non-SHM transport and retain trace context | Network-only loopback passed; two-host evidence pending |
| OpenTelemetry | One business trace crosses processes and correlates spans and logs in OTLP backend | Official Collector 0.157.0 accepted two real Qt host/child traces; parent/child IDs, inputs, outputs, status and logs verified through its debug and file exporters |
| Bundle loading | Shared library install/resolve/start/stop/unload and atomic replacement | Runtime watcher and admin install/stop/restart/uninstall/reinstall passed with real DLL |
| Admin plane | Authenticated topology, logs, config, lifecycle and trace APIs plus UI | Real runtime discovers and controls remote process over DDS; durable storage and RBAC pending |
| Qt/OpenGL demo | Embedded/rendered child, DDS control, trace, crash/restart and cleanup | Automated DDS render, W3C Trace ID continuity, changed PID after crash/restart, second render and cleanup passed; visual compositor embedding remains a manual platform gate |
| Portability | Windows, Linux and macOS CI plus platform-specific integration evidence | Windows, Linux and macOS core jobs passed; Linux clean dependency bootstrap, full-stack build and Qt acceptance suite passed in GitHub Actions run 29912246747 |
