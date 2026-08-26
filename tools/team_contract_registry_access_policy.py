#!/usr/bin/env python3
"""Sign, verify and atomically activate remote Registry access-policy revisions."""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from pathlib import Path
from typing import Any

import team_contract_impact as impact_tool
import team_contract_package as package_tool
import team_contract_registry as registry_tool


POLICY_PRODUCT = "PocoDDSRuntimeTeamContractRegistryAccessPolicy"
TRUST_POLICY_PRODUCT = "PocoDDSRuntimeTeamContractRegistryAccessPolicyTrustPolicy"
ROLES = {"reader", "publisher", "promoter", "rollback", "auditor", "operator"}
V1_FIELDS = {
    "schemaVersion", "product", "policyId", "registryId", "maxRequestBytes",
    "maxResponseBytes", "principals", "revokedTokenSha256",
}
V2_FIELDS = V1_FIELDS | {
    "policyRevision", "previousPolicySha256", "issuedAt", "controlLimits", "signer",
}
DEFAULT_CONTROL_LIMITS = {
    "maxActiveRequestRecords": 100000,
    "maxRecoveryRecords": 100000,
    "maxAuditRecords": 1000000,
    "maxControlBytes": 4 * 1024 * 1024 * 1024,
}


def validate_control_limits(limits: Any) -> None:
    fields = {
        "maxActiveRequestRecords", "maxRecoveryRecords", "maxAuditRecords",
        "maxControlBytes",
    }
    if (not isinstance(limits, dict) or set(limits) != fields
            or type(limits.get("maxActiveRequestRecords")) is not int
            or not 1 <= limits["maxActiveRequestRecords"] <= 1_000_000
            or type(limits.get("maxRecoveryRecords")) is not int
            or not 1 <= limits["maxRecoveryRecords"] <= 1_000_000
            or type(limits.get("maxAuditRecords")) is not int
            or not 2 <= limits["maxAuditRecords"] <= 10_000_000
            or type(limits.get("maxControlBytes")) is not int
            or not 1024 * 1024 <= limits["maxControlBytes"] <= 1024 ** 4):
        raise ValueError("Registry remote access-policy control limits are malformed")


def validate_policy(policy: Any) -> None:
    version = policy.get("schemaVersion") if isinstance(policy, dict) else None
    expected_fields = V1_FIELDS if version == 1 else V2_FIELDS if version == 2 else set()
    if (not isinstance(policy, dict) or set(policy) != expected_fields
            or policy.get("product") != POLICY_PRODUCT
            or not package_tool.IDENTIFIER.fullmatch(str(policy.get("policyId", "")))
            or not package_tool.IDENTIFIER.fullmatch(str(policy.get("registryId", "")))
            or type(policy.get("maxRequestBytes")) is not int
            or not 4096 <= policy["maxRequestBytes"] <= 64 * 1024 * 1024
            or type(policy.get("maxResponseBytes")) is not int
            or not 4096 <= policy["maxResponseBytes"] <= 64 * 1024 * 1024
            or not isinstance(policy.get("principals"), list) or not policy["principals"]
            or len(policy["principals"]) > 256
            or not isinstance(policy.get("revokedTokenSha256"), list)
            or len(policy["revokedTokenSha256"]) > 256
            or len(policy["revokedTokenSha256"])
                != len(set(policy["revokedTokenSha256"]))
            or any(not package_tool.SHA256.fullmatch(str(value))
                   for value in policy["revokedTokenSha256"])):
        raise ValueError("Registry remote access policy is malformed")
    principal_fields = {
        "principalId", "tokenSha256", "roles", "packageIds", "channels",
        "notBefore", "notAfter",
    }
    principal_ids: set[str] = set()
    tokens: set[str] = set()
    for principal in policy["principals"]:
        if (not isinstance(principal, dict) or set(principal) != principal_fields
                or not package_tool.IDENTIFIER.fullmatch(
                    str(principal.get("principalId", "")))
                or not package_tool.SHA256.fullmatch(
                    str(principal.get("tokenSha256", "")))
                or principal["principalId"] in principal_ids
                or principal["tokenSha256"] in tokens
                or not isinstance(principal.get("roles"), list) or not principal["roles"]
                or len(principal["roles"]) != len(set(principal["roles"]))
                or any(role not in ROLES for role in principal["roles"])
                or not isinstance(principal.get("packageIds"), list)
                or len(principal["packageIds"]) > 256
                or len(principal["packageIds"]) != len(set(principal["packageIds"]))
                or any(not package_tool.IDENTIFIER.fullmatch(str(value))
                       for value in principal["packageIds"])
                or not isinstance(principal.get("channels"), list)
                or len(principal["channels"]) > registry_tool.MAX_CHANNELS
                or len(principal["channels"]) != len(set(principal["channels"]))
                or any(not package_tool.IDENTIFIER.fullmatch(str(value))
                       for value in principal["channels"])):
            raise ValueError("Registry remote access principal is malformed")
        before = package_tool.parse_time(principal["notBefore"], "principal notBefore")
        after = package_tool.parse_time(principal["notAfter"], "principal notAfter")
        if before >= after:
            raise ValueError("Registry remote principal validity window is reversed")
        if "publisher" in principal["roles"] and not principal["packageIds"]:
            raise ValueError("remote publisher requires an explicit package scope")
        if ({"promoter", "rollback"} & set(principal["roles"])) \
                and not principal["channels"]:
            raise ValueError("remote promotion roles require an explicit channel scope")
        principal_ids.add(principal["principalId"])
        tokens.add(principal["tokenSha256"])
    if version == 2:
        if (type(policy.get("policyRevision")) is not int
                or policy["policyRevision"] < 1
                or not package_tool.SHA256.fullmatch(
                    str(policy.get("previousPolicySha256", "")))):
            raise ValueError("signed access-policy revision linkage is malformed")
        package_tool.parse_time(policy.get("issuedAt"), "access policy issuedAt")
        validate_control_limits(policy.get("controlLimits"))
        signer = policy.get("signer")
        if (not isinstance(signer, dict)
                or set(signer) != {"keyId", "algorithm", "signature"}
                or not package_tool.IDENTIFIER.fullmatch(str(signer.get("keyId", "")))
                or signer.get("algorithm") != "Ed25519"
                or not isinstance(signer.get("signature"), str)):
            raise ValueError("signed access-policy signer is malformed")
        try:
            signature = base64.b64decode(signer["signature"], validate=True)
        except (ValueError, TypeError) as error:
            raise ValueError("signed access-policy signature encoding is invalid") from error
        if len(signature) != 64:
            raise ValueError("signed access-policy Ed25519 signature length is invalid")


def control_limits(policy: dict[str, Any]) -> dict[str, int]:
    return dict(policy["controlLimits"] if policy["schemaVersion"] == 2
                else DEFAULT_CONTROL_LIMITS)


def policy_payload(policy: dict[str, Any]) -> dict[str, Any]:
    payload = dict(policy)
    signer = dict(payload["signer"])
    signer.pop("signature", None)
    payload["signer"] = signer
    return payload


def validate_trust_policy(policy: Any) -> None:
    fields = {"schemaVersion", "product", "policyId", "allowedSigners", "revokedKeys"}
    if (not isinstance(policy, dict) or set(policy) != fields
            or policy.get("schemaVersion") != 1
            or policy.get("product") != TRUST_POLICY_PRODUCT
            or not package_tool.IDENTIFIER.fullmatch(str(policy.get("policyId", "")))
            or not isinstance(policy.get("allowedSigners"), list)
            or not policy["allowedSigners"] or len(policy["allowedSigners"]) > 64
            or not isinstance(policy.get("revokedKeys"), list)
            or len(policy["revokedKeys"]) > 64):
        raise ValueError("Registry access-policy signer trust policy is malformed")
    signer_fields = {
        "keyId", "algorithm", "publicKey", "publicKeySha256", "registryIds",
        "policyIds", "notBefore", "notAfter",
    }
    key_ids: set[str] = set()
    for signer in policy["allowedSigners"]:
        if (not isinstance(signer, dict) or set(signer) != signer_fields
                or not package_tool.IDENTIFIER.fullmatch(str(signer.get("keyId", "")))
                or signer["keyId"] in key_ids or signer.get("algorithm") != "Ed25519"
                or not isinstance(signer.get("publicKey"), str)
                or Path(signer["publicKey"]).is_absolute()
                or len(Path(signer["publicKey"]).parts) != 2
                or Path(signer["publicKey"]).parts[0] != "keys"
                or not package_tool.SHA256.fullmatch(
                    str(signer.get("publicKeySha256", "")))
                or any(not isinstance(signer.get(name), list) or not signer[name]
                       or len(signer[name]) > 128
                       or len(signer[name]) != len(set(signer[name]))
                       or any(not package_tool.IDENTIFIER.fullmatch(str(value))
                              for value in signer[name])
                       for name in ("registryIds", "policyIds"))):
            raise ValueError("Registry access-policy trusted signer is malformed")
        before = package_tool.parse_time(signer["notBefore"], "signer notBefore")
        after = package_tool.parse_time(signer["notAfter"], "signer notAfter")
        if before >= after:
            raise ValueError("Registry access-policy signer validity is reversed")
        key_ids.add(signer["keyId"])
    revoked_ids: set[str] = set()
    for revoked in policy["revokedKeys"]:
        if (not isinstance(revoked, dict)
                or set(revoked) != {"keyId", "revokedAt", "reason"}
                or not package_tool.IDENTIFIER.fullmatch(str(revoked.get("keyId", "")))
                or revoked["keyId"] in revoked_ids
                or not isinstance(revoked.get("reason"), str)
                or not 1 <= len(revoked["reason"]) <= 512):
            raise ValueError("Registry access-policy signer revocation is malformed")
        package_tool.parse_time(revoked["revokedAt"], "signer revokedAt")
        revoked_ids.add(revoked["keyId"])


def load_trust_policy(path: str | Path, expected_id: str,
                      expected_sha: str) -> tuple[dict[str, Any], str, Path]:
    policy_path = package_tool.resolved_path(path, "Registry access-policy signer trust")
    policy, actual_sha = impact_tool.load_json(
        policy_path, "Registry access-policy signer trust"
    )
    if (policy.get("policyId") != expected_id
            or not package_tool.SHA256.fullmatch(str(expected_sha).lower())
            or actual_sha != str(expected_sha).lower()):
        raise ValueError("Registry access-policy signer trust identity is not pinned")
    validate_trust_policy(policy)
    return policy, actual_sha, policy_path


def verify_signed_policy(policy: dict[str, Any], trust: dict[str, Any],
                         trust_path: Path, at: Any) -> dict[str, str]:
    validate_policy(policy)
    if policy["schemaVersion"] != 2:
        raise ValueError("hot-reload access policy must be a signed revision")
    issued_at = package_tool.parse_time(policy["issuedAt"], "access policy issuedAt")
    if issued_at > at:
        raise ValueError("access policy was issued in the future")
    key_id = policy["signer"]["keyId"]
    matches = [item for item in trust["allowedSigners"]
               if item["keyId"] == key_id
               and policy["registryId"] in item["registryIds"]
               and policy["policyId"] in item["policyIds"]]
    if len(matches) != 1:
        raise ValueError("access-policy signer is not trusted for this scope")
    signer = matches[0]
    if (issued_at < package_tool.parse_time(signer["notBefore"], "signer notBefore")
            or issued_at >= package_tool.parse_time(signer["notAfter"], "signer notAfter")):
        raise ValueError("access policy is outside signer validity")
    for revoked in trust["revokedKeys"]:
        if (revoked["keyId"] == key_id
                and at >= package_tool.parse_time(revoked["revokedAt"], "signer revokedAt")):
            raise ValueError("access-policy signer key was revoked")
    public_path = registry_tool.safe_member(
        trust_path.parent, signer["publicKey"], "access-policy signer public key"
    )
    public_bytes = public_path.read_bytes()
    if package_tool.sha256_bytes(public_bytes) != signer["publicKeySha256"]:
        raise ValueError("access-policy signer public key digest changed")
    try:
        signature = base64.b64decode(policy["signer"]["signature"], validate=True)
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        from cryptography.hazmat.primitives.serialization import load_pem_public_key
        key = load_pem_public_key(public_bytes)
        if not isinstance(key, Ed25519PublicKey):
            raise ValueError("access-policy signer public key is not Ed25519")
        key.verify(signature, package_tool.canonical_bytes(policy_payload(policy)))
    except ImportError as error:
        raise ValueError("access-policy verification requires cryptography") from error
    except Exception as error:
        if isinstance(error, ValueError):
            raise
        raise ValueError("access-policy Ed25519 verification failed") from error
    return {"keyId": key_id, "publicKeySha256": signer["publicKeySha256"]}


def load_policy_bytes(path: str | Path) -> tuple[dict[str, Any], str, bytes, Path]:
    policy_path = package_tool.resolved_path(path, "Registry remote access policy")
    content = policy_path.read_bytes()
    try:
        policy = json.loads(content)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("Registry remote access policy is invalid JSON") from error
    validate_policy(policy)
    return policy, package_tool.sha256_bytes(content), content, policy_path


def sign_command(args: argparse.Namespace) -> int:
    try:
        base, _, _, _ = load_policy_bytes(args.input)
        if base["schemaVersion"] != 1:
            raise ValueError("access-policy signing input must use bootstrap schema v1")
        previous_sha = str(args.expected_previous_policy_sha256).lower()
        if not package_tool.SHA256.fullmatch(previous_sha):
            raise ValueError("access-policy predecessor SHA is malformed")
        key_value = os.environ.get(args.private_key_environment)
        if not key_value:
            raise ValueError("access-policy private key environment is unset")
        passphrase = None
        if args.private_key_passphrase_environment:
            value = os.environ.get(args.private_key_passphrase_environment)
            if value is None:
                raise ValueError("access-policy passphrase environment is unset")
            passphrase = value.encode("utf-8")
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
            from cryptography.hazmat.primitives.serialization import load_pem_private_key
        except ImportError as error:
            raise ValueError("access-policy signing requires cryptography") from error
        key = load_pem_private_key(Path(key_value).resolve().read_bytes(), password=passphrase)
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError("access-policy private key is not Ed25519")
        signed = dict(base)
        signed.update({
            "schemaVersion": 2,
            "policyRevision": args.policy_revision,
            "previousPolicySha256": previous_sha,
            "issuedAt": registry_tool.utc_time(args.issued_at),
            "controlLimits": {
                "maxActiveRequestRecords": args.max_active_request_records,
                "maxRecoveryRecords": args.max_recovery_records,
                "maxAuditRecords": args.max_audit_records,
                "maxControlBytes": args.max_control_bytes,
            },
            "signer": {"keyId": args.key_id, "algorithm": "Ed25519"},
        })
        validate_control_limits(signed["controlLimits"])
        signed["signer"]["signature"] = base64.b64encode(
            key.sign(package_tool.canonical_bytes(signed))
        ).decode("ascii")
        validate_policy(signed)
        output = Path(args.output).resolve()
        registry_tool.exclusive_bytes(output, package_tool.json_bytes(signed))
        print(
            "PDR_TEAM_CONTRACT_REGISTRY_ACCESS_POLICY_SIGN_PASS "
            f"revision={signed['policyRevision']} output={output}"
        )
        return 0
    except (OSError, UnicodeError, ValueError) as error:
        print(f"PDR_TEAM_CONTRACT_REGISTRY_ACCESS_POLICY_ERROR: {error}", file=sys.stderr)
        return 2


def activate_command(args: argparse.Namespace) -> int:
    try:
        current, current_sha, _, active_path = load_policy_bytes(args.active_policy)
        if current_sha != str(args.expected_current_policy_sha256).lower():
            raise ValueError("active access-policy SHA changed before activation")
        candidate, candidate_sha, candidate_bytes, _ = load_policy_bytes(args.candidate)
        trust, trust_sha, trust_path = load_trust_policy(
            args.trust_policy, args.expected_trust_policy_id,
            args.expected_trust_policy_sha256,
        )
        signer = verify_signed_policy(
            candidate, trust, trust_path,
            package_tool.verification_time(args.verification_time),
        )
        current_revision = current.get("policyRevision", 0)
        if (candidate["policyId"] != current["policyId"]
                or candidate["registryId"] != current["registryId"]
                or candidate["policyRevision"] != current_revision + 1
                or candidate["previousPolicySha256"] != current_sha):
            raise ValueError("candidate access-policy revision is not the exact successor")
        temporary = active_path.with_name(active_path.name + ".activate.tmp")
        try:
            temporary.write_bytes(candidate_bytes)
            os.replace(temporary, active_path)
        finally:
            temporary.unlink(missing_ok=True)
        report = {
            "schemaVersion": 1,
            "product": "PocoDDSRuntimeTeamContractRegistryAccessPolicyActivation",
            "passed": True,
            "policyId": candidate["policyId"],
            "registryId": candidate["registryId"],
            "previousPolicySha256": current_sha,
            "policyRevision": candidate["policyRevision"],
            "policySha256": candidate_sha,
            "signerKeyId": signer["keyId"],
            "signerPublicKeySha256": signer["publicKeySha256"],
            "trustPolicyId": trust["policyId"],
            "trustPolicySha256": trust_sha,
            "activatedAt": registry_tool.utc_time(args.verification_time),
        }
        if args.report:
            package_tool.write_json(Path(args.report).resolve(), report)
        print(
            "PDR_TEAM_CONTRACT_REGISTRY_ACCESS_POLICY_ACTIVATE_PASS "
            f"revision={candidate['policyRevision']} sha256={candidate_sha}"
        )
        return 0
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        print(f"PDR_TEAM_CONTRACT_REGISTRY_ACCESS_POLICY_ERROR: {error}", file=sys.stderr)
        return 2


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    sign = commands.add_parser("sign", help="create an exact signed successor policy")
    sign.add_argument("--input", required=True)
    sign.add_argument("--expected-previous-policy-sha256", required=True)
    sign.add_argument("--policy-revision", type=int, required=True)
    sign.add_argument("--issued-at")
    sign.add_argument("--key-id", required=True)
    sign.add_argument("--private-key-environment", required=True)
    sign.add_argument("--private-key-passphrase-environment")
    sign.add_argument("--max-active-request-records", type=int, default=100000)
    sign.add_argument("--max-recovery-records", type=int, default=100000)
    sign.add_argument("--max-audit-records", type=int, default=1000000)
    sign.add_argument("--max-control-bytes", type=int, default=4 * 1024 * 1024 * 1024)
    sign.add_argument("--output", required=True)
    sign.set_defaults(handler=sign_command)
    activate = commands.add_parser("activate", help="verify and atomically activate a policy")
    activate.add_argument("--active-policy", required=True)
    activate.add_argument("--candidate", required=True)
    activate.add_argument("--expected-current-policy-sha256", required=True)
    activate.add_argument("--trust-policy", required=True)
    activate.add_argument("--expected-trust-policy-id", required=True)
    activate.add_argument("--expected-trust-policy-sha256", required=True)
    activate.add_argument("--verification-time")
    activate.add_argument("--report")
    activate.set_defaults(handler=activate_command)
    return result


def main() -> int:
    args = parser().parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
