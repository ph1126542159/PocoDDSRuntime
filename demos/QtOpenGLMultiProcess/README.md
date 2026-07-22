# Qt/OpenGL multi-process acceptance demo

This optional demo is a framework acceptance target and an example project layer. The host uses the
framework supervisor to start and restart a separate OpenGL child process. The processes discover
one another through Fast-DDS, exchange traced render commands, and use the child's native surface
identifier to embed it in the main window when the window system supports foreign windows.

Enable with `-DPDR_BUILD_QT_OPENGL_DEMO=ON` and a Qt 6.5+ installation. Native foreign-window
embedding depends on the Qt platform plugin and window system. DDS surface negotiation, render
control, W3C trace continuity, deliberate child failure and bounded automatic restart are implemented.
The example keeps those lifecycle and messaging responsibilities below the Qt project layer.

With tests enabled, `QtOpenGLMultiProcessAcceptance` runs headlessly. It requires a successful render,
matching parent/child Trace IDs, a changed child PID after fault injection, and a second successful
render. The visual embedding itself remains a manual platform acceptance gate because an offscreen
CI platform cannot prove compositor behavior.

```powershell
ctest --test-dir build-qt -C Release --output-on-failure `
  -R QtOpenGLMultiProcessAcceptance
```
