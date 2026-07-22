# Qt/OpenGL multi-process acceptance demo

This optional demo is a framework acceptance target, not a reusable business module. The host starts
and supervises a separate OpenGL child process, receives its native surface identifier and attempts
to embed that surface in the main window.

Enable with `-DPDR_BUILD_QT_OPENGL_DEMO=ON` and a Qt 6.5+ installation. Native foreign-window
embedding depends on the Qt platform plugin and window system. A later acceptance stage adds DDS
surface negotiation, heartbeat/restart, OpenTelemetry trace continuity and an offscreen/shared-texture
fallback for platforms where native embedding is unavailable.

Current Windows acceptance evidence requires both `pdr-qt-opengl-host` and
`pdr-qt-opengl-child` to remain responsive after startup. Visual embedding, DDS exchange,
restart recovery and OpenTelemetry span continuity are separate gates and must not be inferred from
the startup check.
