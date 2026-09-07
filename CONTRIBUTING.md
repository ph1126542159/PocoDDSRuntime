# Contributing

PocoDDSRuntime is an early-stage project. Reports with a minimal reproduction,
platform/toolchain versions, and expected/actual behavior are welcome through
GitHub Issues. Remove credentials and private deployment data from reports.

For changes, explain the affected lifecycle, service or protocol boundary and
include the applicable validation results. Keep test fixtures separate from
deployment configuration. Use descriptive commit messages and retain upstream
copyright and license notices.

Project-owned contributions are accepted under GPL-3.0-only; third-party files
retain their existing licenses. See `NOTICE.md`.

Read `README.md` and `docs/README.md` for architecture and build entry points.
Python tooling tests can be run after building the native signature verifier
(`build/bin/pdr-signature-check.exe` on Windows) with:

```sh
python -m unittest discover -s tools/tests -v
```

The CI workflow contains additional repository-policy and native build checks.
A local tooling pass is not evidence of a successful full native build.
Some signature-verifier tests use their dedicated CTest entry points and are
not fully initialized by generic unittest discovery.
