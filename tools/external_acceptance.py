#!/usr/bin/env python3
"""Create and verify candidate-bound external acceptance evidence."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


ACCEPTANCE_CHECKS = {
    "petalinux-target": ("image-identity", "boot-cycle", "runtime-health",
                         "resource-boundary", "upgrade-rollback"),
    "physical-protocols": ("device-inventory", "connectivity", "data-integrity",
                           "disconnect-recovery", "throughput-error-budget"),
    "production-identity": ("identity-provider", "least-privilege", "rotation",
                            "revocation", "audit-secret-redaction"),
    "site-network": ("routing-dns", "tls-path", "firewall-proxy", "reconnect",
                     "time-synchronization"),
    "soak-24h": ("duration", "health", "resource-growth", "error-budget", "fault-recovery"),
    "soak-72h": ("duration", "health", "resource-growth", "error-budget", "fault-recovery"),
}


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def content_digest(document: dict[str, Any]) -> str:
    payload = dict(document)
    payload.pop("contentSha256", None)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def atomic_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.new")
    try:
        temporary.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n",
                             encoding="utf-8", newline="\n")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def named_path(value: str) -> tuple[str, Path]:
    name, separator, raw_path = value.partition("=")
    if not separator or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", name):
        raise argparse.ArgumentTypeError("expected CHECK-ID=PATH")
    return name, Path(raw_path)


def create_template(args: argparse.Namespace) -> int:
    manifest = args.artifact_manifest.resolve()
    document = {
        "schemaVersion": 1, "operation": "external-acceptance-template",
        "acceptanceType": args.type, "createdAt": datetime.now(timezone.utc).isoformat(),
        "candidate": {"version": args.version, "gitCommit": args.git_commit,
                      "artifactManifestSha256": digest(manifest)},
        "checks": [{"id": check, "status": "PENDING"} for check in ACCEPTANCE_CHECKS[args.type]],
    }
    atomic_json(args.output.resolve(), document)
    print(f"EXTERNAL_ACCEPTANCE_TEMPLATE_PASS type={args.type} output={args.output.resolve()}")
    return 0


def approve(args: argparse.Namespace) -> int:
    if not args.confirm_all_checks_passed:
        raise ValueError("approval requires --confirm-all-checks-passed")
    if not args.key_id or any(character.isspace() for character in args.key_id):
        raise ValueError("external approval key id must be non-empty and contain no whitespace")
    template = json.loads(args.template.resolve().read_text(encoding="utf-8"))
    acceptance_type = template.get("acceptanceType")
    if (template.get("operation") != "external-acceptance-template" or
            acceptance_type not in ACCEPTANCE_CHECKS):
        raise ValueError("invalid external acceptance template")
    evidence_by_check: dict[str, list[Path]] = {}
    for check, path in args.evidence:
        evidence_by_check.setdefault(check, []).append(path.resolve())
    expected = set(ACCEPTANCE_CHECKS[acceptance_type])
    if set(evidence_by_check) != expected:
        missing = sorted(expected - set(evidence_by_check))
        unexpected = sorted(set(evidence_by_check) - expected)
        raise ValueError(f"evidence check mismatch; missing={missing} unexpected={unexpected}")
    output = args.output.resolve()
    signature_output = args.signature_output.resolve()
    archive = output.parent / f"{output.stem}.evidence"
    if output.exists() or signature_output.exists() or archive.exists():
        raise FileExistsError("external acceptance output, signature or evidence archive already exists")
    staging = archive.with_name(archive.name + f".{uuid.uuid4().hex}.new")
    staging.mkdir(parents=True)
    checks = []
    try:
        for check in ACCEPTANCE_CHECKS[acceptance_type]:
            attachments = []
            check_directory = staging / check
            check_directory.mkdir()
            for index, path in enumerate(evidence_by_check[check]):
                if not path.is_file():
                    raise FileNotFoundError(f"external evidence attachment not found: {path}")
                destination = check_directory / f"{index:02d}-{path.name}"
                shutil.copy2(path, destination)
                final_path = archive / check / destination.name
                attachments.append({"path": final_path.relative_to(output.parent).as_posix(),
                                    "size": destination.stat().st_size,
                                    "sha256": digest(destination)})
            checks.append({"id": check, "status": "PASSED", "evidence": attachments})
        os.replace(staging, archive)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    document = {
        "schemaVersion": 1, "operation": "external-acceptance", "passed": True,
        "verdict": "APPROVED", "acceptanceType": acceptance_type,
        "approvedAt": datetime.now(timezone.utc).isoformat(),
        "candidate": template.get("candidate"), "checks": checks,
        "approval": {"approverId": args.approver_id, "record": args.approval_record},
    }
    document["contentSha256"] = content_digest(document)
    try:
        atomic_json(output, document)
        key_path_value = os.environ.get(args.private_key_path_environment)
        if not key_path_value:
            raise ValueError("external approval private key path environment is unset")
        passphrase = None
        if args.private_key_passphrase_environment:
            value = os.environ.get(args.private_key_passphrase_environment)
            if value is None:
                raise ValueError("external approval private key passphrase environment is unset")
            passphrase = value.encode("utf-8")
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
            from cryptography.hazmat.primitives.serialization import load_pem_private_key
        except ImportError as error:
            raise ValueError("Ed25519 signing requires the release-host cryptography package") from error
        key = load_pem_private_key(Path(key_path_value).read_bytes(), password=passphrase)
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError("external approval private key is not Ed25519")
        payload = output.read_bytes()
        signature = {
            "schemaVersion": 1, "product": "PocoDDSRuntimeExternalAcceptance",
            "algorithm": "Ed25519", "keyId": args.key_id,
            "manifestSha256": hashlib.sha256(payload).hexdigest(),
            "signature": base64.b64encode(key.sign(payload)).decode("ascii"),
        }
        atomic_json(signature_output, signature)
    except Exception:
        output.unlink(missing_ok=True)
        signature_output.unlink(missing_ok=True)
        shutil.rmtree(archive, ignore_errors=True)
        raise
    print(f"EXTERNAL_ACCEPTANCE_APPROVED type={acceptance_type} output={output}")
    return 0


def verify_report(path: Path, expected_type: str | None = None,
                  expected_version: str | None = None, expected_commit: str | None = None,
                  expected_manifest_sha256: str | None = None) -> dict[str, Any]:
    document = json.loads(path.resolve().read_text(encoding="utf-8"))
    acceptance_type = document.get("acceptanceType")
    if (document.get("schemaVersion") != 1 or document.get("operation") != "external-acceptance" or
            document.get("passed") is not True or document.get("verdict") != "APPROVED" or
            acceptance_type not in ACCEPTANCE_CHECKS):
        raise ValueError("unsupported or non-approved external acceptance report")
    if expected_type and acceptance_type != expected_type:
        raise ValueError("external acceptance type mismatch")
    if document.get("contentSha256") != content_digest(document):
        raise ValueError("external acceptance content digest mismatch")
    candidate = document.get("candidate", {})
    for label, actual, expected in (
        ("version", candidate.get("version"), expected_version),
        ("git commit", candidate.get("gitCommit"), expected_commit),
        ("artifact manifest", candidate.get("artifactManifestSha256"), expected_manifest_sha256),
    ):
        if expected is not None and actual != expected:
            raise ValueError(f"external acceptance candidate {label} mismatch")
    approval = document.get("approval", {})
    if not str(approval.get("approverId", "")).strip() or not str(approval.get("record", "")).strip():
        raise ValueError("external acceptance has no approver or approval record")
    checks = document.get("checks")
    if not isinstance(checks, list) or {item.get("id") for item in checks} != set(
            ACCEPTANCE_CHECKS[acceptance_type]):
        raise ValueError("external acceptance check set mismatch")
    attachment_count = 0
    for check in checks:
        evidence = check.get("evidence")
        if check.get("status") != "PASSED" or not isinstance(evidence, list) or not evidence:
            raise ValueError(f"external acceptance check is incomplete: {check.get('id')}")
        for attachment in evidence:
            attachment_path = Path(str(attachment.get("path", "")))
            if not attachment_path.is_absolute():
                attachment_path = path.resolve().parent / attachment_path
            attachment_path = attachment_path.resolve()
            if (not attachment_path.is_file() or attachment_path.stat().st_size != attachment.get("size") or
                    digest(attachment_path) != attachment.get("sha256")):
                raise ValueError(f"external acceptance attachment changed: {attachment_path}")
            attachment_count += 1
    return {"verified": True, "acceptanceType": acceptance_type,
            "attachmentCount": attachment_count, "contentSha256": document["contentSha256"]}


def parse_time(value: Any, field: str) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"external approval trust policy {field} is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"external approval trust policy {field} is invalid") from error
    if parsed.tzinfo is None:
        raise ValueError(f"external approval trust policy {field} requires timezone")
    return parsed.astimezone(timezone.utc)


def verify_signed_report(report_path: Path, signature_path: Path, trust_policy_path: Path,
                         expected_policy_id: str, expected_policy_sha256: str,
                         signature_check_executable: Path, expected_type: str,
                         expected_version: str, expected_commit: str | None,
                         expected_manifest_sha256: str | None) -> dict[str, Any]:
    evidence = verify_report(report_path, expected_type, expected_version, expected_commit,
                             expected_manifest_sha256)
    policy_path = trust_policy_path.resolve()
    policy_sha = digest(policy_path)
    if policy_sha != expected_policy_sha256.lower():
        raise ValueError("external approval trust policy SHA-256 is not trusted")
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    if (policy.get("schemaVersion") != 1 or
            policy.get("product") != "PocoDDSRuntimeExternalAcceptance" or
            policy.get("policyId") != expected_policy_id):
        raise ValueError("external approval trust policy identity is invalid")
    report = json.loads(report_path.resolve().read_text(encoding="utf-8"))
    approved_at = parse_time(report.get("approvedAt"), "approvedAt")
    current = datetime.now(timezone.utc)
    if approved_at is None or approved_at > current + timedelta(minutes=5):
        raise ValueError("external approval time is invalid or in the future")
    signature = json.loads(signature_path.resolve().read_text(encoding="utf-8"))
    if (signature.get("schemaVersion") != 1 or
            signature.get("product") != "PocoDDSRuntimeExternalAcceptance" or
            signature.get("algorithm") != "Ed25519" or not isinstance(signature.get("keyId"), str)):
        raise ValueError("unsupported external approval signature envelope")
    key_id = signature["keyId"]
    revoked = policy.get("revokedKeys")
    if not isinstance(revoked, list):
        raise ValueError("external approval revocation list is malformed")
    for entry in revoked:
        if not isinstance(entry, dict) or not entry.get("keyId") or not entry.get("reason"):
            raise ValueError("external approval revocation entry is malformed")
        parse_time(entry.get("revokedAt"), "revokedAt")
        if entry["keyId"] == key_id:
            raise ValueError(f"external approval key is revoked: {key_id}: {entry['reason']}")
    approver_id = report.get("approval", {}).get("approverId")
    allowed = policy.get("allowedApprovers")
    if not isinstance(allowed, list):
        raise ValueError("external approval approver list is malformed")
    matches = [entry for entry in allowed if isinstance(entry, dict) and
               entry.get("approverId") == approver_id and entry.get("keyId") == key_id]
    if len(matches) != 1:
        raise ValueError("external approver and signing key are not uniquely allowed")
    approver = matches[0]
    types = approver.get("acceptanceTypes")
    if (approver.get("algorithm") != "Ed25519" or not isinstance(types, list) or
            expected_type not in types):
        raise ValueError("external approver is not allowed for this acceptance type")
    public_key = (policy_path.parent / str(approver.get("publicKeyPath", ""))).resolve()
    public_key_sha = digest(public_key)
    if approver.get("publicKeySha256") != public_key_sha:
        raise ValueError("external approver public key is not allowed by trust policy")
    not_before = parse_time(approver.get("notBefore"), "notBefore")
    not_after = parse_time(approver.get("notAfter"), "notAfter")
    if not_before and not_after and not_before >= not_after:
        raise ValueError("external approver validity window is invalid")
    if not_before and (current < not_before or approved_at < not_before):
        raise ValueError("external approver key is not active yet")
    if not_after and (current >= not_after or approved_at >= not_after):
        raise ValueError("external approver key has expired")
    verifier = signature_check_executable.resolve()
    if not verifier.is_file():
        raise ValueError(f"external signature verifier is unavailable: {verifier}")
    completed = subprocess.run(
        [str(verifier), str(report_path.resolve()), str(signature_path.resolve()),
         str(public_key), key_id, "PocoDDSRuntimeExternalAcceptance"],
        capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise ValueError((completed.stderr or completed.stdout).strip() or
                         "external approval signature verification failed")
    evidence.update({"signatureVerified": True, "approverId": approver_id, "keyId": key_id,
                     "publicKeySha256": public_key_sha, "policyId": policy["policyId"],
                     "policySha256": policy_sha})
    return evidence


def verify_command(args: argparse.Namespace) -> int:
    if args.signature:
        required = (args.trust_policy, args.expected_trust_policy_id,
                    args.expected_trust_policy_sha256, args.signature_check_executable,
                    args.type, args.version)
        if any(value is None for value in required):
            raise ValueError("signed verification requires trust policy pins, verifier, type and version")
        result = verify_signed_report(
            args.report, args.signature, args.trust_policy, args.expected_trust_policy_id,
            args.expected_trust_policy_sha256, args.signature_check_executable,
            args.type, args.version, args.git_commit, args.artifact_manifest_sha256)
    else:
        result = verify_report(args.report, args.type, args.version, args.git_commit,
                               args.artifact_manifest_sha256)
    print(f"EXTERNAL_ACCEPTANCE_VERIFY_PASS type={result['acceptanceType']} attachments={result['attachmentCount']}")
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    template = commands.add_parser("template")
    template.add_argument("--type", choices=sorted(ACCEPTANCE_CHECKS), required=True)
    template.add_argument("--version", required=True)
    template.add_argument("--git-commit", required=True)
    template.add_argument("--artifact-manifest", type=Path, required=True)
    template.add_argument("--output", type=Path, required=True)
    template.set_defaults(handler=create_template)
    approval = commands.add_parser("approve")
    approval.add_argument("--template", type=Path, required=True)
    approval.add_argument("--evidence", action="append", type=named_path, default=[])
    approval.add_argument("--approver-id", required=True)
    approval.add_argument("--approval-record", required=True)
    approval.add_argument("--confirm-all-checks-passed", action="store_true")
    approval.add_argument("--output", type=Path, required=True)
    approval.add_argument("--signature-output", type=Path, required=True)
    approval.add_argument("--key-id", required=True)
    approval.add_argument("--private-key-path-environment", required=True)
    approval.add_argument("--private-key-passphrase-environment")
    approval.set_defaults(handler=approve)
    verify = commands.add_parser("verify")
    verify.add_argument("--report", type=Path, required=True)
    verify.add_argument("--type", choices=sorted(ACCEPTANCE_CHECKS))
    verify.add_argument("--version")
    verify.add_argument("--git-commit")
    verify.add_argument("--artifact-manifest-sha256")
    verify.add_argument("--signature", type=Path)
    verify.add_argument("--trust-policy", type=Path)
    verify.add_argument("--expected-trust-policy-id")
    verify.add_argument("--expected-trust-policy-sha256")
    verify.add_argument("--signature-check-executable", type=Path)
    verify.set_defaults(handler=verify_command)
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        return args.handler(args)
    except (OSError, ValueError) as error:
        print(f"EXTERNAL_ACCEPTANCE_ERROR: {error}", file=os.sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
