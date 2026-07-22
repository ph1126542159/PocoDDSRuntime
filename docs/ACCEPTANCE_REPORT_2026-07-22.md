# Single-host acceptance report — 2026-07-22

## Baseline

- Repository: `ph1126542159/PocoDDSRuntime`
- Commit: `c40784a`
- Host platform: Windows x64
- OpenTelemetry Collector: `0.157.0`
- GitHub Actions run: `29930537604`

## Results

| Gate | Evidence | Result |
|---|---|---|
| Windows full stack | `ctest --test-dir build-qt -C Release --output-on-failure` | 45/45 passed |
| Fast-DDS SHM payload and trace | Five consecutive multi-process runs | Passed |
| Fast-DDS UDP payload and trace | Five consecutive multi-process runs | Passed |
| Fast-DDS SHM control | Five consecutive multi-process runs | Passed |
| Fast-DDS UDP control | Five consecutive multi-process runs | Passed |
| Qt native child embedding | Three consecutive native-platform runs | Passed |
| Qt fault recovery | PID changed from 1632 to 11092 and rendered again | Passed |
| Official Collector OTLP | Both Qt services and operations plus correlated child log; 4014-byte file export | Passed |
| Portable core | Ubuntu, Windows and macOS jobs in run 29930537604 | Passed |
| Linux full stack | Full suite, isolated container network stacks and installed SDK consumer | Passed |

The final Qt marker was:

```text
QT_DDS_TRACE_CRASH_RESTART_PASS
first_pid=1632
restarted_pid=11092
native_embedded=true
```

The official Collector check returned:

```text
OTEL_OFFICIAL_COLLECTOR_SINGLE_HOST_PASS bytes=4014
```

## Scope boundary

This report proves the complete single-host baseline. The isolated Linux container test additionally
uses distinct network namespaces and IP addresses, but neither result is represented as physical
two-machine evidence. The remaining physical gate must use the procedure in
`CROSS_HOST_ACCEPTANCE.md` and retain the four host-specific JSON reports and raw logs.
