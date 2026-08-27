#!/usr/bin/env python3
"""Create a digest-pinned config for the PDR file Artifact Store example."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path


PRODUCT = "PocoDDSRuntimeTeamContractArtifactStoreConfig"
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
ENVIRONMENT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
CAPABILITIES = [
    "content-addressed-read", "idempotent-create", "immutable-content",
    "namespace-confinement", "read-after-write",
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def regular(value: str, label: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise ValueError(f"{label} must be absolute")
    path = path.resolve()
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a regular non-link file")
    return path


def execute(args: argparse.Namespace) -> int:
    try:
        namespaces = sorted(set(args.namespace_id))
        if (not IDENTIFIER.fullmatch(args.store_id)
                or len(namespaces) != len(args.namespace_id)
                or any(not IDENTIFIER.fullmatch(item) for item in namespaces)
                or not ENVIRONMENT_NAME.fullmatch(args.root_environment)
                or not 1 <= args.timeout_seconds <= 60
                or not 1 <= args.max_artifact_bytes <= 16 * 1024 * 1024):
            raise ValueError("artifact store configuration arguments are malformed")
        executable = regular(args.python, "Python executable")
        adapter = regular(args.adapter, "adapter")
        output = Path(args.output)
        if not output.is_absolute():
            raise ValueError("output must be absolute")
        output = output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        maximum_response = ((args.max_artifact_bytes + 2) // 3) * 4 + 4096
        document = {
            "schemaVersion": 1, "product": PRODUCT,
            "storeId": args.store_id, "kind": "external-command",
            "namespaceIds": namespaces,
            "protocolMajor": 1, "minimumProtocolMinor": 0,
            "requiredCapabilities": CAPABILITIES,
            "executable": str(executable),
            "executableSha256": sha256(executable),
            "arguments": [
                str(adapter), "--root-environment", args.root_environment,
            ],
            "artifactPins": [{"path": str(adapter), "sha256": sha256(adapter)}],
            "environmentVariables": [args.root_environment],
            "timeoutSeconds": args.timeout_seconds,
            "maxResponseBytes": maximum_response,
            "maxArtifactBytes": args.max_artifact_bytes,
        }
        content = (json.dumps(document, indent=2, sort_keys=True)
                   + "\n").encode("utf-8")
        with output.open("xb") as stream:
            stream.write(content)
        print(
            "PDR_ARTIFACT_STORE_SAMPLE_CONFIG_PASS "
            f"store={args.store_id} sha256={hashlib.sha256(content).hexdigest()} "
            f"output={output}"
        )
        return 0
    except (OSError, UnicodeError, ValueError) as error:
        print(f"PDR_ARTIFACT_STORE_SAMPLE_CONFIG_ERROR: {error}", file=sys.stderr)
        return 2


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--python", required=True)
    result.add_argument("--adapter", required=True)
    result.add_argument("--store-id", required=True)
    result.add_argument("--namespace-id", action="append", required=True)
    result.add_argument(
        "--root-environment", default="PDR_ARTIFACT_STORE_SAMPLE_ROOT"
    )
    result.add_argument("--timeout-seconds", type=int, default=5)
    result.add_argument("--max-artifact-bytes", type=int, default=1024 * 1024)
    result.add_argument("--output", required=True)
    result.set_defaults(handler=execute)
    return result


def main() -> int:
    args = parser().parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
