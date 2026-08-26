#!/usr/bin/env python3
"""Create and verify portable signed anchors for project configuration audit chains."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import project_config_audit as audit


PRODUCT = "PocoDDSRuntimeProjectConfigurationAuditCheckpoint"
KEY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


def canonical_json(document: Any) -> bytes:
    return json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def digest(document: Any) -> str:
    return hashlib.sha256(canonical_json(document)).hexdigest()


def bytes_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def self_digest(document: dict[str, Any], field: str) -> str:
    return digest({key: value for key, value in document.items() if key != field})


def same_or_child(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def load_json_bytes(content: bytes, description: str) -> dict[str, Any]:
    try:
        document = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read {description}: {error}") from error
    if not isinstance(document, dict):
        raise ValueError(f"{description} root must be an object")
    return document


def exclusive_bytes(path: Path, content: bytes) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(descriptor)


def validate_checkpoint(checkpoint: dict[str, Any]) -> None:
    required = {
        "schemaVersion", "product", "operation", "checkpointId", "createdAt",
        "actor", "project", "recordCount", "verifiedJournalCount", "lastSequence",
        "lastRecordSha256", "auditFileSha256", "headSha256", "checkpointSha256",
    }
    if (set(checkpoint) != required or checkpoint.get("schemaVersion") != 1
            or checkpoint.get("product") != PRODUCT
            or checkpoint.get("operation") != "project-config-audit-checkpoint"
            or audit.validate_actor(checkpoint.get("actor")) != checkpoint["actor"]
            or not isinstance(checkpoint.get("project"), str) or not checkpoint["project"]
            or not isinstance(checkpoint.get("recordCount"), int)
            or not isinstance(checkpoint.get("verifiedJournalCount"), int)
            or not isinstance(checkpoint.get("lastSequence"), int)
            or checkpoint["recordCount"] != checkpoint["lastSequence"]
            or checkpoint["verifiedJournalCount"] > checkpoint["recordCount"]
            or checkpoint["lastSequence"] < 1
            or SHA256.fullmatch(str(checkpoint.get("lastRecordSha256", ""))) is None
            or SHA256.fullmatch(str(checkpoint.get("auditFileSha256", ""))) is None
            or SHA256.fullmatch(str(checkpoint.get("headSha256", ""))) is None
            or checkpoint.get("checkpointSha256") != self_digest(
                checkpoint, "checkpointSha256")):
        raise ValueError("project configuration audit checkpoint is malformed or corrupted")
    try:
        uuid.UUID(checkpoint["checkpointId"])
        created = datetime.fromisoformat(checkpoint["createdAt"].replace("Z", "+00:00"))
        if created.tzinfo is None:
            raise ValueError
    except (ValueError, TypeError, AttributeError) as error:
        raise ValueError("project configuration audit checkpoint identity or time is invalid") from error


def checkpoint_command(args: Any) -> int:
    state = Path(args.state_dir).resolve()
    actor = audit.validate_actor(args.actor)
    result = audit.validate_audit(state, verify_journals=True)
    records, _, _ = audit.read_records(state)
    if not records:
        raise ValueError("cannot checkpoint an empty configuration audit chain")
    key_id = args.key_id
    if not isinstance(key_id, str) or KEY_ID.fullmatch(key_id) is None:
        raise ValueError("configuration audit checkpoint key identity is malformed")
    key_value = os.environ.get(args.private_key_path_environment)
    if not key_value:
        raise ValueError("configuration audit checkpoint private key environment is unset")
    passphrase = None
    if args.private_key_passphrase_environment:
        value = os.environ.get(args.private_key_passphrase_environment)
        if value is None:
            raise ValueError("configuration audit checkpoint key passphrase environment is unset")
        passphrase = value.encode("utf-8")
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
    except ImportError as error:
        raise ValueError("signed audit checkpoint requires the release-host cryptography package") from error
    private_key_path = Path(key_value).resolve()
    if same_or_child(private_key_path, state):
        raise ValueError("checkpoint signing key must be outside configuration state")
    key = load_pem_private_key(private_key_path.read_bytes(), password=passphrase)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("configuration audit checkpoint private key is not Ed25519")
    checkpoint = {
        "schemaVersion": 1,
        "product": PRODUCT,
        "operation": "project-config-audit-checkpoint",
        "checkpointId": args.checkpoint_id or str(uuid.uuid4()),
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "actor": actor,
        "project": records[-1]["project"],
        "recordCount": result["recordCount"],
        "verifiedJournalCount": result["verifiedJournalCount"],
        "lastSequence": result["lastSequence"],
        "lastRecordSha256": result["lastRecordSha256"],
        "auditFileSha256": result["auditFileSha256"],
        "headSha256": result["headSha256"],
    }
    checkpoint["checkpointSha256"] = self_digest(checkpoint, "checkpointSha256")
    validate_checkpoint(checkpoint)
    checkpoint_path = Path(args.output).resolve()
    signature_path = Path(args.signature_output).resolve()
    if same_or_child(checkpoint_path, state) or same_or_child(signature_path, state):
        raise ValueError("checkpoint evidence must be written outside configuration state")
    payload = json.dumps(checkpoint, indent=2, ensure_ascii=False).encode("utf-8") + b"\n"
    signature = {
        "schemaVersion": 1,
        "product": PRODUCT,
        "algorithm": "Ed25519",
        "keyId": key_id,
        "manifestSha256": bytes_sha256(payload),
        "signature": base64.b64encode(key.sign(payload)).decode("ascii"),
    }
    signature_bytes = json.dumps(signature, indent=2).encode("utf-8") + b"\n"
    checkpoint_created = False
    signature_created = False
    try:
        exclusive_bytes(checkpoint_path, payload)
        checkpoint_created = True
        exclusive_bytes(signature_path, signature_bytes)
        signature_created = True
    except Exception:
        if checkpoint_created:
            checkpoint_path.unlink(missing_ok=True)
        if signature_created:
            signature_path.unlink(missing_ok=True)
        raise
    print(
        f"PDR_PROJECT_CONFIG_AUDIT_CHECKPOINT_PASS project={checkpoint['project']} "
        f"sequence={checkpoint['lastSequence']} checkpoint={checkpoint_path}"
    )
    return 0


def verify_checkpoint_command(args: Any) -> int:
    checkpoint_path = Path(args.checkpoint).resolve()
    signature_path = Path(args.signature).resolve()
    public_key_path = Path(args.public_key).resolve()
    verifier = Path(args.signature_check_executable).resolve()
    checkpoint_bytes = checkpoint_path.read_bytes()
    signature_bytes = signature_path.read_bytes()
    public_key_bytes = public_key_path.read_bytes()
    checkpoint = load_json_bytes(checkpoint_bytes, "configuration audit checkpoint")
    validate_checkpoint(checkpoint)
    signature = load_json_bytes(signature_bytes, "configuration audit checkpoint signature")
    if (set(signature) != {
            "schemaVersion", "product", "algorithm", "keyId", "manifestSha256",
            "signature"} or signature.get("schemaVersion") != 1
            or signature.get("product") != PRODUCT
            or signature.get("algorithm") != "Ed25519"
            or signature.get("keyId") != args.expected_key_id
            or signature.get("manifestSha256") != bytes_sha256(checkpoint_bytes)):
        raise ValueError("configuration audit checkpoint signature envelope is malformed")
    expected_public_sha = str(args.expected_public_key_sha256).lower()
    if SHA256.fullmatch(expected_public_sha) is None \
            or bytes_sha256(public_key_bytes) != expected_public_sha:
        raise ValueError("configuration audit checkpoint public key is not pinned")
    if not verifier.is_file():
        raise ValueError("configuration audit checkpoint signature verifier is unavailable")
    if checkpoint["lastSequence"] < args.expected_min_sequence:
        raise ValueError("configuration audit checkpoint sequence is below the required minimum")

    with tempfile.TemporaryDirectory(prefix="pdr-config-audit-checkpoint-") as directory:
        staging = Path(directory)
        staged_checkpoint = staging / "checkpoint.json"
        staged_signature = staging / "signature.json"
        staged_key = staging / "public.pem"
        staged_checkpoint.write_bytes(checkpoint_bytes)
        staged_signature.write_bytes(signature_bytes)
        staged_key.write_bytes(public_key_bytes)
        completed = subprocess.run(
            [str(verifier), str(staged_checkpoint), str(staged_signature),
             str(staged_key), args.expected_key_id, PRODUCT],
            capture_output=True, text=True, check=False,
        )
        if completed.returncode != 0:
            raise ValueError(
                (completed.stderr or completed.stdout).strip()
                or "configuration audit checkpoint signature verification failed"
            )

    current_sequence: int | None = None
    state_verified = False
    if args.state_dir:
        state = Path(args.state_dir).resolve()
        if same_or_child(verifier, state) or same_or_child(public_key_path, state):
            raise ValueError("checkpoint trust material must be outside configuration state")
        result = audit.validate_audit(state, verify_journals=True)
        records, content, lines = audit.read_records(state)
        sequence = checkpoint["lastSequence"]
        if result["lastSequence"] < sequence:
            raise ValueError("current configuration audit chain is older than the checkpoint")
        anchored = records[sequence - 1]
        prefix = b"".join(lines[:sequence])
        if (anchored["recordSha256"] != checkpoint["lastRecordSha256"]
                or bytes_sha256(prefix) != checkpoint["auditFileSha256"]
                or anchored["project"] != checkpoint["project"]):
            raise ValueError("current configuration audit chain does not contain the checkpoint")
        current_sequence = result["lastSequence"]
        state_verified = True

    report = {
        "schemaVersion": 1,
        "operation": "project-config-audit-checkpoint-verify",
        "verifiedAt": datetime.now(timezone.utc).isoformat(),
        "checkpointId": checkpoint["checkpointId"],
        "checkpointSha256": checkpoint["checkpointSha256"],
        "project": checkpoint["project"],
        "checkpointSequence": checkpoint["lastSequence"],
        "currentSequence": current_sequence,
        "stateVerified": state_verified,
        "keyId": args.expected_key_id,
        "publicKeySha256": expected_public_sha,
        "signatureSha256": bytes_sha256(signature_bytes),
    }
    if args.report:
        audit.durable_replace(
            Path(args.report).resolve(),
            json.dumps(report, indent=2, ensure_ascii=False).encode("utf-8") + b"\n",
        )
    print(
        f"PDR_PROJECT_CONFIG_AUDIT_CHECKPOINT_VERIFY_PASS "
        f"project={checkpoint['project']} checkpoint={checkpoint['lastSequence']} "
        f"current={current_sequence if current_sequence is not None else 'not-checked'}"
    )
    return 0
