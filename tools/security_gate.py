#!/usr/bin/env python3
"""Validate deploy-time PocoDDSRuntime security invariants."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def properties(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def validate(values: dict[str, str]) -> list[str]:
    errors: list[str] = []
    profile = values.get("security.profile", "development").lower()
    host = values.get("osp.web.server.host", "")
    auth = values.get("osp.web.authServiceName", "")
    try:
        secure_port = int(values.get("osp.web.server.securePort", "0"))
    except ValueError:
        secure_port = 0
    legacy_auth = values.get("auth.simple.enable", "false").lower() == "true"
    loopback = host.lower() in {"127.0.0.1", "::1", "localhost"}
    if profile not in {"development", "production"}:
        errors.append("security.profile must be development or production")
    elif profile == "development" and not loopback and (not auth or secure_port <= 0):
        errors.append("external development binding requires authentication and TLS")
    elif profile == "production":
        if secure_port <= 0:
            errors.append("production requires osp.web.server.securePort")
        if not auth:
            errors.append("production requires osp.web.authServiceName")
        if legacy_auth:
            errors.append("production prohibits legacy SimpleAuth")
        management_required = values.get(
            "pdr.management.authentication.required", "false").lower() == "true"
        try:
            principal_count = int(values.get(
                "pdr.management.authentication.principals.count", "0"))
        except ValueError:
            principal_count = 0
        has_legacy_source = bool(
            values.get("pdr.management.authentication.tokenEnvironment", "") or
            values.get("pdr.management.authentication.tokenFile", "")
        )
        request_id_required = values.get(
            "pdr.management.idempotency.requireRequestId", "false").lower() == "true"
        if not management_required:
            errors.append("production requires management authentication")
        if principal_count <= 0 and not has_legacy_source:
            errors.append("production requires a management identity source")
        if not request_id_required:
            errors.append("production requires management request IDs")
        if any(key.startswith("pdr.serial.") and key.endswith("transport") and
               value.lower() == "loopback" for key, value in values.items()):
            errors.append("production prohibits serial loopback transport")
        if any(key.startswith("pdr.can.") and key.endswith("transport") and
               value.lower() == "loopback" for key, value in values.items()):
            errors.append("production prohibits CAN loopback transport")
        if any(key.startswith("pdr.gnss.") and key.endswith("transport") and
               value.lower() == "loopback" for key, value in values.items()):
            errors.append("production prohibits GNSS loopback transport")
        if any(key.startswith("pdr.xbee.") and key.endswith("transport") and
               value.lower() == "loopback" for key, value in values.items()):
            errors.append("production prohibits XBee loopback transport")
    for key, value in values.items():
        lowered = key.lower()
        reference = lowered.endswith(("file", "path", "environment"))
        if (any(token in lowered for token in ("password", "secret", "token")) and
                value and not reference):
            errors.append(f"inline secret is prohibited: {key}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    args = parser.parse_args()
    errors = validate(properties(args.config))
    if errors:
        for error in errors:
            print(f"SECURITY_ERROR: {error}", file=sys.stderr)
        return 1
    print(f"SECURITY_GATE_PASS config={args.config}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
