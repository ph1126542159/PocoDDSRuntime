#!/usr/bin/env python3
"""Durable hash-chained audit for offline project configuration transactions."""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PRODUCT = "PocoDDSRuntimeProjectConfigurationAudit"
AUDIT_FILE = "config-transaction-audit.jsonl"
HEAD_FILE = "config-transaction-audit.head.json"
ACTOR = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._@-]{0,127}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
EVENTS = {
    "CONFIG_TRANSACTION_COMMITTED",
    "CONFIG_TRANSACTION_ROLLED_BACK",
    "CONFIG_TRANSACTION_PREFLIGHT_FAILED",
    "CONFIG_TRANSACTION_ROLLBACK_FAILED",
    "CONFIG_TRANSACTION_RECOVERED_ROLLBACK",
}
TERMINAL_STATUSES = {"committed", "rolled-back", "preflight-failed", "rollback-failed"}
AUDIT_POINTER_FIELDS = {
    "journalSha256", "auditSequence", "auditRecordSha256", "auditEvent",
}


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


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_actor(actor: Any) -> str:
    if not isinstance(actor, str) or ACTOR.fullmatch(actor) is None:
        raise ValueError("configuration transaction actor identity is malformed")
    return actor


def terminal_journal_digest(journal: dict[str, Any]) -> str:
    return digest({
        key: value for key, value in journal.items() if key not in AUDIT_POINTER_FIELDS
    })


def durable_replace(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        if os.name != "nt":
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def write_head(state: Path, records: list[dict[str, Any]], audit_bytes: bytes) -> dict[str, Any]:
    if not records:
        raise ValueError("cannot write an empty configuration audit head")
    head = {
        "schemaVersion": 1,
        "product": PRODUCT,
        "sequence": records[-1]["sequence"],
        "recordSha256": records[-1]["recordSha256"],
        "auditFileSha256": bytes_sha256(audit_bytes),
        "updatedAt": now(),
    }
    head["headSha256"] = self_digest(head, "headSha256")
    durable_replace(
        state / HEAD_FILE,
        json.dumps(head, indent=2, ensure_ascii=False).encode("utf-8") + b"\n",
    )
    return head


def validate_record(record: Any, expected_sequence: int,
                    previous_sha: str | None) -> dict[str, Any]:
    required = {
        "schemaVersion", "product", "sequence", "recordedAt", "event",
        "transactionId", "project", "actor", "status", "journalFile",
        "terminalJournalSha256", "planSha256", "previousRecordSha256",
        "recordSha256",
    }
    if (not isinstance(record, dict) or set(record) != required
            or record.get("schemaVersion") != 1 or record.get("product") != PRODUCT
            or record.get("sequence") != expected_sequence
            or record.get("event") not in EVENTS
            or record.get("status") not in TERMINAL_STATUSES
            or record.get("previousRecordSha256") != previous_sha
            or not isinstance(record.get("project"), str) or not record["project"]
            or validate_actor(record.get("actor")) != record["actor"]
            or not isinstance(record.get("journalFile"), str)
            or Path(record["journalFile"]).name != record["journalFile"]
            or SHA256.fullmatch(str(record.get("terminalJournalSha256", ""))) is None
            or SHA256.fullmatch(str(record.get("planSha256", ""))) is None
            or record.get("recordSha256") != self_digest(record, "recordSha256")):
        raise ValueError(f"configuration audit record is malformed: sequence {expected_sequence}")
    try:
        uuid.UUID(record["transactionId"])
        parsed = datetime.fromisoformat(record["recordedAt"].replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError
    except (ValueError, TypeError, AttributeError) as error:
        raise ValueError(
            f"configuration audit record identity or time is malformed: sequence {expected_sequence}"
        ) from error
    return record


def read_records(state: Path) -> tuple[list[dict[str, Any]], bytes, list[bytes]]:
    audit_path = state / AUDIT_FILE
    if not audit_path.exists():
        if (state / HEAD_FILE).exists():
            raise ValueError("configuration audit head exists without its audit log")
        return [], b"", []
    content = audit_path.read_bytes()
    if content and not content.endswith(b"\n"):
        raise ValueError("configuration audit log has an incomplete final record")
    lines = content.splitlines(keepends=True)
    records: list[dict[str, Any]] = []
    previous: str | None = None
    for index, line in enumerate(lines, start=1):
        try:
            record = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError(f"configuration audit record is unreadable: sequence {index}") from error
        validated = validate_record(record, index, previous)
        records.append(validated)
        previous = validated["recordSha256"]
    return records, content, lines


def read_head(state: Path) -> dict[str, Any] | None:
    path = state / HEAD_FILE
    if not path.exists():
        return None
    try:
        head = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("configuration audit head is unreadable") from error
    required = {
        "schemaVersion", "product", "sequence", "recordSha256",
        "auditFileSha256", "updatedAt", "headSha256",
    }
    if (not isinstance(head, dict) or set(head) != required
            or head.get("schemaVersion") != 1 or head.get("product") != PRODUCT
            or not isinstance(head.get("sequence"), int)
            or SHA256.fullmatch(str(head.get("recordSha256", ""))) is None
            or SHA256.fullmatch(str(head.get("auditFileSha256", ""))) is None
            or head.get("headSha256") != self_digest(head, "headSha256")):
        raise ValueError("configuration audit head is malformed or corrupted")
    return head


def head_matches(head: dict[str, Any], records: list[dict[str, Any]], content: bytes) -> bool:
    return bool(records) and head.get("sequence") == records[-1]["sequence"] \
        and head.get("recordSha256") == records[-1]["recordSha256"] \
        and head.get("auditFileSha256") == bytes_sha256(content)


def reconcile_head(state: Path, records: list[dict[str, Any]], content: bytes,
                   lines: list[bytes]) -> dict[str, Any] | None:
    head = read_head(state)
    if not records:
        if head is not None:
            raise ValueError("configuration audit head exists for an empty log")
        return None
    if head is not None and head_matches(head, records, content):
        return head
    repairable = False
    if head is None and len(records) == 1:
        repairable = True
    elif head is not None and head.get("sequence") == len(records) - 1:
        prefix = b"".join(lines[:-1])
        previous = records[-2]
        repairable = head.get("recordSha256") == previous["recordSha256"] \
            and head.get("auditFileSha256") == bytes_sha256(prefix)
    if not repairable:
        raise ValueError("configuration audit head differs from the audit log")
    return write_head(state, records, content)


def append_terminal_record(state: Path, journal_path: Path, journal: dict[str, Any],
                           actor: str, event: str) -> dict[str, Any]:
    actor = validate_actor(actor)
    if event not in EVENTS or journal.get("status") not in TERMINAL_STATUSES:
        raise ValueError("configuration terminal audit event or status is invalid")
    records, content, lines = read_records(state)
    reconcile_head(state, records, content, lines)
    terminal_sha = terminal_journal_digest(journal)
    for record in records:
        if record["transactionId"] == journal["transactionId"] \
                and record["event"] == event and record["status"] == journal["status"]:
            if record["terminalJournalSha256"] != terminal_sha:
                raise ValueError("configuration audit already has conflicting terminal evidence")
            return record
    record = {
        "schemaVersion": 1,
        "product": PRODUCT,
        "sequence": len(records) + 1,
        "recordedAt": now(),
        "event": event,
        "transactionId": journal["transactionId"],
        "project": journal["project"],
        "actor": actor,
        "status": journal["status"],
        "journalFile": journal_path.name,
        "terminalJournalSha256": terminal_sha,
        "planSha256": journal["planSha256"],
        "previousRecordSha256": records[-1]["recordSha256"] if records else None,
    }
    record["recordSha256"] = self_digest(record, "recordSha256")
    line = canonical_json(record) + b"\n"
    audit_path = state / AUDIT_FILE
    descriptor = os.open(audit_path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "ab") as stream:
        stream.write(line)
        stream.flush()
        os.fsync(stream.fileno())
    records.append(record)
    content += line
    write_head(state, records, content)
    return record


def validate_audit(state: Path, verify_journals: bool = True) -> dict[str, Any]:
    state = state.resolve()
    records, content, _ = read_records(state)
    head = read_head(state)
    if records:
        if head is None or not head_matches(head, records, content):
            raise ValueError("configuration audit head differs from the audit log")
        projects = {record["project"] for record in records}
        if len(projects) != 1:
            raise ValueError("configuration audit log mixes multiple projects")
    elif head is not None:
        raise ValueError("configuration audit head exists for an empty log")

    v3_journals: list[Path] = []
    if state.is_dir():
        for path in sorted(state.glob("*.journal.json")):
            try:
                journal = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                raise ValueError(f"configuration transaction journal is unreadable: {path}") from error
            if journal.get("schemaVersion") == 3 and journal.get("status") in TERMINAL_STATUSES:
                v3_journals.append(path)
    if v3_journals and not records:
        raise ValueError("audited configuration journals exist without an audit log")

    verified_journals = 0
    if verify_journals:
        latest: dict[str, dict[str, Any]] = {}
        for record in records:
            latest[record["transactionId"]] = record
        for transaction_id, record in latest.items():
            path = state / record["journalFile"]
            if not path.is_file():
                raise ValueError(f"configuration audit journal is missing: {path}")
            journal = json.loads(path.read_text(encoding="utf-8"))
            if (journal.get("transactionId") != transaction_id
                    or journal.get("auditSequence") != record["sequence"]
                    or journal.get("auditRecordSha256") != record["recordSha256"]
                    or journal.get("auditEvent") != record["event"]
                    or journal.get("journalSha256") != self_digest(journal, "journalSha256")
                    or terminal_journal_digest(journal) != record["terminalJournalSha256"]):
                raise ValueError(
                    f"configuration audit and journal binding mismatch: {transaction_id}"
                )
            verified_journals += 1
        for path in v3_journals:
            journal = json.loads(path.read_text(encoding="utf-8"))
            if journal.get("transactionId") not in latest:
                raise ValueError(f"configuration terminal journal is absent from audit: {path}")
    return {
        "recordCount": len(records),
        "verifiedJournalCount": verified_journals,
        "lastSequence": records[-1]["sequence"] if records else 0,
        "lastRecordSha256": records[-1]["recordSha256"] if records else None,
        "auditFileSha256": bytes_sha256(content),
        "headSha256": head["headSha256"] if head else None,
    }


def verify_command(args: Any) -> int:
    state = Path(args.state_dir).resolve()
    result = validate_audit(state, verify_journals=True)
    report = {
        "schemaVersion": 1,
        "operation": "project-config-audit-verify",
        "verifiedAt": now(),
        "stateDirectory": str(state),
        **result,
    }
    if args.report:
        report_path = Path(args.report).resolve()
        durable_replace(
            report_path,
            json.dumps(report, indent=2, ensure_ascii=False).encode("utf-8") + b"\n",
        )
    print(
        f"PDR_PROJECT_CONFIG_AUDIT_VERIFY_PASS records={result['recordCount']} "
        f"journals={result['verifiedJournalCount']} sequence={result['lastSequence']}"
    )
    return 0
