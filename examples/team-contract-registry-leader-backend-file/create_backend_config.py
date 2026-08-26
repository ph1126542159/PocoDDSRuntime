#!/usr/bin/env python3
"""Create a digest-pinned config for the PDR file backend SDK example."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path


PRODUCT = "PocoDDSRuntimeTeamContractRegistryLeaderBackendConfig"
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
ENVIRONMENT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def regular_absolute(value: str, label: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise ValueError(f"{label} must be absolute")
    resolved = path.resolve()
    if path.is_symlink() or resolved.is_symlink() or not resolved.is_file():
        raise ValueError(f"{label} must be a regular non-link file")
    return resolved


def execute(args: argparse.Namespace) -> int:
    try:
        if (not IDENTIFIER.fullmatch(args.backend_id)
                or not args.authority_id or not args.registry_id
                or any(not IDENTIFIER.fullmatch(item)
                       for item in args.authority_id + args.registry_id)
                or len(set(args.authority_id)) != len(args.authority_id)
                or len(set(args.registry_id)) != len(args.registry_id)
                or not ENVIRONMENT_NAME.fullmatch(args.root_environment)
                or not 1 <= args.timeout_seconds <= 30
                or not 1024 <= args.max_response_bytes <= 1024 * 1024):
            raise ValueError("backend configuration arguments are malformed")
        executable = regular_absolute(args.python, "Python executable")
        adapter = regular_absolute(args.adapter, "adapter")
        output = Path(args.output)
        if not output.is_absolute():
            raise ValueError("output must be absolute")
        output = output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        document = {
            "schemaVersion": 1, "product": PRODUCT,
            "backendId": args.backend_id, "kind": "external-command",
            "authorityIds": args.authority_id,
            "registryIds": args.registry_id,
            "executable": str(executable),
            "executableSha256": digest(executable),
            "arguments": [str(adapter)],
            "artifactPins": [{"path": str(adapter), "sha256": digest(adapter)}],
            "environmentVariables": [args.root_environment],
            "timeoutSeconds": args.timeout_seconds,
            "maxResponseBytes": args.max_response_bytes,
        }
        content = (json.dumps(document, indent=2, sort_keys=True)
                   + "\n").encode("utf-8")
        with output.open("xb") as stream:
            stream.write(content)
        print(
            "PDR_LEADER_BACKEND_SAMPLE_CONFIG_PASS "
            f"backend={args.backend_id} sha256={hashlib.sha256(content).hexdigest()} "
            f"output={output}"
        )
        return 0
    except (OSError, UnicodeError, ValueError) as error:
        print(f"PDR_LEADER_BACKEND_SAMPLE_CONFIG_ERROR: {error}", file=sys.stderr)
        return 2


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--python", required=True)
    result.add_argument("--adapter", required=True)
    result.add_argument("--backend-id", required=True)
    result.add_argument("--authority-id", action="append", required=True)
    result.add_argument("--registry-id", action="append", required=True)
    result.add_argument(
        "--root-environment", default="PDR_LEADER_BACKEND_SAMPLE_ROOT"
    )
    result.add_argument("--timeout-seconds", type=int, default=5)
    result.add_argument("--max-response-bytes", type=int, default=65536)
    result.add_argument("--output", required=True)
    result.set_defaults(handler=execute)
    return result


def main() -> int:
    args = parser().parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
