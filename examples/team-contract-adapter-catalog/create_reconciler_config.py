#!/usr/bin/env python3
"""Create a digest-pinned Adapter Catalog lifecycle Reconciler config."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path


PRODUCT = "PocoDDSRuntimeTeamContractAdapterCatalogReconcilerConfig"
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
ENVIRONMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
CAPABILITIES = [
    "abort", "activate", "bounded-drain", "commit", "health-gate",
    "idempotent-operations", "prepare", "rollback",
]


def regular(path_value: str, label: str) -> Path:
    path = Path(path_value)
    if not path.is_absolute():
        raise ValueError(f"{label} must be absolute")
    path = path.resolve()
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a regular non-link file")
    return path


def execute(args: argparse.Namespace) -> int:
    try:
        if (IDENTIFIER.fullmatch(args.reconciler_id) is None
                or ENVIRONMENT.fullmatch(args.state_environment) is None
                or any(ENVIRONMENT.fullmatch(item) is None
                       for item in args.optional_environment)
                or not 1 <= args.timeout_seconds <= 60
                or not 1 <= args.health_attempts <= 100
                or not 0 <= args.health_interval_milliseconds <= 30000):
            raise ValueError("Reconciler config identity is malformed")
        python = regular(args.python, "Python executable")
        adapter = regular(args.adapter, "Reconciler adapter")
        output = Path(args.output)
        if not output.is_absolute():
            raise ValueError("output must be absolute")
        output = output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        optional = sorted(set(args.optional_environment))
        if args.state_environment in optional:
            raise ValueError("required and optional environments overlap")
        document = {
            "schemaVersion": 1, "product": PRODUCT,
            "reconcilerId": args.reconciler_id, "kind": "external-command",
            "protocolMajor": 1, "minimumProtocolMinor": 0,
            "requiredCapabilities": CAPABILITIES,
            "executable": str(python),
            "executableSha256": hashlib.sha256(python.read_bytes()).hexdigest(),
            "arguments": [str(adapter)],
            "artifactPins": [{
                "path": str(adapter),
                "sha256": hashlib.sha256(adapter.read_bytes()).hexdigest(),
            }],
            "environmentVariables": [args.state_environment],
            "optionalEnvironmentVariables": optional,
            "timeoutSeconds": args.timeout_seconds,
            "maxResponseBytes": 4096,
            "healthAttempts": args.health_attempts,
            "healthIntervalMilliseconds": args.health_interval_milliseconds,
        }
        content = (json.dumps(document, indent=2, sort_keys=True) + "\n").encode()
        descriptor = os.open(output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
        print(
            "PDR_ADAPTER_CATALOG_RECONCILER_CONFIG_PASS "
            f"reconciler={args.reconciler_id} "
            f"sha256={hashlib.sha256(content).hexdigest()}"
        )
        return 0
    except (OSError, ValueError) as error:
        print(f"PDR_ADAPTER_CATALOG_RECONCILER_CONFIG_ERROR: {error}", file=sys.stderr)
        return 2


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--python", required=True)
    result.add_argument("--adapter", required=True)
    result.add_argument("--reconciler-id", required=True)
    result.add_argument("--state-environment", default="PDR_RECONCILER_STATE_ROOT")
    result.add_argument("--optional-environment", action="append", default=[])
    result.add_argument("--timeout-seconds", type=int, default=10)
    result.add_argument("--health-attempts", type=int, default=3)
    result.add_argument("--health-interval-milliseconds", type=int, default=10)
    result.add_argument("--output", required=True)
    result.set_defaults(handler=execute)
    return result


def main() -> int:
    args = parser().parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
