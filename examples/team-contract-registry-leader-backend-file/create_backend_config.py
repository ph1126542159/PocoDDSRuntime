#!/usr/bin/env python3
"""Create a digest-pinned config for the PDR file backend SDK example."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path


PRODUCT = "PocoDDSRuntimeTeamContractRegistryLeaderBackendConfig"
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
ENVIRONMENT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
REQUIRED_CAPABILITIES = [
    "atomic-compare-and-swap",
    "commit-outcome-reconciliation",
    "immutable-history",
    "linearizable-read-current",
    "scope-confinement",
]


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
                or (args.required_environment is not None
                    and not ENVIRONMENT_NAME.fullmatch(
                        args.required_environment))
                or not 1 <= args.timeout_seconds <= 30
                or not args.timeout_seconds + 1
                    <= args.minimum_credential_lease_seconds <= 3600
                or not 1024 <= args.max_response_bytes <= 1024 * 1024):
            raise ValueError("backend configuration arguments are malformed")
        executable = regular_absolute(args.python, "Python executable")
        adapter = regular_absolute(args.adapter, "adapter")
        credential_bindings = []
        secret_provider = None
        if args.credential or args.rotating_credential:
            if not args.secret_provider_config:
                raise ValueError(
                    "credential bindings require --secret-provider-config"
                )
            provider_path = regular_absolute(
                args.secret_provider_config, "secret provider config"
            )
            provider_document = json.loads(provider_path.read_bytes())
            provider_id = str(provider_document.get("providerId", "")) \
                if isinstance(provider_document, dict) else ""
            if not IDENTIFIER.fullmatch(provider_id):
                raise ValueError("secret provider identity is malformed")
            seen_names: set[str] = set()
            seen_references: set[str] = set()
            for environment_variable, secret_id, version in args.credential:
                ref_key = json.dumps(
                    [secret_id, version], separators=(",", ":")
                )
                if (not ENVIRONMENT_NAME.fullmatch(environment_variable)
                        or environment_variable == args.root_environment
                        or environment_variable in seen_names
                        or not IDENTIFIER.fullmatch(secret_id)
                        or not IDENTIFIER.fullmatch(version)
                        or ref_key in seen_references):
                    raise ValueError(
                        "credential binding is malformed or duplicated"
                    )
                credential_bindings.append({
                    "environmentVariable": environment_variable,
                    "secretRef": {
                        "kind": "secret-ref", "providerId": provider_id,
                        "secretId": secret_id, "version": version,
                    },
                })
                seen_names.add(environment_variable)
                seen_references.add(ref_key)
            for (environment_variable, secret_id, preferred_version,
                 fallback_version, fallback_until) in args.rotating_credential:
                try:
                    deadline = datetime.fromisoformat(
                        fallback_until.replace("Z", "+00:00")
                    )
                except ValueError as error:
                    raise ValueError(
                        "credential rotation deadline is malformed"
                    ) from error
                ref_key = json.dumps(
                    [secret_id, preferred_version, fallback_version,
                     fallback_until], separators=(",", ":")
                )
                if (not ENVIRONMENT_NAME.fullmatch(environment_variable)
                        or environment_variable == args.root_environment
                        or environment_variable in seen_names
                        or any(not IDENTIFIER.fullmatch(item) for item in (
                            secret_id, preferred_version, fallback_version))
                        or preferred_version == fallback_version
                        or deadline.tzinfo is None
                        or ref_key in seen_references):
                    raise ValueError(
                        "rotating credential binding is malformed or duplicated"
                    )
                credential_bindings.append({
                    "environmentVariable": environment_variable,
                    "secretRef": {
                        "kind": "secret-rotation-ref",
                        "providerId": provider_id, "secretId": secret_id,
                        "versions": [preferred_version, fallback_version],
                        "fallbackUntil": deadline.isoformat(),
                    },
                })
                seen_names.add(environment_variable)
                seen_references.add(ref_key)
            if (args.rotating_credential
                    and provider_document.get("schemaVersion") != 2):
                raise ValueError("credential rotation requires provider v2")
            secret_provider = {
                "kind": "external-command", "providerId": provider_id,
                "configPath": str(provider_path),
                "configSha256": digest(provider_path),
            }
            if (args.required_environment is not None
                    and args.required_environment not in seen_names):
                raise ValueError(
                    "required environment must name a credential binding"
                )
        elif args.required_environment is not None:
            raise ValueError(
                "required environment requires a credential binding"
            )
        output = Path(args.output)
        if not output.is_absolute():
            raise ValueError("output must be absolute")
        output = output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        document = {
            "schemaVersion": 4 if args.rotating_credential
                else (3 if credential_bindings else 2),
            "product": PRODUCT,
            "backendId": args.backend_id, "kind": "external-command",
            "protocolMajor": 1, "minimumProtocolMinor": 0,
            "requiredCapabilities": REQUIRED_CAPABILITIES,
            "authorityIds": args.authority_id,
            "registryIds": args.registry_id,
            "executable": str(executable),
            "executableSha256": digest(executable),
            "arguments": [
                str(adapter), "--root-environment", args.root_environment,
            ] + ([
                "--required-environment", args.required_environment,
            ] if args.required_environment else []),
            "artifactPins": [{"path": str(adapter), "sha256": digest(adapter)}],
            "environmentVariables": [args.root_environment],
            "timeoutSeconds": args.timeout_seconds,
            "maxResponseBytes": args.max_response_bytes,
        }
        if credential_bindings:
            document["secretProvider"] = secret_provider
            document["credentialBindings"] = credential_bindings
        if args.rotating_credential:
            document["minimumCredentialLeaseSeconds"] = \
                args.minimum_credential_lease_seconds
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
    result.add_argument("--secret-provider-config")
    result.add_argument("--required-environment")
    result.add_argument(
        "--credential", nargs=3, action="append", default=[],
        metavar=("ENVIRONMENT_VARIABLE", "SECRET_ID", "VERSION"),
        help="Generate schema v3 and inject a version-pinned secret per request",
    )
    result.add_argument(
        "--rotating-credential", nargs=5, action="append", default=[],
        metavar=("ENVIRONMENT_VARIABLE", "SECRET_ID", "PREFERRED_VERSION",
                 "FALLBACK_VERSION", "FALLBACK_UNTIL"),
        help="Generate schema v4 with an explicit dual-version fallback window",
    )
    result.add_argument(
        "--minimum-credential-lease-seconds", type=int, default=10
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
