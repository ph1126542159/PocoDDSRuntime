#!/usr/bin/env python3
"""Create a pinned discovery manifest around one external-command adapter config."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path


PRODUCT = "PocoDDSRuntimeTeamContractAdapterManifest"
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
ADAPTER_TYPE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
FIELD_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9]{0,63}$")
OWNER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}/[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
RESERVED_CAPABILITY_FIELDS = {
    "schemaVersion", "product", "requestId", "implementationId",
    "protocolMajor", "protocolMinor", "capabilities",
}


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
        if (any(IDENTIFIER.fullmatch(value) is None for value in (
                args.manifest_id, args.adapter_id, args.revision,
                args.protocol_id, args.capability_request_product,
                args.capability_manifest_product))
                or ADAPTER_TYPE.fullmatch(args.adapter_type) is None
                or OWNER.fullmatch(args.owner) is None
                or FIELD_NAME.fullmatch(args.identity_field) is None
                or args.identity_field in RESERVED_CAPABILITY_FIELDS):
            raise ValueError("adapter manifest arguments are malformed")
        config_path = regular(args.config, "adapter config")
        config_content = config_path.read_bytes()
        config = json.loads(config_content)
        if (not isinstance(config, dict)
                or config.get(args.identity_field) != args.adapter_id
                or config.get("kind") != "external-command"):
            raise ValueError("adapter config identity is incompatible")
        output = Path(args.output)
        if not output.is_absolute():
            raise ValueError("output must be absolute")
        output = output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        document = {
            "schemaVersion": 1, "product": PRODUCT,
            "manifestId": args.manifest_id, "adapterId": args.adapter_id,
            "adapterType": args.adapter_type, "owner": args.owner,
            "revision": args.revision, "protocolId": args.protocol_id,
            "configPath": str(config_path),
            "configSha256": hashlib.sha256(config_content).hexdigest(),
            "identityField": args.identity_field,
            "capabilityRequestProduct": args.capability_request_product,
            "capabilityManifestProduct": args.capability_manifest_product,
        }
        content = (json.dumps(document, indent=2, sort_keys=True) + "\n").encode()
        with output.open("xb") as stream:
            stream.write(content)
        print(
            "PDR_ADAPTER_MANIFEST_CREATE_PASS "
            f"manifest={args.manifest_id} adapter={args.adapter_id} "
            f"sha256={hashlib.sha256(content).hexdigest()}"
        )
        return 0
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        print(f"PDR_ADAPTER_MANIFEST_CREATE_ERROR: {error}", file=sys.stderr)
        return 2


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--config", required=True)
    result.add_argument("--manifest-id", required=True)
    result.add_argument("--adapter-id", required=True)
    result.add_argument("--adapter-type", required=True)
    result.add_argument("--owner", required=True)
    result.add_argument("--revision", required=True)
    result.add_argument("--protocol-id", required=True)
    result.add_argument("--identity-field", required=True)
    result.add_argument("--capability-request-product", required=True)
    result.add_argument("--capability-manifest-product", required=True)
    result.add_argument("--output", required=True)
    result.set_defaults(handler=execute)
    return result


def main() -> int:
    args = parser().parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
