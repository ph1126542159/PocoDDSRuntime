# Single-host acceptance

The Windows full-stack build validates both same-machine Fast-DDS transports, process and bundle
lifecycle, administration, tracing, and the Qt/OpenGL process-container demo.

Run the complete suite:

```powershell
C:\Qt\Tools\CMake_64\bin\ctest.exe --test-dir build-qt -C Release --output-on-failure
```

Repeat the four Fast-DDS multi-process combinations five times:

```powershell
C:\Qt\Tools\CMake_64\bin\ctest.exe --test-dir build-qt -C Release `
  -R '^FastDDSMultiProcessTest\.' --repeat until-fail:5 --output-on-failure
```

Use an official OpenTelemetry Collector build to prove real OTLP export from the Qt host and child:

```powershell
.\scripts\acceptance\single-host-otel.ps1 `
  -Collector C:\tools\otelcol\otelcol.exe `
  -BuildDirectory .\build-qt
```

The script requires `QT_QPA_PLATFORM=windows`, launches the Collector hidden, runs the supervised Qt
host/child workflow, verifies both service and operation names plus the correlated child log in the
Collector file export, and requires the native embedding/crash/restart marker. It stops only the
Collector process that it launched.

This is a single-machine gate. Passing it does not replace the physical two-host procedure in
`CROSS_HOST_ACCEPTANCE.md`.
