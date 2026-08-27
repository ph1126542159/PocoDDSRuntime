#!/usr/bin/env python3
"""Create a pinned environment-backed Secret Provider example config."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path


CONFIG_PRODUCT = "PocoDDSRuntimeTeamContractSecretProviderConfig"
MAPPING_PRODUCT = "PocoDDSRuntimeTeamContractSecretProviderEnvironmentMapping"
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
ENVIRONMENT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
CAPABILITIES = [
    "bounded-secret", "leased-secret", "no-secret-persistence",
    "revocation-aware", "rotation-fallback", "scoped-read",
    "version-pinned-read",
]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def regular(value: str, label: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise ValueError(f"{label} must be absolute")
    path = path.resolve()
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a regular non-link file")
    return path


def exclusive_json(path_value: str, document: dict) -> tuple[Path, bytes]:
    path = Path(path_value)
    if not path.is_absolute():
        raise ValueError("output must be absolute")
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    content = (json.dumps(document, indent=2, sort_keys=True) + "\n").encode()
    with path.open("xb") as stream:
        stream.write(content)
    return path, content


def execute(args: argparse.Namespace) -> int:
    try:
        if (not IDENTIFIER.fullmatch(args.provider_id)
                or not 1 <= args.timeout_seconds <= 30
                or not 1 <= args.max_secret_bytes <= 64 * 1024
                or not 2 <= args.lease_seconds <= 3600
                or not 1 <= args.minimum_remaining_seconds
                    < args.lease_seconds):
            raise ValueError("secret provider configuration arguments are malformed")
        executable = regular(args.python, "Python executable")
        adapter = regular(args.adapter, "secret provider adapter")
        entries = []
        seen: set[tuple[str, str]] = set()
        for secret_id, version, environment_variable in args.entry:
            if (not IDENTIFIER.fullmatch(secret_id)
                    or not IDENTIFIER.fullmatch(version)
                    or not ENVIRONMENT_NAME.fullmatch(environment_variable)
                    or (secret_id, version) in seen):
                raise ValueError("secret mapping entry is malformed or duplicated")
            entries.append({
                "secretId": secret_id, "version": version,
                "environmentVariable": environment_variable,
                "status": "active",
            })
            seen.add((secret_id, version))
        revoked = {tuple(item) for item in args.revoked}
        if not revoked.issubset(seen):
            raise ValueError("revoked secret version is not mapped")
        for entry in entries:
            if (entry["secretId"], entry["version"]) in revoked:
                entry["status"] = "revoked"
        entries.sort(key=lambda item: (item["secretId"], item["version"]))
        mapping, mapping_content = exclusive_json(args.mapping_output, {
            "schemaVersion": 2, "product": MAPPING_PRODUCT,
            "providerId": args.provider_id, "entries": entries,
        })
        maximum_response = ((args.max_secret_bytes + 2) // 3) * 4 + 4096
        output, config_content = exclusive_json(args.output, {
            "schemaVersion": 2, "product": CONFIG_PRODUCT,
            "providerId": args.provider_id, "kind": "external-command",
            "secretIds": sorted({item[0] for item in seen}),
            "protocolMajor": 1, "minimumProtocolMinor": 1,
            "requiredCapabilities": CAPABILITIES,
            "executable": str(executable),
            "executableSha256": digest(executable),
            "arguments": [str(adapter), "--mapping", str(mapping)],
            "artifactPins": [
                {"path": str(adapter), "sha256": digest(adapter)},
                {"path": str(mapping),
                 "sha256": hashlib.sha256(mapping_content).hexdigest()},
            ],
            "environmentVariables": [],
            "optionalEnvironmentVariables": sorted({
                item["environmentVariable"] for item in entries
            }),
            "timeoutSeconds": args.timeout_seconds,
            "maxResponseBytes": maximum_response,
            "maxSecretBytes": args.max_secret_bytes,
            "leasePolicy": {
                "requestedLeaseSeconds": args.lease_seconds,
                "minimumRemainingSeconds": args.minimum_remaining_seconds,
            },
        })
        print(
            "PDR_SECRET_PROVIDER_SAMPLE_CONFIG_PASS "
            f"provider={args.provider_id} secrets={len(seen)} "
            f"sha256={hashlib.sha256(config_content).hexdigest()} output={output}"
        )
        return 0
    except (OSError, UnicodeError, ValueError) as error:
        print(f"PDR_SECRET_PROVIDER_SAMPLE_CONFIG_ERROR: {error}", file=sys.stderr)
        return 2


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--python", required=True)
    result.add_argument("--adapter", required=True)
    result.add_argument("--provider-id", required=True)
    result.add_argument(
        "--entry", nargs=3, action="append", required=True,
        metavar=("SECRET_ID", "VERSION", "ENVIRONMENT_VARIABLE"),
    )
    result.add_argument("--mapping-output", required=True)
    result.add_argument("--timeout-seconds", type=int, default=5)
    result.add_argument("--max-secret-bytes", type=int, default=4096)
    result.add_argument("--lease-seconds", type=int, default=30)
    result.add_argument("--minimum-remaining-seconds", type=int, default=5)
    result.add_argument(
        "--revoked", nargs=2, action="append", default=[],
        metavar=("SECRET_ID", "VERSION"),
    )
    result.add_argument("--output", required=True)
    result.set_defaults(handler=execute)
    return result


def main() -> int:
    args = parser().parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
