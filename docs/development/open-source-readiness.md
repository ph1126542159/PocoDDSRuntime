# Open-source preparation, 2026-09-07

This preparation starts from main commit
`3821d9a9950ddedb4b80398551897c704f66f8a0`. It adds the project license and
attribution, removes tracked frontend dependency installations, and documents
the current acceptance boundary. It does not change the runtime architecture.

## Secret scan

Gitleaks 8.30.1 scanned all fetched branches and tags and local Git refs:
102 commits, approximately 143.77 MB. Its 159 initial candidates were reviewed:

- 149 generated `tokenSha256` interface-fingerprint values;
- 8 test constants, test signing labels, or variable/filename false positives;
- 2 public upstream example PEM fixtures, identified by blob hash in `NOTICE.md`.

`.gitleaksignore` records exact historical finding fingerprints, not broad
directory exclusions. New findings still require review. This scan did not
identify a live credential requiring revocation; it is not a guarantee that
automated detection finds every possible secret or confidential document.

## Validation boundary

The existing v0.1.0 GitHub Release is a source release without binary assets.
At preparation time, main's most recent CI run was 32206271407, which failed
formatting and Linux compilation (Poco Data `long long` extraction). Those
pre-existing failures are not represented as fixed by licensing cleanup.
See https://github.com/ph1126542159/PocoDDSRuntime/actions/runs/32206271407.

The project has not established broad public adoption. Build/release status,
hardware acceptance and external adoption must be reported separately.

The preparation passed contract, documentation, profile, compatibility,
dependency-inventory, release-matrix and default-security configuration checks.
Generic Python test discovery ran 87 tests: 83 passed and 4 errored because
the isolated checkout lacks the native signature verifier or the dedicated
test entry point's executable argument. This is not a full test-suite pass.
