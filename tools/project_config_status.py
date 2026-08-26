#!/usr/bin/env python3
"""Read-only collaboration status for project configuration transactions."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import project_config_audit as audit
import project_config_transaction as transaction
import project_manager


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def valid_time(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("time is not a string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("time has no timezone")
    return value


def inspect_lock(state: Path, root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    path = state / "config-transaction.lock"
    base = {
        "status": "free", "path": relative(root, path), "pid": None,
        "transactionId": None, "processIdentity": None, "actor": None,
        "error": None,
    }
    if not path.exists():
        return base, []
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise ValueError("root must be an object")
        pid = document.get("pid")
        transaction_id = document.get("transactionId")
        process_identity = document.get("processIdentity")
        actor = document.get("actor")
        if not isinstance(pid, int) or pid < 1:
            raise ValueError("pid is invalid")
        uuid.UUID(transaction_id)
        if process_identity is not None and not isinstance(process_identity, str):
            raise ValueError("process identity is invalid")
        if actor is not None:
            actor = audit.validate_actor(actor)
        observed_identity = transaction.process_identity(pid)
        identity_matches = (
            process_identity is None
            or observed_identity is None
            or observed_identity == process_identity
        )
        lock_status = (
            "active" if transaction.process_alive(pid) and identity_matches else "stale"
        )
        result = {
            **base, "status": lock_status, "pid": pid,
            "transactionId": transaction_id,
            "processIdentity": process_identity, "actor": actor,
        }
        issue = {
            "code": "CONFIG_TRANSACTION_ACTIVE" if lock_status == "active"
                    else "CONFIG_TRANSACTION_STALE_LOCK",
            "severity": "info" if lock_status == "active" else "warning",
            "message": (
                f"configuration transaction {transaction_id} is active with pid {pid}"
                if lock_status == "active" else
                f"stale configuration transaction lock will be recovered on the next operation: {path}"
            ),
        }
        return result, [issue]
    except (OSError, ValueError, TypeError, AttributeError, json.JSONDecodeError) as error:
        message = f"configuration transaction lock is invalid: {path}: {error}"
        return {
            **base, "status": "invalid", "error": message,
        }, [{
            "code": "CONFIG_TRANSACTION_LOCK_INVALID",
            "severity": "blocker", "message": message,
        }]


def inspect_transactions(state: Path, root: Path, project: str,
                         participants: dict[str, dict[str, Any]],
                         lock: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    items: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    if state.is_dir():
        paths = sorted(state.glob("*.journal.json"))
    else:
        paths = []
    for path in paths:
        item: dict[str, Any] = {
            "journal": relative(root, path), "transactionId": None, "status": None,
            "initiatedBy": None, "startedAt": None, "finishedAt": None,
            "disposition": "invalid", "auditSequence": None, "error": None,
        }
        try:
            journal = transaction.load_json(path, "configuration transaction journal")
            if journal.get("operation") != "project-config-transaction":
                raise ValueError("operation is invalid")
            if journal.get("project") != project:
                raise ValueError("journal belongs to another project")
            transaction_id = journal.get("transactionId")
            uuid.UUID(transaction_id)
            status = journal.get("status")
            if status not in transaction.TRANSACTION_STATUSES:
                raise ValueError("status is invalid")
            version = journal.get("schemaVersion")
            if version not in (1, 2, transaction.JOURNAL_SCHEMA_VERSION):
                raise ValueError("schema version is unsupported")
            if isinstance(version, int) and version >= 2:
                transaction.validate_self_digest(
                    journal, "journalSha256", "configuration transaction journal"
                )
            initiated_by = journal.get("initiatedBy")
            if initiated_by is not None:
                initiated_by = audit.validate_actor(initiated_by)
            item.update({
                "transactionId": transaction_id,
                "status": status,
                "initiatedBy": initiated_by,
                "startedAt": valid_time(journal.get("startedAt")),
                "finishedAt": valid_time(journal.get("finishedAt")),
                "auditSequence": journal.get("auditSequence"),
            })
            if (item["auditSequence"] is not None
                    and (not isinstance(item["auditSequence"], int)
                         or item["auditSequence"] < 1)):
                raise ValueError("audit sequence is invalid")
            missing_terminal_audit = (
                version == transaction.JOURNAL_SCHEMA_VERSION
                and status in transaction.TERMINAL_STATUSES
                and not {"auditSequence", "auditRecordSha256", "auditEvent"}.issubset(journal)
            )
            unfinished = status not in transaction.TERMINAL_STATUSES or missing_terminal_audit
            if unfinished:
                transaction.validate_journal(journal, participants)
                if (lock["status"] == "active"
                        and lock["transactionId"] == transaction_id):
                    item["disposition"] = "running"
                else:
                    item["disposition"] = "recovery-required"
                    issues.append({
                        "code": "CONFIG_TRANSACTION_RECOVERY_REQUIRED",
                        "severity": "blocker",
                        "message": (
                            f"configuration transaction {transaction_id} requires recovery "
                            f"from {item['journal']}"
                        ),
                        "journal": item["journal"],
                    })
            else:
                item["disposition"] = "terminal"
        except (OSError, ValueError, TypeError, AttributeError, json.JSONDecodeError) as error:
            item["error"] = str(error)
            issues.append({
                "code": "CONFIG_TRANSACTION_JOURNAL_INVALID",
                "severity": "blocker",
                "message": f"configuration transaction journal is invalid: {path}: {error}",
                "journal": item["journal"],
            })
        items.append(item)
    return {
        "total": len(items),
        "terminal": sum(item["disposition"] == "terminal" for item in items),
        "running": sum(item["disposition"] == "running" for item in items),
        "recoveryRequired": sum(
            item["disposition"] == "recovery-required" for item in items
        ),
        "invalid": sum(item["disposition"] == "invalid" for item in items),
        "items": items,
    }, issues


def inspect_audit(state: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    base = {
        "status": "empty", "recordCount": 0, "verifiedJournalCount": 0,
        "lastSequence": 0, "lastRecordSha256": None, "auditFileSha256": None,
        "headSha256": None, "error": None,
    }
    try:
        result = audit.validate_audit(state, verify_journals=True)
        return {
            **base, **result,
            "status": "valid" if result["recordCount"] else "empty",
        }, []
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        message = f"configuration transaction audit is invalid: {error}"
        return {
            **base, "status": "invalid", "error": message,
        }, [{
            "code": "CONFIG_TRANSACTION_AUDIT_INVALID",
            "severity": "blocker", "message": message,
        }]


def validate_report(report: dict[str, Any]) -> None:
    transactions = report["transactions"]
    counted = (
        transactions["terminal"] + transactions["running"]
        + transactions["recoveryRequired"] + transactions["invalid"]
    )
    if transactions["total"] != len(transactions["items"]) or counted != transactions["total"]:
        raise RuntimeError("configuration transaction status counts are inconsistent")
    if report["canApply"] != (report["overallStatus"] == "ready"):
        raise RuntimeError("configuration transaction apply readiness is inconsistent")
    lock = report["lock"]
    if lock["status"] == "free" and any(
            lock[field] is not None
            for field in ("pid", "transactionId", "processIdentity", "actor", "error")):
        raise RuntimeError("free configuration transaction lock has owner state")
    if lock["status"] in {"active", "stale"} and (
            lock["pid"] is None or lock["transactionId"] is None
            or lock["error"] is not None):
        raise RuntimeError("owned configuration transaction lock is incomplete")
    if lock["status"] == "invalid" and not lock["error"]:
        raise RuntimeError("invalid configuration transaction lock has no error")
    audit_status = report["audit"]
    if audit_status["status"] == "empty" and (
            audit_status["recordCount"] != 0 or audit_status["lastSequence"] != 0):
        raise RuntimeError("empty configuration transaction audit has records")
    if audit_status["status"] == "valid" and (
            audit_status["recordCount"] < 1
            or audit_status["recordCount"] != audit_status["lastSequence"]):
        raise RuntimeError("valid configuration transaction audit counts are inconsistent")


def status_command(args: Any) -> int:
    manifest = Path(args.manifest).resolve()
    project_document = project_manager.validate_manifest(manifest, check_paths=True)
    root = manifest.parent
    state = transaction.confined_path(
        root, args.state_dir, "configuration transaction state directory"
    )
    _, participants, _ = transaction.load_capabilities(manifest)
    lock, lock_issues = inspect_lock(state, root)
    transactions, transaction_issues = inspect_transactions(
        state, root, project_document["name"], participants, lock
    )
    audit_status, audit_issues = inspect_audit(state)
    issues = lock_issues + transaction_issues + audit_issues
    invalid = (
        lock["status"] == "invalid" or transactions["invalid"] > 0
        or audit_status["status"] == "invalid"
    )
    if invalid:
        overall = "invalid"
    elif transactions["recoveryRequired"]:
        overall = "recovery-required"
    elif lock["status"] == "active":
        overall = "busy"
    else:
        overall = "ready"
    report = {
        "schemaVersion": 1,
        "operation": "project-config-transaction-status",
        "observedAt": now(),
        "project": project_document["name"],
        "stateDirectory": relative(root, state),
        "overallStatus": overall,
        "canApply": overall == "ready",
        "lock": lock,
        "transactions": transactions,
        "audit": audit_status,
        "issues": issues,
    }
    validate_report(report)
    if args.report:
        report_path = transaction.confined_path(
            root, args.report, "configuration transaction status report"
        )
        transaction.durable_replace(
            report_path,
            json.dumps(report, indent=2, ensure_ascii=False).encode("utf-8") + b"\n",
        )
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(
            f"PDR_PROJECT_CONFIG_STATUS status={overall} "
            f"canApply={str(report['canApply']).lower()} "
            f"transactions={transactions['total']} "
            f"recoveryRequired={transactions['recoveryRequired']} "
            f"audit={audit_status['status']}"
        )
        for item in transactions["items"]:
            if item["disposition"] == "recovery-required":
                print(
                    f"PDR_PROJECT_CONFIG_RECOVERY_REQUIRED "
                    f"transaction={item['transactionId']} status={item['status']} "
                    f"initiatedBy={item['initiatedBy'] or 'unknown'} "
                    f"journal={item['journal']}"
                )
    return 2 if args.check and not report["canApply"] else 0
