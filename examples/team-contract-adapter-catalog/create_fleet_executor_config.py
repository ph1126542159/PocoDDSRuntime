#!/usr/bin/env python3
"""Create a digest-pinned Adapter Catalog Fleet Executor config."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path


PRODUCT = "PocoDDSRuntimeTeamContractAdapterCatalogFleetExecutorConfig"
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
ENVIRONMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
CAPABILITIES = [
    "idempotent-node-deploy", "node-reconcile-status",
    "reverse-order-revert", "wave-rollout",
]
DEPENDENCIES = [
    "process_file_lease.py", "team_contract_adapter_catalog.py",
    "team_contract_adapter_catalog_reconciler.py",
    "team_contract_adapter_catalog_state.py", "team_contract_adapter_runtime.py",
    "team_contract_package.py", "team_contract_registry.py",
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
        if (IDENTIFIER.fullmatch(args.executor_id) is None
                or any(ENVIRONMENT.fullmatch(item) is None
                       for item in args.optional_environment)
                or not 1 <= args.timeout_seconds <= 120):
            raise ValueError("Fleet Executor config identity is malformed")
        python = regular(args.python, "Python executable")
        adapter = regular(args.adapter, "Fleet Executor adapter")
        mapping = regular(args.mapping, "Fleet node map")
        tools_dir = Path(args.tools_dir)
        if (not tools_dir.is_absolute() or tools_dir.is_symlink()
                or not tools_dir.resolve().is_dir()):
            raise ValueError("tools directory is unavailable or unsafe")
        tools_dir = tools_dir.resolve()
        dependencies = [regular(str(tools_dir / name), name) for name in DEPENDENCIES]
        output = Path(args.output)
        if not output.is_absolute() or output.is_symlink():
            raise ValueError("output must be an absolute non-link path")
        output = output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        pins = [adapter, mapping, *dependencies]
        document = {
            "schemaVersion": 1, "product": PRODUCT,
            "executorId": args.executor_id, "kind": "external-command",
            "protocolMajor": 1, "minimumProtocolMinor": 0,
            "requiredCapabilities": CAPABILITIES,
            "executable": str(python), "executableSha256": sha(python),
            "arguments": [str(adapter), "--mapping", str(mapping),
                          "--tools-dir", str(tools_dir)],
            "artifactPins": [
                {"path": str(path), "sha256": sha(path)} for path in pins
            ],
            "environmentVariables": [],
            "optionalEnvironmentVariables": sorted(
                set(args.optional_environment)),
            "timeoutSeconds": args.timeout_seconds, "maxResponseBytes": 4096,
        }
        content = (json.dumps(document, indent=2, sort_keys=True) + "\n").encode()
        descriptor = os.open(output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
        print(
            "PDR_ADAPTER_CATALOG_FLEET_EXECUTOR_CONFIG_PASS "
            f"executor={args.executor_id} sha256={hashlib.sha256(content).hexdigest()}"
        )
        return 0
    except (OSError, ValueError) as error:
        print(f"PDR_ADAPTER_CATALOG_FLEET_EXECUTOR_CONFIG_ERROR: {error}", file=sys.stderr)
        return 2


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--python", required=True)
    result.add_argument("--adapter", required=True)
    result.add_argument("--mapping", required=True)
    result.add_argument("--tools-dir", required=True)
    result.add_argument("--executor-id", required=True)
    result.add_argument("--optional-environment", action="append", default=[])
    result.add_argument("--timeout-seconds", type=int, default=30)
    result.add_argument("--output", required=True)
    return result


if __name__ == "__main__":
    raise SystemExit(execute(parser().parse_args()))
