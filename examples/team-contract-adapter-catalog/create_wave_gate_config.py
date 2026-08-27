#!/usr/bin/env python3
"""Create a digest-pinned Adapter Catalog Wave Gate config."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path


PRODUCT = "PocoDDSRuntimeTeamContractAdapterCatalogWaveGateConfig"
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
ENVIRONMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
CAPABILITIES = [
    "bounded-observation", "idempotent-evaluation", "no-secret-evidence",
    "wave-slo-gate",
]


def regular(value: str, label: str) -> Path:
    path = Path(value)
    if not path.is_absolute() or path.is_symlink():
        raise ValueError(f"{label} must be an absolute non-link file")
    path = path.resolve()
    if not path.is_file():
        raise ValueError(f"{label} is unavailable")
    return path


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def execute(args: argparse.Namespace) -> int:
    try:
        if (IDENTIFIER.fullmatch(args.gate_id) is None
                or ENVIRONMENT.fullmatch(args.state_environment) is None
                or any(ENVIRONMENT.fullmatch(item) is None
                       for item in args.optional_environment)
                or not 1 <= args.timeout_seconds <= 120):
            raise ValueError("Wave Gate config identity is malformed")
        python = regular(args.python, "Python executable")
        adapter = regular(args.adapter, "Wave Gate adapter")
        optional = sorted(set(args.optional_environment))
        if args.state_environment in optional:
            raise ValueError("Wave Gate required and optional environments overlap")
        output = Path(args.output)
        if not output.is_absolute() or output.is_symlink():
            raise ValueError("output must be an absolute non-link path")
        output = output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        document = {
            "schemaVersion": 1, "product": PRODUCT, "gateId": args.gate_id,
            "kind": "external-command", "protocolMajor": 1,
            "minimumProtocolMinor": 0, "requiredCapabilities": CAPABILITIES,
            "executable": str(python), "executableSha256": sha(python),
            "arguments": [str(adapter)],
            "artifactPins": [{"path": str(adapter), "sha256": sha(adapter)}],
            "environmentVariables": [args.state_environment],
            "optionalEnvironmentVariables": optional,
            "timeoutSeconds": args.timeout_seconds, "maxResponseBytes": 4096,
        }
        content = (json.dumps(document, indent=2, sort_keys=True) + "\n").encode()
        descriptor = os.open(output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
        print(
            "PDR_ADAPTER_CATALOG_WAVE_GATE_CONFIG_PASS "
            f"gate={args.gate_id} sha256={hashlib.sha256(content).hexdigest()}"
        )
        return 0
    except (OSError, ValueError) as error:
        print(f"PDR_ADAPTER_CATALOG_WAVE_GATE_CONFIG_ERROR: {error}", file=sys.stderr)
        return 2


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--python", required=True)
    result.add_argument("--adapter", required=True)
    result.add_argument("--gate-id", required=True)
    result.add_argument("--state-environment", default="PDR_WAVE_GATE_STATE_ROOT")
    result.add_argument("--optional-environment", action="append", default=[])
    result.add_argument("--timeout-seconds", type=int, default=30)
    result.add_argument("--output", required=True)
    return result


if __name__ == "__main__":
    raise SystemExit(execute(parser().parse_args()))
