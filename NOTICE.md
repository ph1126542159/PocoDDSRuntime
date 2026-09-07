# Licensing and attribution

PocoDDSRuntime is maintained by Hui Peng (GitHub: ph1126542159).
Project-owned contributions are licensed under GPL-3.0-only. The license text
is in `LICENSE`. Existing third-party copyright notices and licenses remain
in force; this declaration does not relicense third-party code or claim its
authorship.

## Included source

- The OSP service-container and CodeGeneration modules, and other files marked
  `SPDX-License-Identifier: GPL-3.0-only`, retain the copyrights of Applied
  Informatics Software Engineering GmbH and their other named authors.
- The composition model and portions of the platform/services derive from
  macchina.io. This project changes the cross-process communication layer to
  Fast DDS and adds its own runtime, observability, tooling and UI integration.
  Source provenance: https://github.com/MyPocoPH/macchina.io (upstream recorded
  by GitHub as https://github.com/leisen2009/macchina.io).
- Files marked `BSL-1.0`, including Serial and WebTunnel sources, retain the
  Boost Software License in `LICENSES/BSL-1.0.txt`.
- Other included files retain their existing file-level license and copyright
  notices. Consult those notices before redistributing a component separately.

## Build dependencies

Pinned dependency versions, licenses and source URLs are listed in
`release/dependencies.json`. These include Poco (BSL-1.0), Fast DDS and Fast CDR
(Apache-2.0), foonathan memory (Zlib), Paho MQTT C (EPL-2.0 OR BSD-3-Clause),
OpenTelemetry C++ (Apache-2.0), and GoogleTest (BSD-3-Clause).
Qt and frontend packages have their own licenses. Frontend manifests and lock
files identify the packages; dependency installations are not maintained as
project source. Preserve the corresponding notices when distributing binaries.

## Public test certificates

`platform/OSP/samples/BundleContainer/any.pem` and
`platform/OSP/samples/BundleServer/any.pem` contain the same public upstream
example key/certificate fixture. Their Git blob is
`cf7ff6ef5052bcf323954cb92a66bbb21f61c8fe`, verified against
https://github.com/MyPocoPH/macchina.io/blob/71a448532de5e3853f40d8bea579613d775b8882/platform/OSP/samples/BundleContainer/any.pem.
They are test data, not confidential deployment credentials. Never use them
to secure a deployment; generate and manage deployment keys separately.
