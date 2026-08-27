#!/usr/bin/env python3
"""Sign and verify portable Adapter conformance attestations."""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any

import team_contract_adapter_conformance as conformance_tool
import team_contract_adapter_runtime as adapter_runtime
import team_contract_package as package_tool
import team_contract_registry as registry_tool


ATTESTATION_PRODUCT = \
    "PocoDDSRuntimeTeamContractAdapterConformanceAttestation"
POLICY_PRODUCT = \
    "PocoDDSRuntimeTeamContractAdapterConformanceTrustPolicy"
MAX_LIFETIME = 2678400
PUBLIC_KEY = re.compile(r"keys/[A-Za-z0-9._-]+\.pem")


def canonical_payload(document: dict[str, Any]) -> bytes:
    return package_tool.canonical_bytes({
        key: value for key, value in document.items() if key != "signature"
    })


def signature_bytes(value: Any) -> bytes:
    try:
        result = base64.b64decode(value, validate=True)
    except (TypeError, ValueError) as error:
        raise ValueError(
            "Adapter conformance signature encoding is invalid"
        ) from error
    if len(result) != 64:
        raise ValueError("Adapter conformance Ed25519 signature is invalid")
    return result


def validate_attestation(document: Any) -> None:
    fields = {
        "schemaVersion", "product", "operation", "certifierId", "keyId",
        "evidenceSha256", "conformanceId", "adapterKind", "adapterId",
        "configSha256", "scope", "issuedAt", "expiresAt", "signature",
    }
    if (not isinstance(document, dict) or set(document) != fields
            or document.get("schemaVersion") != 1
            or document.get("product") != ATTESTATION_PRODUCT
            or document.get("operation")
                != "adapter-conformance-attest"
            or any(package_tool.IDENTIFIER.fullmatch(str(
                document.get(name, ""))) is None
                for name in ("certifierId", "keyId", "adapterId"))
            or document.get("adapterKind")
                not in conformance_tool.SUPPORTED_KINDS
            or any(package_tool.SHA256.fullmatch(str(
                document.get(name, ""))) is None for name in (
                    "evidenceSha256", "conformanceId", "configSha256",
                ))
            or not isinstance(document.get("scope"), dict)
            or set(document["scope"]) != {"primaryId", "secondaryId"}):
        raise ValueError("Adapter conformance attestation is malformed")
    conformance_tool._scope(
        document["scope"]["primaryId"],
        document["scope"]["secondaryId"], document["adapterKind"],
    )
    issued = package_tool.parse_time(document["issuedAt"], "issuedAt")
    expires = package_tool.parse_time(document["expiresAt"], "expiresAt")
    if issued >= expires or (expires - issued).total_seconds() > MAX_LIFETIME:
        raise ValueError("Adapter conformance attestation lifetime is invalid")
    signature_bytes(document["signature"])


def validate_policy(document: Any) -> None:
    fields = {
        "schemaVersion", "product", "policyId", "generation",
        "maximumAttestationLifetimeSeconds", "allowedCertifiers",
        "revokedKeys",
    }
    if (not isinstance(document, dict) or set(document) != fields
            or document.get("schemaVersion") != 1
            or document.get("product") != POLICY_PRODUCT
            or package_tool.IDENTIFIER.fullmatch(str(
                document.get("policyId", ""))) is None
            or type(document.get("generation")) is not int
            or not 1 <= document["generation"] <= 2147483647
            or type(document.get("maximumAttestationLifetimeSeconds"))
                is not int
            or not 60 <= document["maximumAttestationLifetimeSeconds"]
                <= MAX_LIFETIME
            or not isinstance(document.get("allowedCertifiers"), list)
            or not document["allowedCertifiers"]
            or len(document["allowedCertifiers"]) > 256
            or not isinstance(document.get("revokedKeys"), list)
            or len(document["revokedKeys"]) > 256):
        raise ValueError(
            "Adapter conformance trust policy is malformed"
        )
    keys: set[str] = set()
    entry_fields = {
        "certifierId", "keyId", "algorithm", "publicKey",
        "publicKeySha256", "adapterKinds", "adapterIds", "notBefore",
        "notAfter",
    }
    for entry in document["allowedCertifiers"]:
        if (not isinstance(entry, dict) or set(entry) != entry_fields
                or any(package_tool.IDENTIFIER.fullmatch(str(
                    entry.get(name, ""))) is None
                    for name in ("certifierId", "keyId"))
                or entry.get("algorithm") != "Ed25519"
                or PUBLIC_KEY.fullmatch(str(entry.get("publicKey", "")))
                    is None
                or package_tool.SHA256.fullmatch(str(
                    entry.get("publicKeySha256", ""))) is None
                or not isinstance(entry.get("adapterKinds"), list)
                or entry["adapterKinds"] != sorted(set(
                    entry["adapterKinds"]))
                or not entry["adapterKinds"]
                or any(kind not in conformance_tool.SUPPORTED_KINDS
                       for kind in entry["adapterKinds"])
                or not isinstance(entry.get("adapterIds"), list)
                or entry["adapterIds"] != sorted(set(entry["adapterIds"]))
                or not entry["adapterIds"]
                or any(package_tool.IDENTIFIER.fullmatch(str(value)) is None
                       for value in entry["adapterIds"])
                or entry["keyId"] in keys):
            raise ValueError(
                "Adapter conformance trust policy certifier is malformed"
            )
        if package_tool.parse_time(entry["notBefore"], "notBefore") >= \
                package_tool.parse_time(entry["notAfter"], "notAfter"):
            raise ValueError(
                "Adapter conformance certifier validity window is reversed"
            )
        keys.add(entry["keyId"])
    revoked: set[str] = set()
    for entry in document["revokedKeys"]:
        if (not isinstance(entry, dict) or set(entry) != {
                "keyId", "revokedAt", "reason"
                } or package_tool.IDENTIFIER.fullmatch(str(
                    entry.get("keyId", ""))) is None
                or not isinstance(entry.get("reason"), str)
                or not entry["reason"] or len(entry["reason"]) > 512
                or entry["keyId"] in revoked):
            raise ValueError(
                "Adapter conformance trust policy revocation is malformed"
            )
        package_tool.parse_time(entry["revokedAt"], "revokedAt")
        revoked.add(entry["keyId"])


def load_policy(path_value: str | Path, expected_sha256: str,
                *, expected_policy_id: str, minimum_generation: int) \
        -> tuple[dict[str, Any], Path, str]:
    policy, path, digest = adapter_runtime.load_pinned_json(
        path_value, expected_sha256, "Adapter conformance trust policy",
        validate_policy,
    )
    if (policy["policyId"] != expected_policy_id
            or policy["generation"] < minimum_generation):
        raise ValueError(
            "Adapter conformance trust policy identity or generation changed"
        )
    return policy, path, digest


def private_key(args: argparse.Namespace) -> Any:
    value = os.environ.get(args.private_key_environment)
    if not value:
        raise ValueError("Adapter certifier private key environment is unset")
    path = package_tool.resolved_path(value, "Adapter certifier private key")
    passphrase = None
    if args.private_key_passphrase_environment:
        secret = os.environ.get(args.private_key_passphrase_environment)
        if secret is None:
            raise ValueError("Adapter certifier passphrase environment is unset")
        passphrase = secret.encode()
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import \
            Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import \
            load_pem_private_key
    except ImportError as error:
        raise ValueError("Ed25519 signing requires cryptography") from error
    key = load_pem_private_key(path.read_bytes(), password=passphrase)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("Adapter certifier private key is not Ed25519")
    return key


def attest_command(args: argparse.Namespace) -> int:
    try:
        evidence, _, evidence_sha = adapter_runtime.load_pinned_json(
            args.evidence, args.expected_evidence_sha256,
            "Adapter conformance evidence", conformance_tool.validate_evidence,
        )
        if (not package_tool.IDENTIFIER.fullmatch(args.certifier_id)
                or not package_tool.IDENTIFIER.fullmatch(args.key_id)
                or not 60 <= args.lifetime_seconds <= MAX_LIFETIME):
            raise ValueError("Adapter certifier identity or lifetime is invalid")
        issued = package_tool.verification_time(args.issued_at)
        document = {
            "schemaVersion": 1, "product": ATTESTATION_PRODUCT,
            "operation": "adapter-conformance-attest",
            "certifierId": args.certifier_id, "keyId": args.key_id,
            "evidenceSha256": evidence_sha,
            "conformanceId": evidence["conformanceId"],
            "adapterKind": evidence["adapterKind"],
            "adapterId": evidence["adapterId"],
            "configSha256": evidence["configSha256"],
            "scope": evidence["scope"], "issuedAt": issued.isoformat(),
            "expiresAt": (issued + timedelta(
                seconds=args.lifetime_seconds
            )).isoformat(),
            "signature": "",
        }
        document["signature"] = base64.b64encode(
            private_key(args).sign(canonical_payload(document))
        ).decode("ascii")
        validate_attestation(document)
        package_tool.write_json(Path(args.report).resolve(), document)
        print(
            "PDR_ADAPTER_CONFORMANCE_ATTEST_PASS "
            f"kind={evidence['adapterKind']} adapter={evidence['adapterId']} "
            f"certifier={args.certifier_id} key={args.key_id}"
        )
        return 0
    except (OSError, UnicodeError, ValueError, RuntimeError,
            json.JSONDecodeError) as error:
        print(f"PDR_ADAPTER_CONFORMANCE_ATTEST_ERROR: {error}", file=sys.stderr)
        return 2


def verify_attestation(
        attestation_path: str | Path, expected_attestation_sha256: str,
        evidence: dict[str, Any], evidence_sha256: str,
        policy: dict[str, Any], policy_path: Path,
        verification_time: str | None = None) -> dict[str, Any]:
    attestation, _, attestation_sha = adapter_runtime.load_pinned_json(
        attestation_path, expected_attestation_sha256,
        "Adapter conformance attestation", validate_attestation,
    )
    expected = {
        "evidenceSha256": evidence_sha256,
        "conformanceId": evidence["conformanceId"],
        "adapterKind": evidence["adapterKind"],
        "adapterId": evidence["adapterId"],
        "configSha256": evidence["configSha256"],
        "scope": evidence["scope"],
    }
    if any(attestation[name] != value for name, value in expected.items()):
        raise ValueError("Adapter conformance attestation evidence changed")
    at = package_tool.verification_time(verification_time)
    issued = package_tool.parse_time(attestation["issuedAt"], "issuedAt")
    expires = package_tool.parse_time(attestation["expiresAt"], "expiresAt")
    if (issued > at + timedelta(minutes=5) or at >= expires
            or (expires - issued).total_seconds()
                > policy["maximumAttestationLifetimeSeconds"]):
        raise ValueError(
            "Adapter conformance attestation is expired, future or too long"
        )
    revoked = {item["keyId"] for item in policy["revokedKeys"]}
    matches = [item for item in policy["allowedCertifiers"]
               if item["certifierId"] == attestation["certifierId"]
               and item["keyId"] == attestation["keyId"]]
    if len(matches) != 1 or attestation["keyId"] in revoked:
        raise ValueError(
            "Adapter conformance certifier is untrusted or revoked"
        )
    certifier = matches[0]
    if (attestation["adapterKind"] not in certifier["adapterKinds"]
            or attestation["adapterId"] not in certifier["adapterIds"]
            or issued < package_tool.parse_time(
                certifier["notBefore"], "notBefore")
            or at >= package_tool.parse_time(
                certifier["notAfter"], "notAfter")):
        raise ValueError(
            "Adapter conformance certifier scope or validity is untrusted"
        )
    public_key = package_tool.policy_public_key(
        policy_path, certifier["publicKey"]
    )
    public_sha = package_tool.sha256_file(public_key)
    if public_sha != certifier["publicKeySha256"]:
        raise ValueError("Adapter certifier public key SHA is untrusted")
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import \
            Ed25519PublicKey
        from cryptography.hazmat.primitives.serialization import \
            load_pem_public_key
        key = load_pem_public_key(public_key.read_bytes())
        if not isinstance(key, Ed25519PublicKey):
            raise ValueError("Adapter certifier public key is not Ed25519")
        key.verify(
            signature_bytes(attestation["signature"]),
            canonical_payload(attestation),
        )
    except Exception as error:
        raise ValueError(
            "Adapter conformance attestation signature failed"
        ) from error
    return {
        "attestationSha256": attestation_sha,
        "certifierId": attestation["certifierId"],
        "keyId": attestation["keyId"],
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--evidence", required=True)
    result.add_argument("--expected-evidence-sha256", required=True)
    result.add_argument("--certifier-id", required=True)
    result.add_argument("--key-id", required=True)
    result.add_argument("--private-key-environment", required=True)
    result.add_argument("--private-key-passphrase-environment")
    result.add_argument("--issued-at")
    result.add_argument("--lifetime-seconds", type=int, default=3600)
    result.add_argument("--report", required=True)
    return result


def main() -> int:
    return attest_command(parser().parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
