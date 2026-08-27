#!/usr/bin/env python3
"""Create a pinned local-map Backend Config Resolver example configuration."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path


CONFIG_PRODUCT = "PocoDDSRuntimeTeamContractBackendConfigResolverConfig"
MAPPING_PRODUCT = "PocoDDSRuntimeTeamContractBackendConfigResolverMapping"
BACKEND_PRODUCT = "PocoDDSRuntimeTeamContractRegistryLeaderBackendConfig"
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
CAPABILITIES = [
    "backend-identity-binding", "local-path-resolution",
    "pinned-config-resolution", "revision-binding", "scope-validation",
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
        if (not IDENTIFIER.fullmatch(args.resolver_id)
                or not 1 <= args.timeout_seconds <= 30):
            raise ValueError("resolver configuration arguments are malformed")
        executable = regular(args.python, "Python executable")
        adapter = regular(args.adapter, "resolver adapter")
        entries = []
        seen: set[str] = set()
        for config_id, revision, config_value in args.entry:
            if (not IDENTIFIER.fullmatch(config_id)
                    or not IDENTIFIER.fullmatch(revision)
                    or config_id in seen):
                raise ValueError("resolver entry identity is malformed or duplicated")
            config = regular(config_value, "backend config")
            backend = json.loads(config.read_bytes())
            if (not isinstance(backend, dict)
                    or backend.get("product") != BACKEND_PRODUCT
                    or not IDENTIFIER.fullmatch(str(backend.get("backendId", "")))):
                raise ValueError("resolver entry is not a backend config")
            entries.append({
                "configId": config_id, "backendId": backend["backendId"],
                "revision": revision, "configPath": str(config),
                "configSha256": digest(config),
            })
            seen.add(config_id)
        entries.sort(key=lambda item: item["configId"])
        mapping, mapping_content = exclusive_json(args.mapping_output, {
            "schemaVersion": 1, "product": MAPPING_PRODUCT,
            "resolverId": args.resolver_id, "entries": entries,
        })
        output, config_content = exclusive_json(args.output, {
            "schemaVersion": 1, "product": CONFIG_PRODUCT,
            "resolverId": args.resolver_id, "kind": "external-command",
            "configIds": sorted(seen),
            "protocolMajor": 1, "minimumProtocolMinor": 0,
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
            "timeoutSeconds": args.timeout_seconds,
            "maxResponseBytes": 64 * 1024,
        })
        print(
            "PDR_BACKEND_CONFIG_RESOLVER_SAMPLE_CONFIG_PASS "
            f"resolver={args.resolver_id} entries={len(entries)} "
            f"sha256={hashlib.sha256(config_content).hexdigest()} output={output}"
        )
        return 0
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        print(f"PDR_BACKEND_CONFIG_RESOLVER_SAMPLE_CONFIG_ERROR: {error}", file=sys.stderr)
        return 2


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--python", required=True)
    result.add_argument("--adapter", required=True)
    result.add_argument("--resolver-id", required=True)
    result.add_argument(
        "--entry", nargs=3, action="append", required=True,
        metavar=("CONFIG_ID", "REVISION", "BACKEND_CONFIG"),
    )
    result.add_argument("--mapping-output", required=True)
    result.add_argument("--timeout-seconds", type=int, default=5)
    result.add_argument("--output", required=True)
    result.set_defaults(handler=execute)
    return result


def main() -> int:
    args = parser().parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
