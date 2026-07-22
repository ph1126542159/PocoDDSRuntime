# Two-host Fast-DDS acceptance

CI also runs `scripts/acceptance/container-network-fastdds.sh`, which proves network-only discovery,
payload/trace propagation and control across two isolated Linux container network stacks. The
procedure below is deliberately stricter and remains the required physical two-machine acceptance.

This gate proves that communication is not accidentally using shared memory or loopback. Both hosts
must be on a multicast-capable network, use the same probe binary build and DDS domain, and allow UDP
discovery/data traffic through their firewalls.

Build `pdr-dds-probe` with Fast-DDS enabled, copy the same executable and its runtime dependencies to
both machines, and create an empty evidence directory on each host. Start the subscriber first:

```powershell
.\scripts\acceptance\cross-host-fastdds.ps1 -Role subscriber `
  -Probe .\build-fastdds\apps\pdr-dds-probe.exe -Domain 166
```

While it is waiting, run this on the second host:

```powershell
.\scripts\acceptance\cross-host-fastdds.ps1 -Role publisher `
  -Probe .\build-fastdds\apps\pdr-dds-probe.exe -Domain 166
```

Repeat the control-plane gate by starting `control-agent` on the first host and `control-client` on
the second. Each command writes a versioned JSON report containing hostname, IPv4 addresses, UTC
times, probe SHA-256, domain, forced `network-only` transport, exit code, marker and raw log name.

Acceptance requires all four reports to have exit code zero, different hostnames (and normally
different non-loopback IPv4 addresses), identical probe hashes/domain, plus these markers:

- subscriber: `FAST_DDS_TWO_PROCESS_PASS`
- publisher: `FAST_DDS_PUBLISH_PASS` in its log
- control agent: `FAST_DDS_CONTROL_AGENT_PASS` in its log
- control client: `FAST_DDS_CONTROL_PASS`

Archive the four JSON files and four logs together. A same-host network-only run remains useful, but
does not satisfy this two-host gate.

Place all eight files in one directory and verify the evidence set:

```powershell
.\scripts\acceptance\verify-cross-host-fastdds.ps1 `
  -EvidenceDirectory .\cross-host-evidence
```

Only `FAST_DDS_PHYSICAL_TWO_HOST_ACCEPTANCE_PASS` closes the physical two-host gate.
