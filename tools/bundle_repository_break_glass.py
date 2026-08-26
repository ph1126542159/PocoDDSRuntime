#!/usr/bin/env python3
"""Request, rehearse, approve, apply and recover an offline Bundle downgrade."""

from __future__ import annotations

import argparse
import base64
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any, Iterator
import uuid


PRODUCT = "PocoDDSBundleRepositoryBreakGlass"
ACTION = "downgrade-high-water"
SHA256 = re.compile(r"^[0-9a-f]{64}$")
IDENTITY = re.compile(r"^[^\s\x00-\x1f\x7f]+$")
KEY_ID = re.compile(r"^[A-Za-z0-9._-]+$")
TICKET = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{2,127}$")
FINGERPRINT = re.compile(r"^BUNDLE_REPOSITORY_FINGERPRINT sha256=([0-9a-f]{64})$",
                         re.MULTILINE)
MAX_SEQUENCE = (1 << 63) - 1
MAX_APPROVAL_SECONDS = 24 * 60 * 60
MAX_APPROVAL_QUORUM = 16
MAX_AUDIT_BYTES = 16 * 1024 * 1024
MAX_AUDIT_LINE_BYTES = 256 * 1024
AUDIT_GENESIS_SHA256 = "0" * 64
TRANSACTION_STATES = {
    "prepared", "authorized", "previousSaved", "activated",
    "highWaterCommitted", "consumed", "completed", "rolledBack",
}
TERMINAL_TRANSACTION_STATES = {"completed", "rolledBack"}
STATE_FIELDS = (
    "repositoryId", "rolloutSequence", "candidateDigest", "publisherId", "signingKeyId",
    "trustPolicyId", "trustPolicySha256", "attestationSha256",
    "releaseManifestSha256", "sbomSha256", "artifactSetSha256", "releaseVersion",
    "gitCommit", "builderId", "buildProfile",
)


def strict_json(content: str | bytes, description: str) -> Any:
    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{description} contains duplicate JSON key: {key}")
            result[key] = value
        return result
    try:
        return json.loads(content, object_pairs_hook=unique_object)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{description} is malformed JSON") from error


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_time(value: Any, description: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{description} must be ISO-8601 text")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{description} is not valid ISO-8601") from error
    if parsed.tzinfo is None:
        raise ValueError(f"{description} must include a timezone")
    return parsed.astimezone(timezone.utc)


def atomic_bytes(path: Path, content: bytes, *, exclusive: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if exclusive and path.exists():
        raise ValueError(f"refusing to overwrite existing file: {path}")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if exclusive and path.exists():
            raise ValueError(f"refusing to overwrite existing file: {path}")
        durable_replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def durable_replace(temporary: Path, target: Path) -> None:
    if os.name == "nt":
        import ctypes
        if not ctypes.windll.kernel32.MoveFileExW(
                str(temporary), str(target), 0x1 | 0x8):  # REPLACE_EXISTING | WRITE_THROUGH
            raise OSError(ctypes.get_last_error(), f"cannot durably replace {target}")
    else:
        os.replace(temporary, target)
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        descriptor = os.open(target.parent, flags)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def atomic_json(path: Path, document: dict[str, Any], *, exclusive: bool = False) -> None:
    content = (json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    atomic_bytes(path, content, exclusive=exclusive)


def audit_payload(record: dict[str, Any]) -> bytes:
    unsigned = {key: value for key, value in record.items() if key != "recordSha256"}
    return json.dumps(unsigned, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def evidence_sha256(document: dict[str, Any]) -> str:
    unsigned = {key: value for key, value in document.items() if key != "evidenceSha256"}
    payload = json.dumps(unsigned, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def transaction_sha256(document: dict[str, Any]) -> str:
    unsigned = {key: value for key, value in document.items() if key != "transactionSha256"}
    payload = json.dumps(unsigned, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def transaction_path(state_dir: Path, approval_id: str) -> Path:
    return state_dir / "break-glass-transactions" / f"{approval_id}.json"


def validate_transaction(document: Any, path: Path) -> dict[str, Any]:
    required = {
        "schemaVersion", "product", "action", "approvalId", "state", "updatedAt",
        "repository", "staging", "previous", "requestSha256", "sourceStateSha256",
        "ticket", "source", "target", "approval", "transactionSha256",
    }
    optional = {"authorizedAuditSha256", "consumptionSha256", "appliedAuditSha256",
                "recoveryAuditSha256", "recoveryResult"}
    if not isinstance(document, dict) or set(document) - required - optional or \
            not required.issubset(document) or document.get("schemaVersion") != 1 or \
            document.get("product") != PRODUCT or document.get("action") != ACTION or \
            document.get("state") not in TRANSACTION_STATES:
        raise ValueError(f"unsupported break-glass transaction journal: {path}")
    try:
        approval_id = str(uuid.UUID(str(document["approvalId"])))
    except ValueError as error:
        raise ValueError("break-glass transaction approvalId is malformed") from error
    if approval_id != document["approvalId"] or path.name != f"{approval_id}.json":
        raise ValueError("break-glass transaction identity differs from its path")
    parse_time(document["updatedAt"], "break-glass transaction updatedAt")
    if not isinstance(document["ticket"], str) or TICKET.fullmatch(document["ticket"]) is None:
        raise ValueError("break-glass transaction ticket is malformed")
    for field in ("repository", "staging", "previous"):
        value = document[field]
        if not isinstance(value, str) or not Path(value).is_absolute() or \
                Path(value).resolve() != Path(value):
            raise ValueError(f"break-glass transaction {field} is not absolute")
    for field in ("requestSha256", "sourceStateSha256", "transactionSha256"):
        if not isinstance(document[field], str) or SHA256.fullmatch(document[field]) is None:
            raise ValueError(f"break-glass transaction {field} is malformed")
    for field in optional.intersection(document):
        if field.endswith("Sha256") and SHA256.fullmatch(str(document[field])) is None:
            raise ValueError(f"break-glass transaction {field} is malformed")
    source = validate_state({"schemaVersion": 2, **document["source"]},
                            "break-glass transaction source")
    target = validate_state({"schemaVersion": 2, **document["target"]},
                            "break-glass transaction target")
    if source != document["source"] or target != document["target"]:
        raise ValueError("break-glass transaction rollout state is not canonical")
    approval = document["approval"]
    approval_count = approval.get("approvalCount") if isinstance(approval, dict) else None
    minimum_approvals = approval.get("minimumApprovals") if isinstance(approval, dict) else None
    if not isinstance(approval, dict) or not isinstance(approval_count, int) or \
            not isinstance(minimum_approvals, int) or approval_count < minimum_approvals or \
            not isinstance(approval.get("approvals"), list) or \
            len(approval["approvals"]) != approval_count:
        raise ValueError("break-glass transaction approval evidence is malformed")
    if "recoveryResult" in document and document["recoveryResult"] not in {
            "forward-completed", "rolled-back-before-high-water"}:
        raise ValueError("break-glass transaction recovery result is malformed")
    if transaction_sha256(document) != document["transactionSha256"]:
        raise ValueError("break-glass transaction journal hash mismatch")
    return document


def read_transaction(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"break-glass transaction journal is unavailable: {path}")
    return validate_transaction(
        strict_json(path.read_bytes(), "break-glass transaction journal"), path
    )


def write_transaction(path: Path, document: dict[str, Any], *, exclusive: bool = False) -> None:
    updated = dict(document)
    updated["updatedAt"] = datetime.now(timezone.utc).isoformat()
    updated["transactionSha256"] = transaction_sha256(updated)
    validate_transaction(updated, path)
    atomic_json(path, updated, exclusive=exclusive)
    document.clear()
    document.update(updated)


def transition_transaction(path: Path, document: dict[str, Any], state: str,
                           **evidence: Any) -> None:
    if state not in TRANSACTION_STATES:
        raise ValueError(f"unsupported break-glass transaction state: {state}")
    document.update(evidence)
    document["state"] = state
    write_transaction(path, document)


def active_transactions(state_dir: Path, exclude: str | None = None) -> list[Path]:
    directory = state_dir / "break-glass-transactions"
    if not directory.exists():
        return []
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("break-glass transaction directory is not a regular directory")
    paths = sorted(directory.glob("*.json"))
    if len(paths) > 256:
        raise ValueError("break-glass transaction history exceeds the 256-entry inspection limit")
    result: list[Path] = []
    for path in paths:
        journal = read_transaction(path)
        if journal["state"] not in TERMINAL_TRANSACTION_STATES and \
                journal["approvalId"] != exclude:
            result.append(path)
    return result


def verify_audit_path(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"recordCount": 0, "headSha256": AUDIT_GENESIS_SHA256,
                "firstTimestamp": None, "lastTimestamp": None}
    if path.is_symlink() or not path.is_file():
        raise ValueError("break-glass audit must be a regular file")
    if path.stat().st_size > MAX_AUDIT_BYTES:
        raise ValueError("break-glass audit exceeds the 16 MiB verification limit")
    previous = AUDIT_GENESIS_SHA256
    first_timestamp: str | None = None
    last_timestamp: str | None = None
    count = 0
    with path.open("rb") as stream:
        for raw_line in stream:
            count += 1
            if len(raw_line) > MAX_AUDIT_LINE_BYTES:
                raise ValueError(f"break-glass audit record {count} exceeds 256 KiB")
            try:
                record = strict_json(raw_line, f"break-glass audit record {count}")
            except ValueError as error:
                raise ValueError(f"break-glass audit record {count} is malformed") from error
            if not isinstance(record, dict) or record.get("schemaVersion") != 1 or \
                    record.get("product") != PRODUCT or record.get("sequence") != count or \
                    record.get("previousRecordSha256") != previous or \
                    record.get("event") not in {"BUNDLE_BREAK_GLASS_AUTHORIZED",
                                                "BUNDLE_BREAK_GLASS_APPLIED",
                                                "BUNDLE_BREAK_GLASS_RECOVERED_ROLLBACK"}:
                raise ValueError(f"break-glass audit record {count} breaks the chain contract")
            timestamp = record.get("timestamp")
            parse_time(timestamp, f"break-glass audit record {count} timestamp")
            actual = hashlib.sha256(audit_payload(record)).hexdigest()
            if record.get("recordSha256") != actual:
                raise ValueError(f"break-glass audit record {count} hash mismatch")
            previous = actual
            first_timestamp = first_timestamp or timestamp
            last_timestamp = timestamp
    return {"recordCount": count, "headSha256": previous,
            "firstTimestamp": first_timestamp, "lastTimestamp": last_timestamp}


def append_audit(state_dir: Path, event: dict[str, Any]) -> dict[str, Any]:
    reserved = {"schemaVersion", "product", "sequence", "timestamp",
                "previousRecordSha256", "recordSha256"}
    if reserved.intersection(event):
        raise ValueError("break-glass audit event attempts to replace chain metadata")
    state_dir.mkdir(parents=True, exist_ok=True)
    path = state_dir / "break-glass-audit.jsonl"
    chain = verify_audit_path(path)
    record = {
        "schemaVersion": 1, "product": PRODUCT,
        "sequence": chain["recordCount"] + 1,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "previousRecordSha256": chain["headSha256"], **event,
    }
    record["recordSha256"] = hashlib.sha256(audit_payload(record)).hexdigest()
    rendered = json.dumps(record, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":")) + "\n"
    rendered_bytes = rendered.encode("utf-8")
    if len(rendered_bytes) > MAX_AUDIT_LINE_BYTES:
        raise ValueError("break-glass audit record exceeds 256 KiB")
    if (path.stat().st_size if path.exists() else 0) + len(rendered_bytes) > MAX_AUDIT_BYTES:
        raise ValueError("break-glass audit exceeds the 16 MiB append limit")
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(rendered)
        stream.flush()
        os.fsync(stream.fileno())
    return record


def read_properties(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise ValueError(f"Bundle rollout high-water mark is unavailable: {path}")
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "!")):
            continue
        if "=" not in stripped:
            raise ValueError("Bundle rollout high-water mark contains a malformed line")
        key, value = (part.strip() for part in stripped.split("=", 1))
        if not key or key in result:
            raise ValueError("Bundle rollout high-water mark contains an empty or duplicate key")
        result[key] = value
    return result


def positive_sequence(value: Any, description: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{description} is malformed")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{description} is malformed") from error
    if str(parsed) != str(value) or parsed < 1 or parsed > MAX_SEQUENCE:
        raise ValueError(f"{description} is outside 1..2^63-1")
    return parsed


def approval_minutes(value: str) -> int:
    try:
        parsed = int(value, 10)
    except ValueError as error:
        raise argparse.ArgumentTypeError("approval lifetime must be an integer") from error
    if parsed < 1 or parsed > 1440:
        raise argparse.ArgumentTypeError("approval lifetime must be in 1..1440 minutes")
    return parsed


def validate_state(values: dict[str, Any], description: str) -> dict[str, Any]:
    if values.get("schemaVersion", "2") != "2" and values.get("schemaVersion") != 2:
        raise ValueError(f"{description} must use provenance-bound schemaVersion 2")
    missing = [field for field in STATE_FIELDS if field not in values or values[field] in (None, "")]
    if missing:
        raise ValueError(f"{description} is missing: {', '.join(missing)}")
    result = {field: values[field] for field in STATE_FIELDS}
    result["rolloutSequence"] = positive_sequence(result["rolloutSequence"],
                                                   f"{description} rolloutSequence")
    for field in ("candidateDigest", "trustPolicySha256", "attestationSha256",
                  "releaseManifestSha256", "sbomSha256", "artifactSetSha256"):
        if not isinstance(result[field], str) or SHA256.fullmatch(result[field]) is None:
            raise ValueError(f"{description} {field} is malformed")
    if re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", str(result["gitCommit"])) is None:
        raise ValueError(f"{description} gitCommit is malformed")
    for field in ("repositoryId", "publisherId", "signingKeyId", "trustPolicyId",
                  "releaseVersion", "builderId", "buildProfile"):
        if not isinstance(result[field], str) or IDENTITY.fullmatch(result[field]) is None:
            raise ValueError(f"{description} {field} is malformed")
    return result


def high_water(state_dir: Path) -> tuple[Path, dict[str, Any], str]:
    path = state_dir / "repository-rollout-high-water.properties"
    if path.is_symlink():
        raise ValueError("Bundle rollout high-water mark must not be a symbolic link")
    values: dict[str, Any] = read_properties(path)
    return path, validate_state(values, "accepted high-water"), file_sha256(path)


def run_checked(command: list[str], description: str) -> str:
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise ValueError(f"{description} failed: {detail or result.returncode}")
    return result.stdout


def repository_digest(checker: Path, repository: Path) -> str:
    output = run_checked([str(checker), "fingerprint", str(repository)],
                         "Bundle repository fingerprint")
    match = FINGERPRINT.search(output)
    if match is None:
        raise ValueError("Bundle repository fingerprint output is malformed")
    return match.group(1)


def same_or_child(path: Path, parent: Path) -> bool:
    return path == parent or parent in path.parents


def authorize_target(args: argparse.Namespace) -> dict[str, Any]:
    checker = args.fingerprint_executable.resolve()
    repository = args.target_repository.resolve()
    if not checker.is_file() or not repository.is_dir():
        raise ValueError("target authorization requires an available checker and repository")
    if same_or_child(checker, repository):
        raise ValueError("Bundle authorization checker must not come from the target repository")
    if SHA256.fullmatch(args.expected_publisher_trust_policy_sha256) is None:
        raise ValueError("expected publisher trust policy SHA-256 is malformed")
    output = run_checked([
        str(checker), "authorize", str(repository),
        "--repository-id", args.repository_id,
        "--evidence-directory", str(args.evidence_directory.resolve()),
        "--trust-policy-file", str(args.publisher_trust_policy.resolve()),
        "--expected-trust-policy-id", args.expected_publisher_trust_policy_id,
        "--expected-trust-policy-sha256", args.expected_publisher_trust_policy_sha256,
        "--trusted-keys-directory", str(args.publisher_trusted_keys_directory.resolve()),
    ], "target Bundle authorization")
    try:
        report = strict_json(output, "target Bundle authorization output")
    except ValueError as error:
        raise ValueError("target Bundle authorization output is malformed") from error
    if report.get("result") != "BUNDLE_REPOSITORY_AUTHORIZATION_PASS" or \
            report.get("verified") is not True:
        raise ValueError("target Bundle authorization did not produce verified evidence")
    report["schemaVersion"] = 2
    return validate_state(report, "authorized downgrade target")


def validate_request(document: Any, *, require_live: bool = True) -> dict[str, Any]:
    request_fields = {"schemaVersion", "product", "action", "approvalId", "issuedAt",
                      "expiresAt", "reason", "ticket", "sourceStateSha256", "source", "target"}
    if not isinstance(document, dict) or document.get("schemaVersion") != 1 or \
            document.get("product") != PRODUCT or document.get("action") != ACTION or \
            set(document) != request_fields:
        raise ValueError("unsupported break-glass request")
    try:
        approval_id = str(uuid.UUID(str(document["approvalId"])))
    except (KeyError, ValueError) as error:
        raise ValueError("break-glass approvalId must be a UUID") from error
    if approval_id != document["approvalId"]:
        raise ValueError("break-glass approvalId must use canonical UUID text")
    issued_at = parse_time(document.get("issuedAt"), "break-glass issuedAt")
    expires_at = parse_time(document.get("expiresAt"), "break-glass expiresAt")
    if expires_at <= issued_at or (expires_at - issued_at).total_seconds() > MAX_APPROVAL_SECONDS:
        raise ValueError("break-glass approval lifetime must be positive and no more than 24 hours")
    now = datetime.now(timezone.utc)
    if issued_at > now + timedelta(minutes=5):
        raise ValueError("break-glass request issue time is in the future")
    if require_live and now >= expires_at:
        raise ValueError("break-glass approval has expired")
    if not isinstance(document.get("reason"), str) or len(document["reason"].strip()) < 10:
        raise ValueError("break-glass reason must contain at least 10 characters")
    if not isinstance(document.get("ticket"), str) or TICKET.fullmatch(document["ticket"]) is None:
        raise ValueError("break-glass ticket identity is malformed")
    if not isinstance(document.get("source"), dict) or \
            set(document["source"]) != set(STATE_FIELDS) or \
            not isinstance(document.get("target"), dict) or \
            set(document["target"]) != set(STATE_FIELDS):
        raise ValueError("break-glass source or target fields are unsupported")
    source = validate_state({"schemaVersion": 2, **document["source"]},
                            "break-glass source")
    target = validate_state({"schemaVersion": 2, **document["target"]},
                            "break-glass target")
    if source["repositoryId"] != target["repositoryId"] or \
            target["rolloutSequence"] >= source["rolloutSequence"]:
        raise ValueError("break-glass request must bind a lower sequence for the same repository")
    if not isinstance(document.get("sourceStateSha256"), str) or \
            SHA256.fullmatch(document["sourceStateSha256"]) is None:
        raise ValueError("break-glass sourceStateSha256 is malformed")
    return document


def request_command(args: argparse.Namespace) -> dict[str, Any]:
    state_path, source, source_sha256 = high_water(args.state_dir.resolve())
    if args.repository.is_symlink() or not args.repository.resolve().is_dir():
        raise ValueError("current Bundle repository must be an available regular directory")
    repository = args.repository.resolve()
    checker = args.fingerprint_executable.resolve()
    if same_or_child(checker, repository):
        raise ValueError("Bundle fingerprint checker must not come from the current repository")
    current_digest = repository_digest(checker, repository)
    if current_digest != source["candidateDigest"]:
        raise ValueError("current Bundle repository differs from the accepted high-water digest")
    target = authorize_target(args)
    if target["repositoryId"] != source["repositoryId"] or \
            target["rolloutSequence"] >= source["rolloutSequence"]:
        raise ValueError("target must be an authorized lower rollout for the same repository")
    now = datetime.now(timezone.utc)
    document = {
        "schemaVersion": 1,
        "product": PRODUCT,
        "action": ACTION,
        "approvalId": str(uuid.uuid4()),
        "issuedAt": now.isoformat(),
        "expiresAt": (now + timedelta(minutes=args.valid_for_minutes)).isoformat(),
        "reason": args.reason.strip(),
        "ticket": args.ticket,
        "sourceStateSha256": source_sha256,
        "source": source,
        "target": target,
    }
    validate_request(document)
    atomic_json(args.output.resolve(), document, exclusive=True)
    return {"result": "BUNDLE_BREAK_GLASS_REQUEST_CREATED", "approvalId": document["approvalId"],
            "request": str(args.output.resolve()), "sourceHighWater": str(state_path),
            "fromSequence": source["rolloutSequence"], "sourceDigest": current_digest,
            "targetSequence": target["rolloutSequence"]}


def approve_command(args: argparse.Namespace) -> dict[str, Any]:
    request = args.request.resolve()
    validate_request(strict_json(request.read_bytes(), "break-glass request"))
    key_value = os.environ.get(args.private_key_path_environment)
    if not key_value:
        raise ValueError("break-glass private key path environment is unset")
    passphrase = None
    if args.private_key_passphrase_environment:
        value = os.environ.get(args.private_key_passphrase_environment)
        if value is None:
            raise ValueError("break-glass private key passphrase environment is unset")
        passphrase = value.encode()
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
    except ImportError as error:
        raise ValueError("Ed25519 approval requires the release-host cryptography package") from error
    key = load_pem_private_key(Path(key_value).read_bytes(), password=passphrase)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("break-glass private key is not Ed25519")
    if KEY_ID.fullmatch(args.key_id) is None or IDENTITY.fullmatch(args.approver_id) is None:
        raise ValueError("break-glass approver or key identity is malformed")
    payload = request.read_bytes()
    signature = {
        "schemaVersion": 1, "product": PRODUCT, "algorithm": "Ed25519",
        "approverId": args.approver_id, "keyId": args.key_id,
        "manifestSha256": hashlib.sha256(payload).hexdigest(),
        "signature": base64.b64encode(key.sign(payload)).decode("ascii"),
    }
    atomic_json(args.signature_output.resolve(), signature, exclusive=True)
    return {"result": "BUNDLE_BREAK_GLASS_APPROVED", "approverId": args.approver_id,
            "keyId": args.key_id, "signature": str(args.signature_output.resolve())}


def matches_pattern(identity: str, pattern: str) -> bool:
    return identity == pattern or (pattern.endswith("*") and identity.startswith(pattern[:-1]))


def verify_approval(args: argparse.Namespace, request: dict[str, Any]) -> dict[str, Any]:
    policy_path = args.approver_trust_policy.resolve()
    actual_policy_sha256 = file_sha256(policy_path)
    if actual_policy_sha256 != args.expected_approver_trust_policy_sha256:
        raise ValueError("break-glass trust policy digest differs from the pinned digest")
    policy = strict_json(policy_path.read_bytes(), "break-glass trust policy")
    if not isinstance(policy, dict) or policy.get("schemaVersion") != 1 or \
            policy.get("product") != PRODUCT or \
            policy.get("policyId") != args.expected_approver_trust_policy_id or \
            set(policy) != {"schemaVersion", "product", "policyId",
                            "maxApprovalLifetimeSeconds", "minimumApprovals",
                            "allowedApprovers", "revokedKeys"}:
        raise ValueError("unsupported or unexpected break-glass trust policy")
    maximum_lifetime = policy.get("maxApprovalLifetimeSeconds")
    if not isinstance(maximum_lifetime, int) or isinstance(maximum_lifetime, bool) or \
            maximum_lifetime < 60 or maximum_lifetime > MAX_APPROVAL_SECONDS:
        raise ValueError("break-glass trust policy maximum lifetime is malformed")
    request_lifetime = (parse_time(request["expiresAt"], "break-glass expiresAt") -
                        parse_time(request["issuedAt"], "break-glass issuedAt")).total_seconds()
    if request_lifetime > maximum_lifetime:
        raise ValueError("break-glass request exceeds the trust policy approval lifetime")
    revoked = policy.get("revokedKeys")
    approvers = policy.get("allowedApprovers")
    if not isinstance(revoked, list) or not isinstance(approvers, list) or not approvers:
        raise ValueError("break-glass trust policy lists are malformed")
    for item in revoked:
        if not isinstance(item, dict) or set(item) != {"keyId", "revokedAt", "reason"} or \
                KEY_ID.fullmatch(str(item.get("keyId", ""))) is None or \
                not isinstance(item.get("reason"), str) or not item["reason"].strip():
            raise ValueError("break-glass trust policy revocation entry is malformed")
        parse_time(item.get("revokedAt"), "revokedAt")
    allowed_fields = {"approverId", "keyId", "algorithm", "publicKeySha256",
                      "repositoryPatterns", "actions", "notBefore", "notAfter"}
    required_fields = {"approverId", "keyId", "algorithm", "publicKeySha256",
                       "repositoryPatterns", "actions"}
    for item in approvers:
        if not isinstance(item, dict) or not required_fields.issubset(item) or \
                set(item) - allowed_fields or \
                not isinstance(item.get("approverId"), str) or \
                IDENTITY.fullmatch(item["approverId"]) is None or \
                not isinstance(item.get("keyId"), str) or KEY_ID.fullmatch(item["keyId"]) is None or \
                item.get("algorithm") != "Ed25519" or \
                SHA256.fullmatch(str(item.get("publicKeySha256", ""))) is None:
            raise ValueError("break-glass approver policy entry is malformed")
        item_patterns, item_actions = item["repositoryPatterns"], item["actions"]
        if not isinstance(item_patterns, list) or not item_patterns or \
                any(not isinstance(pattern, str) or
                    re.fullmatch(r"[^*\s]+\*?", pattern) is None for pattern in item_patterns) or \
                not isinstance(item_actions, list) or len(item_actions) != 1 or \
                set(item_actions) != {ACTION}:
            raise ValueError("break-glass approver scope is malformed")
        if "notBefore" in item:
            parse_time(item["notBefore"], "approver notBefore")
        if "notAfter" in item:
            parse_time(item["notAfter"], "approver notAfter")
    minimum_approvals = policy.get("minimumApprovals")
    unique_policy_approvers = {item["approverId"] for item in approvers}
    if not isinstance(minimum_approvals, int) or isinstance(minimum_approvals, bool) or \
            minimum_approvals < 1 or minimum_approvals > MAX_APPROVAL_QUORUM or \
            minimum_approvals > len(unique_policy_approvers):
        raise ValueError("break-glass minimum approval quorum is malformed")
    signature_paths = [path.resolve() for path in args.signature]
    if len(signature_paths) != len(set(signature_paths)):
        raise ValueError("duplicate break-glass signature file was supplied")
    verifier = args.signature_check_executable.resolve()
    if not verifier.is_file():
        raise ValueError("trusted break-glass signature verifier is unavailable")
    if same_or_child(verifier, args.target_repository.resolve()):
        raise ValueError("break-glass signature verifier must not come from the target repository")
    approvals: list[dict[str, str]] = []
    seen_approvers: set[str] = set()
    seen_keys: set[str] = set()
    now = datetime.now(timezone.utc)
    for signature_path in signature_paths:
        signature = strict_json(signature_path.read_bytes(), "break-glass signature")
        if not isinstance(signature, dict) or signature.get("schemaVersion") != 1 or \
                signature.get("product") != PRODUCT or \
                signature.get("algorithm") != "Ed25519" or \
                set(signature) != {"schemaVersion", "product", "algorithm", "approverId",
                                   "keyId", "manifestSha256", "signature"}:
            raise ValueError("unsupported break-glass signature envelope")
        approver_id, key_id = signature.get("approverId"), signature.get("keyId")
        if not isinstance(approver_id, str) or not isinstance(key_id, str):
            raise ValueError("break-glass signature lacks approver identity")
        if approver_id in seen_approvers or key_id in seen_keys:
            raise ValueError("break-glass quorum requires distinct approvers and keys")
        if any(item["keyId"] == key_id for item in revoked):
            raise ValueError("break-glass approval key is revoked")
        matches = [item for item in approvers if item["approverId"] == approver_id and
                   item["keyId"] == key_id]
        if len(matches) != 1:
            raise ValueError("break-glass approver and key are not uniquely allowed")
        approver = matches[0]
        if not any(matches_pattern(request["target"]["repositoryId"], pattern)
                   for pattern in approver["repositoryPatterns"]):
            raise ValueError("break-glass approver is not allowed for this repository and action")
        if "notBefore" in approver and \
                now < parse_time(approver["notBefore"], "approver notBefore"):
            raise ValueError("break-glass approver key is not active yet")
        if "notAfter" in approver and \
                now >= parse_time(approver["notAfter"], "approver notAfter"):
            raise ValueError("break-glass approver key has expired")
        public_key = args.approver_trusted_keys_directory.resolve() / f"{key_id}.pem"
        if not public_key.is_file() or file_sha256(public_key) != approver["publicKeySha256"]:
            raise ValueError("break-glass public key is absent or not pinned by policy")
        run_checked([str(verifier), str(args.request.resolve()), str(signature_path),
                     str(public_key), key_id, PRODUCT],
                    "break-glass signature verification")
        seen_approvers.add(approver_id)
        seen_keys.add(key_id)
        approvals.append({"approverId": approver_id, "keyId": key_id,
                          "signatureSha256": file_sha256(signature_path)})
    if len(approvals) < minimum_approvals:
        raise ValueError(
            f"break-glass approval quorum not met: {len(approvals)}/{minimum_approvals}"
        )
    approvals.sort(key=lambda item: (item["approverId"], item["keyId"]))
    return {"approvalCount": len(approvals), "minimumApprovals": minimum_approvals,
            "approvals": approvals, "trustPolicyId": policy["policyId"],
            "trustPolicySha256": actual_policy_sha256}


@contextmanager
def exclusive_state_lease(state_dir: Path) -> Iterator[None]:
    state_dir.mkdir(parents=True, exist_ok=True)
    lock_path = state_dir / "repository-rollout-high-water.lock"
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        create_file = ctypes.windll.kernel32.CreateFileW
        create_file.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        create_file.restype = wintypes.HANDLE
        handle = None
        for _ in range(100):
            candidate = create_file(str(lock_path), 0xC0000000, 0, None, 4, 0x80, None)
            if candidate != wintypes.HANDLE(-1).value:
                handle = candidate
                break
            time.sleep(0.01)
        if handle is None:
            raise ValueError("Bundle rollout high-water lease is held by another process")
        try:
            yield
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    else:
        import fcntl
        descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o660)
        try:
            for _ in range(100):
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    time.sleep(0.01)
            else:
                raise ValueError("Bundle rollout high-water lease is held by another process")
            yield
        finally:
            os.close(descriptor)


def write_high_water(path: Path, target: dict[str, Any]) -> None:
    lines = ["schemaVersion=2"] + [f"{field}={target[field]}" for field in STATE_FIELDS]
    lines.append(f"timestamp={datetime.now(timezone.utc).isoformat()}")
    for line in lines:
        if "\r" in line or "\n" in line:
            raise ValueError("unsafe high-water property value")
    atomic_bytes(path, ("\n".join(lines) + "\n").encode())


def target_authorization_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--target-repository", type=Path, required=True)
    parser.add_argument("--fingerprint-executable", type=Path, required=True)
    parser.add_argument("--repository-id", required=True)
    parser.add_argument("--evidence-directory", type=Path, required=True)
    parser.add_argument("--publisher-trust-policy", type=Path, required=True)
    parser.add_argument("--expected-publisher-trust-policy-id", required=True)
    parser.add_argument("--expected-publisher-trust-policy-sha256", required=True)
    parser.add_argument("--publisher-trusted-keys-directory", type=Path, required=True)


def operation_context(args: argparse.Namespace) -> dict[str, Any]:
    if args.repository.is_symlink() or args.target_repository.is_symlink():
        raise ValueError("live and target Bundle repositories must not be symbolic links")
    state_dir = args.state_dir.resolve()
    live_repository = args.repository.resolve()
    target_repository = args.target_repository.resolve()
    if not live_repository.is_dir():
        raise ValueError("live Bundle repository is unavailable")
    if same_or_child(live_repository, target_repository) or \
            same_or_child(target_repository, live_repository) or \
            same_or_child(state_dir, target_repository) or \
            same_or_child(target_repository, state_dir) or \
            same_or_child(state_dir, live_repository) or \
            same_or_child(live_repository, state_dir):
        raise ValueError("target, live repository and state directory must not overlap")
    trusted_materials = [args.request, args.approver_trust_policy,
                         args.approver_trusted_keys_directory,
                         args.signature_check_executable, args.fingerprint_executable,
                         *args.signature]
    if any(same_or_child(path.resolve(), target_repository) or
           same_or_child(path.resolve(), live_repository) for path in trusted_materials):
        raise ValueError("break-glass approval materials must not come from a Bundle repository")
    request_path = args.request.resolve()
    request = validate_request(strict_json(request_path.read_bytes(), "break-glass request"))
    approval = verify_approval(args, request)
    target = authorize_target(args)
    if target != request["target"]:
        raise ValueError("current target authorization differs from the approved target")
    staging = live_repository.with_name(live_repository.name + ".pdr-break-glass-staging")
    previous = live_repository.with_name(live_repository.name + ".pdr-previous")
    if staging.exists():
        raise ValueError("break-glass staging repository already exists")
    consumed = state_dir / "break-glass-consumed" / f"{request['approvalId']}.json"
    return {"stateDirectory": state_dir, "liveRepository": live_repository,
            "targetRepository": target_repository, "requestPath": request_path,
            "request": request, "approval": approval, "target": target,
            "staging": staging, "previous": previous, "consumed": consumed}


def repository_bytes(repository: Path) -> int:
    total = 0
    for path in repository.rglob("*"):
        if path.is_file() or path.is_symlink():
            total += path.lstat().st_size
    return total


def preflight_command(args: argparse.Namespace) -> dict[str, Any]:
    context = operation_context(args)
    state_dir = context["stateDirectory"]
    live_repository = context["liveRepository"]
    target_repository = context["targetRepository"]
    request = context["request"]
    approval = context["approval"]
    target = context["target"]
    staging = context["staging"]
    previous = context["previous"]
    consumed = context["consumed"]
    target_size = repository_bytes(target_repository)
    free_bytes = shutil.disk_usage(live_repository.parent).free
    required_free = target_size + max(16 * 1024 * 1024, target_size // 10)
    if free_bytes < required_free:
        raise ValueError(
            f"insufficient free space for break-glass staging: {free_bytes} < {required_free}"
        )
    with exclusive_state_lease(state_dir):
        pending = active_transactions(state_dir)
        if pending:
            raise ValueError(
                f"unfinished break-glass transaction requires recover: {pending[0]}"
            )
        validate_request(request)
        if verify_approval(args, request) != approval:
            raise ValueError("break-glass approval evidence changed while acquiring the state lease")
        high_water_path, source, source_sha256 = high_water(state_dir)
        if consumed.exists():
            raise ValueError("break-glass approval was already consumed")
        if staging.exists() or previous.exists():
            raise ValueError("break-glass staging or previous repository already exists")
        if source != request["source"] or source_sha256 != request["sourceStateSha256"]:
            raise ValueError("accepted high-water changed after break-glass approval")
        live_digest = repository_digest(args.fingerprint_executable.resolve(), live_repository)
        if live_digest != source["candidateDigest"]:
            raise ValueError("current Bundle repository differs from the approved high-water digest")
        audit = verify_audit_path(state_dir / "break-glass-audit.jsonl")
        shutil.copytree(target_repository, staging)
        try:
            staged = argparse.Namespace(**vars(args))
            staged.target_repository = staging
            if authorize_target(staged) != target:
                raise ValueError("staged downgrade target differs from approved authorization")
        finally:
            if staging.exists():
                shutil.rmtree(staging)
    result = {
        "schemaVersion": 1, "product": PRODUCT,
        "result": "BUNDLE_BREAK_GLASS_PREFLIGHT_PASS",
        "checkedAt": datetime.now(timezone.utc).isoformat(),
        "approvalId": request["approvalId"], "ticket": request["ticket"],
        "requestSha256": file_sha256(context["requestPath"]),
        "sourceStateSha256": source_sha256, "sourceDigest": live_digest,
        "targetDigest": target["candidateDigest"],
        "fromSequence": source["rolloutSequence"],
        "targetSequence": target["rolloutSequence"],
        "targetBytes": target_size, "freeBytes": free_bytes,
        "requiredFreeBytes": required_free, "audit": audit, **approval,
        "runtimeStoppedAcknowledged": bool(args.runtime_stopped),
        "applyReady": bool(args.runtime_stopped),
        "repositorySwitchPerformed": False, "highWaterChanged": False,
        "approvalConsumed": False, "temporaryStagingRemoved": not staging.exists(),
    }
    result["evidenceSha256"] = evidence_sha256(result)
    if args.report:
        atomic_json(args.report.resolve(), result)
    return result


def apply_command(args: argparse.Namespace) -> dict[str, Any]:
    if not args.runtime_stopped:
        raise ValueError("break-glass apply requires --runtime-stopped acknowledgement")
    context = operation_context(args)
    state_dir = context["stateDirectory"]
    live_repository = context["liveRepository"]
    target_repository = context["targetRepository"]
    request_path = context["requestPath"]
    request = context["request"]
    approval = context["approval"]
    target = context["target"]
    staging = context["staging"]
    previous = context["previous"]
    consumed = context["consumed"]
    with exclusive_state_lease(state_dir):
        validate_request(request)
        if verify_approval(args, request) != approval:
            raise ValueError("break-glass approval evidence changed while acquiring the state lease")
        high_water_path, source, source_sha256 = high_water(state_dir)
        if consumed.exists():
            raise ValueError("break-glass approval was already consumed")
        if previous.exists():
            raise ValueError("previous Bundle repository already exists")
        if source != request["source"] or source_sha256 != request["sourceStateSha256"]:
            raise ValueError("accepted high-water changed after break-glass approval")
        if repository_digest(args.fingerprint_executable.resolve(), live_repository) != \
                source["candidateDigest"]:
            raise ValueError("current Bundle repository differs from the approved high-water digest")
        pending = active_transactions(state_dir)
        if pending:
            raise ValueError(
                f"unfinished break-glass transaction requires recover: {pending[0]}"
            )
        journal_path = transaction_path(state_dir, request["approvalId"])
        if journal_path.exists():
            raise ValueError("break-glass transaction journal already exists for this approval")
        shutil.copytree(target_repository, staging)
        try:
            staged = argparse.Namespace(**vars(args))
            staged.target_repository = staging
            if authorize_target(staged) != target:
                raise ValueError("staged downgrade target differs from approved authorization")
            journal = {
                "schemaVersion": 1, "product": PRODUCT, "action": ACTION,
                "approvalId": request["approvalId"], "state": "prepared",
                "repository": str(live_repository), "staging": str(staging),
                "previous": str(previous), "requestSha256": file_sha256(request_path),
                "sourceStateSha256": source_sha256, "ticket": request["ticket"],
                "source": source, "target": target, "approval": approval,
            }
            write_transaction(journal_path, journal, exclusive=True)
            authorized_audit = append_audit(state_dir, {
                "event": "BUNDLE_BREAK_GLASS_AUTHORIZED", "approvalId": request["approvalId"],
                "ticket": request["ticket"], "fromSequence": source["rolloutSequence"],
                "targetSequence": target["rolloutSequence"], **approval,
            })
            transition_transaction(journal_path, journal, "authorized",
                                   authorizedAuditSha256=authorized_audit["recordSha256"])
            try:
                live_repository.rename(previous)
                transition_transaction(journal_path, journal, "previousSaved")
                try:
                    staging.rename(live_repository)
                    transition_transaction(journal_path, journal, "activated")
                except Exception:
                    if not live_repository.exists() and previous.exists():
                        previous.rename(live_repository)
                    elif live_repository.exists() and previous.exists():
                        live_repository.rename(staging)
                        previous.rename(live_repository)
                    raise
            except Exception:
                raise
            try:
                write_high_water(high_water_path, target)
            except Exception:
                current = high_water(state_dir)[1]
                if current == source and live_repository.exists() and previous.exists():
                    live_repository.rename(staging)
                    previous.rename(live_repository)
                raise
            transition_transaction(journal_path, journal, "highWaterCommitted")
        finally:
            if staging.exists():
                shutil.rmtree(staging)
        consumption = {
            "schemaVersion": 1, "product": PRODUCT, "approvalId": request["approvalId"],
            "requestSha256": file_sha256(request_path),
            "consumedAt": datetime.now(timezone.utc).isoformat(), "ticket": request["ticket"],
            "source": source, "target": target,
            "authorizedAuditSha256": authorized_audit["recordSha256"], **approval,
        }
        atomic_json(consumed, consumption, exclusive=True)
        transition_transaction(journal_path, journal, "consumed",
                               consumptionSha256=file_sha256(consumed))
        applied_event = {key: value for key, value in consumption.items()
                         if key not in {"schemaVersion", "product"}}
        applied_audit = append_audit(
            state_dir, {"event": "BUNDLE_BREAK_GLASS_APPLIED",
                        "consumptionSha256": file_sha256(consumed), **applied_event})
        transition_transaction(journal_path, journal, "completed",
                               appliedAuditSha256=applied_audit["recordSha256"])
    return {
        "result": "BUNDLE_BREAK_GLASS_APPLIED", "approvalId": request["approvalId"],
        "ticket": request["ticket"], "repository": str(live_repository),
        "previousRepository": str(previous), "fromSequence": source["rolloutSequence"],
        "targetSequence": target["rolloutSequence"], "restartRequired": True,
        "transactionState": journal["state"], "transactionJournal": str(journal_path), **approval,
    }


def audit_records(path: Path) -> list[dict[str, Any]]:
    verify_audit_path(path)
    if not path.exists():
        return []
    return [strict_json(line, "break-glass audit record")
            for line in path.read_bytes().splitlines()]


def consumption_from_transaction(journal: dict[str, Any]) -> dict[str, Any]:
    authorized = journal.get("authorizedAuditSha256")
    if not isinstance(authorized, str) or SHA256.fullmatch(authorized) is None:
        raise ValueError("break-glass transaction lacks authorized audit evidence")
    return {
        "schemaVersion": 1, "product": PRODUCT, "approvalId": journal["approvalId"],
        "requestSha256": journal["requestSha256"],
        "consumedAt": datetime.now(timezone.utc).isoformat(), "ticket": journal["ticket"],
        "source": journal["source"], "target": journal["target"],
        "authorizedAuditSha256": authorized, **journal["approval"],
    }


def recover_command(args: argparse.Namespace) -> dict[str, Any]:
    if not args.runtime_stopped:
        raise ValueError("break-glass recover requires --runtime-stopped acknowledgement")
    try:
        approval_id = str(uuid.UUID(args.approval_id))
    except ValueError as error:
        raise ValueError("break-glass recovery approval ID is malformed") from error
    if approval_id != args.approval_id:
        raise ValueError("break-glass recovery approval ID must use canonical UUID text")
    if args.repository.is_symlink():
        raise ValueError("break-glass recovery repository must not be a symbolic link")
    state_dir = args.state_dir.resolve()
    repository = args.repository.resolve()
    if not repository.parent.is_dir():
        raise ValueError("break-glass recovery repository parent is unavailable")
    checker = args.fingerprint_executable.resolve()
    if not checker.is_file() or same_or_child(checker, repository):
        raise ValueError("trusted Bundle fingerprint checker is unavailable")
    journal_path = transaction_path(state_dir, approval_id)
    with exclusive_state_lease(state_dir):
        journal = read_transaction(journal_path)
        staging = Path(journal["staging"])
        previous = Path(journal["previous"])
        expected_staging = repository.with_name(repository.name + ".pdr-break-glass-staging")
        expected_previous = repository.with_name(repository.name + ".pdr-previous")
        if Path(journal["repository"]) != repository or staging != expected_staging or \
                previous != expected_previous:
            raise ValueError("break-glass transaction paths differ from the recovery target")
        source, target = journal["source"], journal["target"]
        _, current, _ = high_water(state_dir)
        audit_path = state_dir / "break-glass-audit.jsonl"
        records = audit_records(audit_path)

        if journal["state"] == "completed":
            if current != target or repository_digest(checker, repository) != target["candidateDigest"]:
                raise ValueError("completed break-glass transaction no longer matches target state")
            result = "BUNDLE_BREAK_GLASS_RECOVERY_ALREADY_COMPLETED"
        elif journal["state"] == "rolledBack":
            if current != source or repository_digest(checker, repository) != source["candidateDigest"]:
                raise ValueError("rolled-back break-glass transaction no longer matches source state")
            result = "BUNDLE_BREAK_GLASS_RECOVERY_ALREADY_ROLLED_BACK"
        elif current == target:
            if not repository.exists():
                if not staging.is_dir() or repository_digest(checker, staging) != \
                        target["candidateDigest"]:
                    raise ValueError("forward recovery cannot locate the approved target repository")
                staging.rename(repository)
            if repository_digest(checker, repository) != target["candidateDigest"]:
                raise ValueError("committed high-water does not match the active target repository")
            if not previous.is_dir() or repository_digest(checker, previous) != \
                    source["candidateDigest"]:
                raise ValueError("forward recovery requires the exact previous source repository")
            consumed = state_dir / "break-glass-consumed" / f"{approval_id}.json"
            if consumed.exists():
                consumption = strict_json(consumed.read_bytes(), "break-glass consumption record")
                if consumption.get("approvalId") != approval_id or \
                        consumption.get("source") != source or consumption.get("target") != target:
                    raise ValueError("existing break-glass consumption record is inconsistent")
            else:
                consumption = consumption_from_transaction(journal)
                atomic_json(consumed, consumption, exclusive=True)
            consumption_sha = file_sha256(consumed)
            applied = [record for record in records
                       if record.get("event") == "BUNDLE_BREAK_GLASS_APPLIED" and
                       record.get("approvalId") == approval_id]
            if len(applied) > 1:
                raise ValueError("break-glass audit contains duplicate applied records")
            if applied:
                if applied[0].get("consumptionSha256") != consumption_sha:
                    raise ValueError("break-glass applied audit differs from consumption evidence")
                applied_audit = applied[0]
            else:
                applied_event = {key: value for key, value in consumption.items()
                                 if key not in {"schemaVersion", "product"}}
                applied_audit = append_audit(
                    state_dir, {"event": "BUNDLE_BREAK_GLASS_APPLIED",
                                "consumptionSha256": consumption_sha, **applied_event})
            transition_transaction(
                journal_path, journal, "completed", consumptionSha256=consumption_sha,
                appliedAuditSha256=applied_audit["recordSha256"],
                recoveryResult="forward-completed")
            result = "BUNDLE_BREAK_GLASS_RECOVERY_FORWARD_COMPLETED"
        elif current == source:
            live_digest = repository_digest(checker, repository) if repository.is_dir() else None
            if live_digest == target["candidateDigest"]:
                if not previous.is_dir() or repository_digest(checker, previous) != \
                        source["candidateDigest"] or staging.exists():
                    raise ValueError("rollback recovery topology is inconsistent")
                repository.rename(staging)
                previous.rename(repository)
            elif live_digest is None:
                if not previous.is_dir() or repository_digest(checker, previous) != \
                        source["candidateDigest"]:
                    raise ValueError("rollback recovery cannot locate the exact source repository")
                previous.rename(repository)
            elif live_digest != source["candidateDigest"]:
                raise ValueError("rollback recovery active repository matches neither source nor target")
            elif previous.exists():
                raise ValueError("rollback recovery found an unexpected previous repository")
            if staging.exists():
                if repository_digest(checker, staging) != target["candidateDigest"]:
                    raise ValueError("rollback recovery staging repository is not the approved target")
                shutil.rmtree(staging)
            recovery_audit = append_audit(state_dir, {
                "event": "BUNDLE_BREAK_GLASS_RECOVERED_ROLLBACK",
                "approvalId": approval_id, "ticket": journal["ticket"],
                "fromSequence": target["rolloutSequence"],
                "targetSequence": source["rolloutSequence"],
                "transactionState": journal["state"],
            })
            transition_transaction(
                journal_path, journal, "rolledBack",
                recoveryAuditSha256=recovery_audit["recordSha256"],
                recoveryResult="rolled-back-before-high-water")
            result = "BUNDLE_BREAK_GLASS_RECOVERY_ROLLED_BACK"
        else:
            raise ValueError("high-water matches neither transaction source nor target")
    report = {
        "result": result, "approvalId": approval_id, "transactionState": journal["state"],
        "repository": str(repository), "highWaterSequence": current["rolloutSequence"],
        "runtimeRestartRequired": current == target,
    }
    if args.report:
        atomic_json(args.report.resolve(), report)
    return report


def verify_audit_command(args: argparse.Namespace) -> dict[str, Any]:
    state_dir = args.state_dir.resolve()
    if not state_dir.is_dir():
        raise ValueError("break-glass state directory is unavailable")
    with exclusive_state_lease(state_dir):
        evidence = verify_audit_path(state_dir / "break-glass-audit.jsonl")
    result = {"result": "BUNDLE_BREAK_GLASS_AUDIT_VERIFIED",
              "stateDirectory": str(state_dir), **evidence}
    if args.report:
        atomic_json(args.report.resolve(), result)
    return result


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    request = commands.add_parser("request", help="create an unsigned, exact downgrade request")
    request.add_argument("--state-dir", type=Path, required=True)
    request.add_argument("--repository", type=Path, required=True,
                         help="currently deployed repository bound to the accepted high-water")
    target_authorization_arguments(request)
    request.add_argument("--reason", required=True)
    request.add_argument("--ticket", required=True)
    request.add_argument("--valid-for-minutes", type=approval_minutes, default=30)
    request.add_argument("--output", type=Path, required=True)

    approve = commands.add_parser("approve", help="sign a downgrade request on an approval host")
    approve.add_argument("--request", type=Path, required=True)
    approve.add_argument("--approver-id", required=True)
    approve.add_argument("--key-id", required=True)
    approve.add_argument("--private-key-path-environment", required=True)
    approve.add_argument("--private-key-passphrase-environment")
    approve.add_argument("--signature-output", type=Path, required=True)

    def operation_arguments(command: argparse.ArgumentParser) -> None:
        command.add_argument("--state-dir", type=Path, required=True)
        command.add_argument("--repository", type=Path, required=True)
        target_authorization_arguments(command)
        command.add_argument("--request", type=Path, required=True)
        command.add_argument("--signature", type=Path, action="append", required=True,
                             help="approved detached signature; repeat to satisfy M-of-N policy")
        command.add_argument("--approver-trust-policy", type=Path, required=True)
        command.add_argument("--expected-approver-trust-policy-id", required=True)
        command.add_argument("--expected-approver-trust-policy-sha256", required=True)
        command.add_argument("--approver-trusted-keys-directory", type=Path, required=True)
        command.add_argument("--signature-check-executable", type=Path, required=True)

    preflight = commands.add_parser(
        "preflight", help="fully rehearse an approved downgrade without switching repositories")
    operation_arguments(preflight)
    preflight.add_argument("--runtime-stopped", action="store_true")
    preflight.add_argument("--report", type=Path)

    apply = commands.add_parser("apply", help="verify approval and atomically install downgrade")
    operation_arguments(apply)
    apply.add_argument("--runtime-stopped", action="store_true")

    recover = commands.add_parser(
        "recover", help="recover an interrupted downgrade at the durable high-water boundary")
    recover.add_argument("--state-dir", type=Path, required=True)
    recover.add_argument("--repository", type=Path, required=True)
    recover.add_argument("--fingerprint-executable", type=Path, required=True)
    recover.add_argument("--approval-id", required=True)
    recover.add_argument("--runtime-stopped", action="store_true")
    recover.add_argument("--report", type=Path)

    verify_audit = commands.add_parser(
        "verify-audit", help="verify the complete tamper-evident break-glass audit chain")
    verify_audit.add_argument("--state-dir", type=Path, required=True)
    verify_audit.add_argument("--report", type=Path)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv or sys.argv[1:])
    try:
        command = {"request": request_command, "approve": approve_command,
                   "preflight": preflight_command, "apply": apply_command,
                   "recover": recover_command,
                   "verify-audit": verify_audit_command}[args.command]
        print(json.dumps(command(args), ensure_ascii=False, sort_keys=True))
        return 0
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"result": "ERROR", "error": str(error)}, ensure_ascii=False),
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
