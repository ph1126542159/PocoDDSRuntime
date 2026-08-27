#!/usr/bin/env python3
"""Create a pinned local Ed25519 Certifier Signer example config."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path


CONFIG_PRODUCT = \
    "PocoDDSRuntimeTeamContractAdapterCertifierSignerConfig"
MAPPING_PRODUCT = \
    "PocoDDSRuntimeTeamContractAdapterCertifierSignerLocalMapping"
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
ENVIRONMENT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
CAPABILITIES = [
    "ed25519", "key-id-routing", "payload-sha256",
    "private-key-non-export",
]


def regular(value: str, label: str) -> Path:
    path = Path(value)
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be an absolute non-link file")
    return path.resolve()


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def exclusive_json(path_value: str, document: dict) -> tuple[Path, bytes]:
    path = Path(path_value)
    if not path.is_absolute() or path.is_symlink():
        raise ValueError("output must be an absolute non-link path")
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    content = (json.dumps(document, indent=2, sort_keys=True) + "\n").encode()
    with path.open("xb") as stream:
        stream.write(content)
    return path, content


def execute(args: argparse.Namespace) -> int:
    try:
        if (any(IDENTIFIER.fullmatch(value) is None for value in (
                args.signer_id, args.certifier_id))
                or not 1 <= args.timeout_seconds <= 60
                or not 256 <= args.max_payload_bytes <= 64 * 1024):
            raise ValueError("signer configuration arguments are malformed")
        executable = regular(args.python, "Python executable")
        adapter = regular(args.adapter, "signer adapter")
        keys = []
        mappings = []
        seen: set[str] = set()
        for key_id, public_value, environment in args.key:
            public = regular(public_value, "signer public key")
            if (IDENTIFIER.fullmatch(key_id) is None
                    or ENVIRONMENT_NAME.fullmatch(environment) is None
                    or key_id in seen):
                raise ValueError("signer key is malformed or duplicated")
            keys.append({
                "keyId": key_id, "algorithm": "Ed25519",
                "publicKey": str(public), "publicKeySha256": digest(public),
            })
            mappings.append({
                "keyId": key_id, "privateKeyEnvironment": environment,
            })
            seen.add(key_id)
        keys.sort(key=lambda item: item["keyId"])
        mappings.sort(key=lambda item: item["keyId"])
        mapping, mapping_content = exclusive_json(args.mapping_output, {
            "schemaVersion": 1, "product": MAPPING_PRODUCT,
            "signerId": args.signer_id, "certifierId": args.certifier_id,
            "keys": mappings,
        })
        output, config_content = exclusive_json(args.output, {
            "schemaVersion": 1, "product": CONFIG_PRODUCT,
            "signerId": args.signer_id, "certifierId": args.certifier_id,
            "kind": "external-command", "protocolMajor": 1,
            "minimumProtocolMinor": 0,
            "requiredCapabilities": CAPABILITIES, "keys": keys,
            "executable": str(executable),
            "executableSha256": digest(executable),
            "arguments": [str(adapter), "--mapping", str(mapping)],
            "artifactPins": [
                {"path": str(adapter), "sha256": digest(adapter)},
                {"path": str(mapping),
                 "sha256": hashlib.sha256(mapping_content).hexdigest()},
            ],
            "environmentVariables": [],
            "optionalEnvironmentVariables": sorted(
                {item[2] for item in args.key}
                | {"PDR_CERTIFIER_SIGNER_FAULT"}
            ),
            "timeoutSeconds": args.timeout_seconds,
            "maxResponseBytes": 16384,
            "maxPayloadBytes": args.max_payload_bytes,
        })
        print(
            "PDR_CERTIFIER_SIGNER_SAMPLE_CONFIG_PASS "
            f"signer={args.signer_id} keys={len(keys)} "
            f"sha256={hashlib.sha256(config_content).hexdigest()} "
            f"output={output}"
        )
        return 0
    except (OSError, UnicodeError, ValueError) as error:
        print(f"PDR_CERTIFIER_SIGNER_SAMPLE_CONFIG_ERROR: {error}",
              file=sys.stderr)
        return 2


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--python", required=True)
    result.add_argument("--adapter", required=True)
    result.add_argument("--signer-id", required=True)
    result.add_argument("--certifier-id", required=True)
    result.add_argument(
        "--key", nargs=3, action="append", required=True,
        metavar=("KEY_ID", "PUBLIC_KEY", "PRIVATE_KEY_ENVIRONMENT"),
    )
    result.add_argument("--mapping-output", required=True)
    result.add_argument("--timeout-seconds", type=int, default=5)
    result.add_argument("--max-payload-bytes", type=int, default=16384)
    result.add_argument("--output", required=True)
    return result


if __name__ == "__main__":
    raise SystemExit(execute(parser().parse_args()))
