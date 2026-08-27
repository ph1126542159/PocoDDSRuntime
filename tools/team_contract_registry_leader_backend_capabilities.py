#!/usr/bin/env python3
"""Negotiate and record a pinned Registry leader backend capability manifest."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import team_contract_package as package_tool
import team_contract_registry_leader_backend as backend_tool


REPORT_PRODUCT = (
    "PocoDDSRuntimeTeamContractRegistryLeaderBackendCapabilityReport"
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def execute_command(args: argparse.Namespace) -> int:
    try:
        backend = backend_tool.ExternalCommandBackend(
            args.backend_config, args.expected_backend_config_sha256,
            args.authority_id, args.registry_id,
        )
        if (backend.config["schemaVersion"] != 2
                or backend.capability_manifest is None
                or backend.capability_manifest_sha256 is None):
            raise ValueError(
                "Registry leader backend configuration does not require "
                "capability negotiation"
            )
        manifest = backend.capability_manifest
        report = {
            "schemaVersion": 1, "product": REPORT_PRODUCT, "passed": True,
            "backendId": backend.backend_id,
            "authorityId": args.authority_id, "registryId": args.registry_id,
            "backendConfigSha256": backend.config_sha256,
            "implementationId": manifest["implementationId"],
            "protocolMajor": manifest["protocolMajor"],
            "protocolMinor": manifest["protocolMinor"],
            "requiredCapabilities": backend.config["requiredCapabilities"],
            "capabilities": manifest["capabilities"],
            "capabilityManifestSha256": backend.capability_manifest_sha256,
            "checkedAt": utc_now(),
        }
        if args.report:
            report_path = Path(args.report)
            if not report_path.is_absolute():
                raise ValueError("capability report path must be absolute")
            report_path = report_path.resolve()
            report_path.parent.mkdir(parents=True, exist_ok=True)
            with report_path.open("xb") as stream:
                stream.write(package_tool.json_bytes(report))
        print(
            "PDR_REGISTRY_LEADER_BACKEND_CAPABILITIES_PASS "
            f"backend={backend.backend_id} "
            f"implementation={manifest['implementationId']} "
            f"protocol={manifest['protocolMajor']}.{manifest['protocolMinor']} "
            f"capabilities={len(manifest['capabilities'])} "
            f"sha256={backend.capability_manifest_sha256}"
        )
        return 0
    except (OSError, UnicodeError, ValueError, RuntimeError,
            json.JSONDecodeError) as error:
        print(
            f"PDR_REGISTRY_LEADER_BACKEND_CAPABILITIES_ERROR: {error}",
            file=sys.stderr,
        )
        return 2


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--backend-config", required=True)
    result.add_argument("--expected-backend-config-sha256", required=True)
    result.add_argument("--authority-id", required=True)
    result.add_argument("--registry-id", required=True)
    result.add_argument("--report")
    result.set_defaults(handler=execute_command)
    return result


def main() -> int:
    args = parser().parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
