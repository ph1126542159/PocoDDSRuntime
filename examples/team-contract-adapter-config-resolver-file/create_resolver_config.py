#!/usr/bin/env python3
"""Create a pinned file Adapter Config Resolver and host-local mapping."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path


CONFIG_PRODUCT = "PocoDDSRuntimeTeamContractAdapterConfigResolverConfig"
MAPPING_PRODUCT = "PocoDDSRuntimeTeamContractAdapterConfigResolverMapping"
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
ADAPTER_TYPES = {
    "artifact-store": (
        "PocoDDSRuntimeTeamContractArtifactStoreConfig", "storeId"
    ),
    "control-authorizer": (
        "PocoDDSRuntimeTeamContractAdapterCatalogControlAuthorizerConfig",
        "authorizerId",
    ),
    "fleet-executor": (
        "PocoDDSRuntimeTeamContractAdapterCatalogFleetExecutorConfig",
        "executorId",
    ),
    "registry-leader-backend": (
        "PocoDDSRuntimeTeamContractRegistryLeaderBackendConfig", "backendId"
    ),
    "wave-gate": (
        "PocoDDSRuntimeTeamContractAdapterCatalogWaveGateConfig", "gateId"
    ),
}
CAPABILITIES = [
    "adapter-identity-binding", "adapter-kind-binding",
    "consumer-scope-confinement", "local-path-resolution",
    "pinned-config-resolution", "revision-binding",
]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def regular(value: str, label: str) -> Path:
    path = Path(value)
    if not path.is_absolute() or path.is_symlink():
        raise ValueError(f"{label} must be an absolute non-link file")
    path = path.resolve()
    if not path.is_file():
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
        if (IDENTIFIER.fullmatch(args.resolver_id) is None
                or not 1 <= args.timeout_seconds <= 30
                or not args.scope):
            raise ValueError("Adapter resolver arguments are malformed")
        scopes = []
        for consumer_type, consumer_id, resource_id in args.scope:
            if any(IDENTIFIER.fullmatch(value) is None for value in (
                    consumer_type, consumer_id, resource_id)):
                raise ValueError("Adapter resolver scope is malformed")
            scopes.append({
                "consumerType": consumer_type, "consumerId": consumer_id,
                "resourceId": resource_id,
            })
        scopes = sorted(
            {json.dumps(item, sort_keys=True): item for item in scopes}.values(),
            key=lambda item: json.dumps(item, sort_keys=True),
        )
        entries = []
        seen: set[str] = set()
        for config_id, revision, adapter_kind, config_value in args.entry:
            if (IDENTIFIER.fullmatch(config_id) is None
                    or IDENTIFIER.fullmatch(revision) is None
                    or adapter_kind not in ADAPTER_TYPES
                    or config_id in seen):
                raise ValueError("Adapter resolver entry is malformed or duplicated")
            config = regular(config_value, "Adapter config")
            document = json.loads(config.read_bytes())
            product, identity_field = ADAPTER_TYPES[adapter_kind]
            adapter_id = document.get(identity_field) \
                if isinstance(document, dict) else None
            if (not isinstance(document, dict)
                    or document.get("product") != product
                    or IDENTIFIER.fullmatch(str(adapter_id or "")) is None):
                raise ValueError("resolver entry has the wrong Adapter type")
            entries.append({
                "configId": config_id, "revision": revision,
                "adapterKind": adapter_kind, "adapterId": adapter_id,
                "configPath": str(config), "configSha256": digest(config),
                "scopes": scopes,
            })
            seen.add(config_id)
        entries.sort(key=lambda item: item["configId"])
        executable = regular(args.python, "Python executable")
        adapter = regular(args.adapter, "resolver adapter")
        mapping, mapping_content = exclusive_json(args.mapping_output, {
            "schemaVersion": 1, "product": MAPPING_PRODUCT,
            "resolverId": args.resolver_id, "entries": entries,
        })
        output, config_content = exclusive_json(args.output, {
            "schemaVersion": 1, "product": CONFIG_PRODUCT,
            "resolverId": args.resolver_id, "kind": "external-command",
            "configIds": sorted(seen), "protocolMajor": 1,
            "minimumProtocolMinor": 0,
            "requiredCapabilities": CAPABILITIES,
            "executable": str(executable),
            "executableSha256": digest(executable),
            "arguments": [str(adapter), "--mapping", str(mapping)],
            "artifactPins": [
                {"path": str(adapter), "sha256": digest(adapter)},
                {"path": str(mapping), "sha256": hashlib.sha256(
                    mapping_content).hexdigest()},
            ],
            "environmentVariables": [],
            "timeoutSeconds": args.timeout_seconds,
            "maxResponseBytes": 64 * 1024,
        })
        print(
            "PDR_ADAPTER_CONFIG_RESOLVER_SAMPLE_CONFIG_PASS "
            f"resolver={args.resolver_id} entries={len(entries)} "
            f"sha256={hashlib.sha256(config_content).hexdigest()} output={output}"
        )
        return 0
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        print(f"PDR_ADAPTER_CONFIG_RESOLVER_SAMPLE_CONFIG_ERROR: {error}",
              file=sys.stderr)
        return 2


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--python", required=True)
    result.add_argument("--adapter", required=True)
    result.add_argument("--resolver-id", required=True)
    result.add_argument(
        "--entry", nargs=4, action="append", required=True,
        metavar=("CONFIG_ID", "REVISION", "ADAPTER_KIND", "CONFIG"),
    )
    result.add_argument(
        "--scope", nargs=3, action="append", required=True,
        metavar=("CONSUMER_TYPE", "CONSUMER_ID", "RESOURCE_ID"),
    )
    result.add_argument("--mapping-output", required=True)
    result.add_argument("--timeout-seconds", type=int, default=5)
    result.add_argument("--output", required=True)
    return result


if __name__ == "__main__":
    raise SystemExit(execute(parser().parse_args()))
