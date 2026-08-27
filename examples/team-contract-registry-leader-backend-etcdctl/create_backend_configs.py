#!/usr/bin/env python3
"""Create pinned etcd adapter and PDR external-backend configurations."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


ADAPTER_PRODUCT = "PocoDDSRuntimeTeamContractRegistryLeaderEtcdAdapterConfig"
BACKEND_PRODUCT = "PocoDDSRuntimeTeamContractRegistryLeaderBackendConfig"
REQUIRED_CAPABILITIES = [
    "atomic-compare-and-swap",
    "commit-outcome-reconciliation",
    "immutable-history",
    "linearizable-read-current",
    "scope-confinement",
]
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
ENVIRONMENT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
VERSION_LINE = re.compile(r"^etcdctl version:\s*(\S+)\s*$", re.MULTILINE)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def regular_absolute(value: str, label: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise ValueError(f"{label} must be absolute")
    resolved = path.resolve()
    if path.is_symlink() or resolved.is_symlink() or not resolved.is_file():
        raise ValueError(f"{label} must be a regular non-link file")
    return resolved


def endpoint(value: str) -> str:
    try:
        parsed = urlsplit(value)
        valid = (parsed.scheme == "https" and bool(parsed.hostname)
                 and parsed.port is not None and parsed.username is None
                 and parsed.password is None and not parsed.path
                 and not parsed.query and not parsed.fragment)
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("every etcd endpoint must be an explicit HTTPS host and port")
    return value


def exclusive_json(path_value: str, document: dict[str, Any]) -> tuple[Path, str]:
    path = Path(path_value)
    if not path.is_absolute():
        raise ValueError("configuration output paths must be absolute")
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    content = (json.dumps(document, indent=2, sort_keys=True)
               + "\n").encode("utf-8")
    with path.open("xb") as stream:
        stream.write(content)
    return path, hashlib.sha256(content).hexdigest()


def execute(args: argparse.Namespace) -> int:
    created: list[Path] = []
    try:
        identifiers = [args.adapter_id, args.backend_id,
                       *args.authority_id, *args.registry_id]
        if (any(not IDENTIFIER.fullmatch(item) for item in identifiers)
                or not 1 <= len(args.authority_id) <= 128
                or not 1 <= len(args.registry_id) <= 128
                or len(set(args.authority_id)) != len(args.authority_id)
                or len(set(args.registry_id)) != len(args.registry_id)
                or len(args.etcdctl_argument) > 16
                or any(not item or len(item) > 1024 or "\x00" in item
                       for item in args.etcdctl_argument)
                or len(args.etcdctl_artifact) > 16
                or len(args.etcdctl_environment) > 16
                or not 3 <= len(args.endpoint) <= 9
                or len(set(args.endpoint)) != len(args.endpoint)
                or not re.fullmatch(r"/[A-Za-z0-9._/-]{1,255}", args.key_prefix)
                or args.key_prefix.endswith("/") or "//" in args.key_prefix
                or any(item in {".", ".."}
                       for item in args.key_prefix.split("/"))
                or any(not ENVIRONMENT_NAME.fullmatch(item)
                       for item in args.etcdctl_environment)
                or len(set(args.etcdctl_environment))
                    != len(args.etcdctl_environment)
                or not 1 <= args.dial_timeout_seconds <= 10
                or not args.dial_timeout_seconds
                    <= args.command_timeout_seconds <= 20
                or not 4096 <= args.max_response_bytes <= 4 * 1024 * 1024):
            raise ValueError("configuration arguments are malformed")
        endpoints = [endpoint(item) for item in args.endpoint]
        python = regular_absolute(args.python, "Python executable")
        adapter = regular_absolute(args.adapter, "adapter")
        etcdctl = regular_absolute(args.etcdctl, "etcdctl executable")
        etcdctl_artifacts = [
            regular_absolute(item, "etcdctl artifact")
            for item in args.etcdctl_artifact
        ]
        if len(set(etcdctl_artifacts)) != len(etcdctl_artifacts):
            raise ValueError("etcdctl artifacts must be unique")
        ca = regular_absolute(args.cacert, "etcd CA certificate")
        cert = regular_absolute(args.cert, "etcd client certificate")
        key = regular_absolute(args.key, "etcd client private key")
        version_result = subprocess.run(
            [str(etcdctl), *args.etcdctl_argument, "version"], check=False,
            capture_output=True, text=True, timeout=5,
        )
        match = VERSION_LINE.search(version_result.stdout)
        if version_result.returncode != 0 or match is None:
            raise ValueError("etcdctl version probe failed")
        adapter_document = {
            "schemaVersion": 1, "product": ADAPTER_PRODUCT,
            "adapterId": args.adapter_id, "etcdctl": str(etcdctl),
            "etcdctlSha256": sha256(etcdctl),
            "etcdctlVersion": match.group(1),
            "etcdctlArguments": args.etcdctl_argument,
            "etcdctlArtifactPins": [
                {"path": str(item), "sha256": sha256(item)}
                for item in etcdctl_artifacts
            ],
            "etcdctlEnvironmentVariables": args.etcdctl_environment,
            "endpoints": endpoints, "keyPrefix": args.key_prefix,
            "caCertificate": str(ca), "caCertificateSha256": sha256(ca),
            "clientCertificate": str(cert),
            "clientCertificateSha256": sha256(cert),
            "clientKey": str(key), "clientKeySha256": sha256(key),
            "dialTimeoutSeconds": args.dial_timeout_seconds,
            "commandTimeoutSeconds": args.command_timeout_seconds,
            "maxResponseBytes": args.max_response_bytes,
        }
        adapter_config, adapter_config_sha = exclusive_json(
            args.adapter_config_output, adapter_document
        )
        created.append(adapter_config)
        pins = [adapter, adapter_config, etcdctl, *etcdctl_artifacts, ca, cert, key]
        unique_pins: list[Path] = []
        for item in pins:
            if item not in unique_pins:
                unique_pins.append(item)
        backend_document = {
            "schemaVersion": 2, "product": BACKEND_PRODUCT,
            "backendId": args.backend_id, "kind": "external-command",
            "protocolMajor": 1, "minimumProtocolMinor": 0,
            "requiredCapabilities": REQUIRED_CAPABILITIES,
            "authorityIds": args.authority_id, "registryIds": args.registry_id,
            "executable": str(python), "executableSha256": sha256(python),
            "arguments": [
                str(adapter), "--config", str(adapter_config),
                "--expected-config-sha256", adapter_config_sha,
            ],
            "artifactPins": [
                {"path": str(item), "sha256": sha256(item)}
                for item in unique_pins
            ],
            "environmentVariables": args.etcdctl_environment,
            "timeoutSeconds": min(args.command_timeout_seconds + 2, 30),
            "maxResponseBytes": args.max_response_bytes,
        }
        backend_config, backend_config_sha = exclusive_json(
            args.backend_config_output, backend_document
        )
        created.append(backend_config)
        print(
            "PDR_LEADER_ETCD_CONFIG_PASS "
            f"adapter={args.adapter_id} adapterConfigSha256={adapter_config_sha} "
            f"backend={args.backend_id} backendConfigSha256={backend_config_sha} "
            f"endpoints={len(endpoints)}"
        )
        return 0
    except (OSError, UnicodeError, ValueError, subprocess.SubprocessError) as error:
        for path in reversed(created):
            path.unlink(missing_ok=True)
        print(f"PDR_LEADER_ETCD_CONFIG_ERROR: {error}", file=sys.stderr)
        return 2


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--python", required=True)
    result.add_argument("--adapter", required=True)
    result.add_argument("--adapter-id", required=True)
    result.add_argument("--backend-id", required=True)
    result.add_argument("--authority-id", action="append", required=True)
    result.add_argument("--registry-id", action="append", required=True)
    result.add_argument("--etcdctl", required=True)
    result.add_argument("--etcdctl-argument", action="append", default=[])
    result.add_argument("--etcdctl-artifact", action="append", default=[])
    result.add_argument("--etcdctl-environment", action="append", default=[])
    result.add_argument("--endpoint", action="append", required=True)
    result.add_argument("--key-prefix", required=True)
    result.add_argument("--cacert", required=True)
    result.add_argument("--cert", required=True)
    result.add_argument("--key", required=True)
    result.add_argument("--dial-timeout-seconds", type=int, default=3)
    result.add_argument("--command-timeout-seconds", type=int, default=5)
    result.add_argument("--max-response-bytes", type=int, default=1048576)
    result.add_argument("--adapter-config-output", required=True)
    result.add_argument("--backend-config-output", required=True)
    result.set_defaults(handler=execute)
    return result


def main() -> int:
    args = parser().parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
