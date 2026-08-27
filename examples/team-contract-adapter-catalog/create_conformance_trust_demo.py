#!/usr/bin/env python3
"""Create a local-demo Adapter certifier key pair and trust policy."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


PRODUCT = "PocoDDSRuntimeTeamContractAdapterConformanceTrustPolicy"
KINDS = {
    "adapter-config-resolver", "artifact-store", "control-authorizer",
    "fleet-executor", "registry-leader-backend", "wave-gate",
}
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def output_path(value: str, label: str) -> Path:
    path = Path(value)
    if not path.is_absolute() or path.is_symlink():
        raise ValueError(f"{label} must be an absolute non-link path")
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"{label} already exists")
    return path


def execute(args: argparse.Namespace) -> int:
    try:
        if (any(IDENTIFIER.fullmatch(value) is None for value in (
                args.policy_id, args.certifier_id, args.key_id))
                or args.generation < 1
                or not 60 <= args.maximum_attestation_lifetime_seconds
                    <= 2678400
                or sorted(set(args.adapter_kind)) != sorted(KINDS)
                or not args.adapter_id
                or sorted(set(args.adapter_id)) != sorted(args.adapter_id)
                or any(IDENTIFIER.fullmatch(value) is None
                       for value in args.adapter_id)):
            raise ValueError("demo Adapter trust identity is malformed")
        policy_path = output_path(args.output, "trust policy output")
        private_path = output_path(args.private_key, "private key output")
        public_path = output_path(args.public_key, "public key output")
        try:
            relative_public = public_path.relative_to(policy_path.parent)
        except ValueError as error:
            raise ValueError(
                "public key must be beneath the policy directory"
            ) from error
        if (len(relative_public.parts) != 2
                or relative_public.parts[0] != "keys"):
            raise ValueError("public key must use policy-relative keys/name.pem")
        from cryptography.hazmat.primitives.asymmetric.ed25519 import \
            Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import (
            Encoding, NoEncryption, PrivateFormat, PublicFormat,
        )
        key = Ed25519PrivateKey.generate()
        private_content = key.private_bytes(
            Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()
        )
        public_content = key.public_key().public_bytes(
            Encoding.PEM, PublicFormat.SubjectPublicKeyInfo
        )
        private_descriptor = os.open(
            private_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600
        )
        with os.fdopen(private_descriptor, "wb") as stream:
            stream.write(private_content)
        public_descriptor = os.open(
            public_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644
        )
        with os.fdopen(public_descriptor, "wb") as stream:
            stream.write(public_content)
        now = datetime.now(timezone.utc)
        document = {
            "schemaVersion": 1, "product": PRODUCT,
            "policyId": args.policy_id, "generation": args.generation,
            "maximumAttestationLifetimeSeconds":
                args.maximum_attestation_lifetime_seconds,
            "allowedCertifiers": [{
                "certifierId": args.certifier_id, "keyId": args.key_id,
                "algorithm": "Ed25519",
                "publicKey": relative_public.as_posix(),
                "publicKeySha256": hashlib.sha256(public_content).hexdigest(),
                "adapterKinds": sorted(args.adapter_kind),
                "adapterIds": sorted(args.adapter_id),
                "notBefore": (now - timedelta(minutes=5)).isoformat(),
                "notAfter": (now + timedelta(days=30)).isoformat(),
            }],
            "revokedKeys": [],
        }
        content = (json.dumps(document, indent=2, sort_keys=True)
                   + "\n").encode()
        descriptor = os.open(
            policy_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644
        )
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
        print(
            "PDR_ADAPTER_CONFORMANCE_TRUST_DEMO_PASS "
            f"policy={args.policy_id} generation={args.generation}"
        )
        return 0
    except (OSError, ValueError, ImportError) as error:
        print(f"PDR_ADAPTER_CONFORMANCE_TRUST_DEMO_ERROR: {error}",
              file=sys.stderr)
        return 2


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--policy-id", required=True)
    result.add_argument("--generation", type=int, default=1)
    result.add_argument("--certifier-id", required=True)
    result.add_argument("--key-id", required=True)
    result.add_argument("--adapter-kind", action="append", required=True)
    result.add_argument("--adapter-id", action="append", required=True)
    result.add_argument(
        "--maximum-attestation-lifetime-seconds", type=int, default=3600
    )
    result.add_argument("--private-key", required=True)
    result.add_argument("--public-key", required=True)
    result.add_argument("--output", required=True)
    return result


if __name__ == "__main__":
    raise SystemExit(execute(parser().parse_args()))
