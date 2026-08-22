#!/usr/bin/env python3
"""Plan, apply and recover project configuration transactions."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import subprocess
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


PROTOCOL = "pdr-config-transaction/1"
CAPABILITY_MODES = {"hot-reload", "restart", "immutable"}
TERMINAL_STATUSES = {"committed", "rolled-back", "preflight-failed"}
TRANSACTION_STATUSES = {
    "preflighting", "preflight-failed", "committing", "activating",
    "rolling-back", "rolled-back", "rollback-failed", "committed",
}
PARTICIPANT_ID = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$")
POINTER_TOKEN = re.compile(r"(?:[^~/]|~[01])+")
MISSING = object()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_json(document: Any) -> bytes:
    return json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def digest(document: Any) -> str:
    return hashlib.sha256(canonical_json(document)).hexdigest()


def load_json(path: Path, description: str) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read {description}: {path}: {error}") from error
    if not isinstance(document, dict):
        raise ValueError(f"{description} root must be an object: {path}")
    return document


def atomic_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def confined_path(root: Path, value: str | Path, field: str,
                  must_exist: bool = False) -> Path:
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = candidate.resolve()
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise ValueError(f"{field} must stay inside the project root") from error
    if must_exist and not candidate.is_file():
        raise FileNotFoundError(f"{field} not found: {candidate}")
    return candidate


def relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root).as_posix()


def validate_pointer(pointer: Any, field: str) -> str:
    if (not isinstance(pointer, str) or not pointer.startswith("/") or pointer == "/"
            or any(not POINTER_TOKEN.fullmatch(token) for token in pointer[1:].split("/"))):
        raise ValueError(f"{field} must be a non-root JSON Pointer")
    return pointer


def pointer_contains(prefix: str, pointer: str) -> bool:
    return pointer == prefix or pointer.startswith(prefix + "/")


def topological_order(participants: dict[str, dict[str, Any]]) -> list[str]:
    remaining = {name: set(item["after"]) for name, item in participants.items()}
    ordered: list[str] = []
    while remaining:
        ready = sorted(name for name, dependencies in remaining.items() if not dependencies)
        if not ready:
            raise ValueError(
                "configuration participant dependency cycle: " + ", ".join(sorted(remaining))
            )
        for name in ready:
            ordered.append(name)
            del remaining[name]
        for dependencies in remaining.values():
            dependencies.difference_update(ready)
    return ordered


def load_capabilities(manifest: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]], Path]:
    import project_manager

    project = project_manager.validate_manifest(manifest, check_paths=True)
    root = manifest.parent
    configured = project["config"].get("capabilities")
    if not configured:
        raise ValueError(
            "config.capabilities is required for configuration transactions"
        )
    path = confined_path(root, configured, "config.capabilities", must_exist=True)
    document = load_json(path, "configuration capability document")
    if set(document) != {"schemaVersion", "participants"}:
        raise ValueError(
            "configuration capability document must contain only schemaVersion and participants"
        )
    if document["schemaVersion"] != 1:
        raise ValueError("configuration capability schemaVersion must be 1")
    raw_participants = document["participants"]
    if not isinstance(raw_participants, list):
        raise ValueError("configuration capability participants must be an array")

    participants: dict[str, dict[str, Any]] = {}
    all_owners: list[tuple[str, str]] = []
    for index, raw in enumerate(raw_participants):
        field = f"participants[{index}]"
        if not isinstance(raw, dict):
            raise ValueError(f"{field} must be an object")
        allowed = {"id", "ownedPaths", "mode", "after", "timeoutSeconds", "command"}
        if set(raw) - allowed:
            raise ValueError(f"{field} contains unknown fields")
        identifier = raw.get("id")
        if not isinstance(identifier, str) or not PARTICIPANT_ID.fullmatch(identifier):
            raise ValueError(f"{field}.id must be lowercase kebab-case or dotted lowercase")
        if identifier in participants:
            raise ValueError(f"duplicate configuration participant: {identifier}")
        owned = raw.get("ownedPaths")
        if not isinstance(owned, list) or not owned:
            raise ValueError(f"{field}.ownedPaths must be a non-empty array")
        normalized_owned = [validate_pointer(item, f"{field}.ownedPaths") for item in owned]
        if len(normalized_owned) != len(set(normalized_owned)):
            raise ValueError(f"{field}.ownedPaths contains duplicates")
        mode = raw.get("mode")
        if mode not in CAPABILITY_MODES:
            raise ValueError(f"{field}.mode must be hot-reload, restart or immutable")
        after = raw.get("after", [])
        if (not isinstance(after, list) or any(
                not isinstance(item, str) or not PARTICIPANT_ID.fullmatch(item)
                for item in after) or len(after) != len(set(after))):
            raise ValueError(f"{field}.after must contain unique participant identifiers")
        timeout = raw.get("timeoutSeconds", 30)
        if (not isinstance(timeout, (int, float)) or isinstance(timeout, bool)
                or not 0.1 <= timeout <= 300):
            raise ValueError(f"{field}.timeoutSeconds must be from 0.1 to 300")
        command = raw.get("command", [])
        if (not isinstance(command, list) or any(
                not isinstance(item, str) or not item for item in command)):
            raise ValueError(f"{field}.command must be an argv string array")
        if mode == "hot-reload" and not command:
            raise ValueError(f"{field}.command is required for hot-reload")
        participants[identifier] = {
            "id": identifier,
            "ownedPaths": normalized_owned,
            "mode": mode,
            "after": list(after),
            "timeoutSeconds": float(timeout),
            "command": list(command),
        }
        all_owners.extend((pointer, identifier) for pointer in normalized_owned)

    for identifier, participant in participants.items():
        for dependency in participant["after"]:
            if dependency == identifier:
                raise ValueError(f"configuration participant cannot depend on itself: {identifier}")
            if dependency not in participants:
                raise ValueError(
                    f"configuration participant {identifier} has unknown dependency: {dependency}"
                )
    for index, (left, left_owner) in enumerate(all_owners):
        for right, right_owner in all_owners[index + 1:]:
            if left_owner != right_owner and (
                    pointer_contains(left, right) or pointer_contains(right, left)):
                raise ValueError(
                    f"configuration ownership overlaps between {left_owner}:{left} and "
                    f"{right_owner}:{right}"
                )
    topological_order(participants)
    normalized = {
        "schemaVersion": 1,
        "participants": [participants[name] for name in sorted(participants)],
    }
    return normalized, participants, path


def load_resolved(path: Path, project_name: str) -> dict[str, Any]:
    document = load_json(path, "resolved configuration")
    required = {
        "schemaVersion", "operation", "project", "sourceVersion", "configVersion",
        "layers", "migrations", "environmentReferences", "missingEnvironmentReferences",
        "valuesSha256", "values",
    }
    if set(document) != required:
        raise ValueError(f"resolved configuration has an unexpected envelope: {path}")
    if document["schemaVersion"] != 1 or document["operation"] != "project-config-resolve":
        raise ValueError(f"unsupported resolved configuration contract: {path}")
    if document["project"] != project_name:
        raise ValueError(
            f"resolved configuration belongs to {document['project']}, expected {project_name}"
        )
    if not isinstance(document["values"], dict):
        raise ValueError(f"resolved configuration values must be an object: {path}")
    actual = digest(document["values"])
    if document["valuesSha256"] != actual:
        raise ValueError(f"resolved configuration values digest mismatch: {path}")
    return document


def escape_pointer(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def value_changes(before: Any, after: Any, path: str = "") -> list[dict[str, str]]:
    if before is MISSING and isinstance(after, dict) and after:
        changes: list[dict[str, str]] = []
        for key in sorted(after):
            changes.extend(value_changes(MISSING, after[key], path + "/" + escape_pointer(key)))
        return changes
    if after is MISSING and isinstance(before, dict) and before:
        changes = []
        for key in sorted(before):
            changes.extend(value_changes(before[key], MISSING, path + "/" + escape_pointer(key)))
        return changes
    if isinstance(before, dict) and isinstance(after, dict):
        changes: list[dict[str, str]] = []
        for key in sorted(set(before) | set(after)):
            pointer = path + "/" + escape_pointer(key)
            if key not in before:
                changes.extend(value_changes(MISSING, after[key], pointer))
            elif key not in after:
                changes.extend(value_changes(before[key], MISSING, pointer))
            else:
                changes.extend(value_changes(before[key], after[key], pointer))
        return changes
    if before is MISSING:
        return [{"path": path or "/", "kind": "added"}]
    if after is MISSING:
        return [{"path": path or "/", "kind": "removed"}]
    if before != after or type(before) is not type(after):
        return [{"path": path or "/", "kind": "changed"}]
    return []


def bind_change(change: dict[str, str], participants: dict[str, dict[str, Any]]) -> dict[str, str]:
    owners = sorted(
        participant["id"]
        for participant in participants.values()
        if any(pointer_contains(pointer, change["path"])
               for pointer in participant["ownedPaths"])
    )
    result = dict(change)
    if not owners:
        result.update({"participant": "", "mode": "unowned"})
    elif len(owners) > 1:
        raise ValueError(f"configuration path has multiple owners: {change['path']}")
    else:
        result.update({"participant": owners[0], "mode": participants[owners[0]]["mode"]})
    return result


def create_plan(manifest: Path, current_path: Path, candidate_path: Path) -> dict[str, Any]:
    import project_manager

    manifest = manifest.resolve()
    project = project_manager.validate_manifest(manifest, check_paths=True)
    root = manifest.parent
    capabilities, participants, capability_path = load_capabilities(manifest)
    current_path = confined_path(root, current_path, "current configuration", must_exist=True)
    candidate_path = confined_path(root, candidate_path, "candidate configuration", must_exist=True)
    current = load_resolved(current_path, project["name"])
    candidate = load_resolved(candidate_path, project["name"])
    changes = [bind_change(change, participants)
               for change in value_changes(current["values"], candidate["values"])]
    affected = {change["participant"] for change in changes if change["participant"]}
    ordered = [name for name in topological_order(participants) if name in affected]
    reasons = sorted(
        ({"UNOWNED_CONFIGURATION_PATH"} if any(
            change["mode"] == "unowned" for change in changes) else set())
        | ({"IMMUTABLE_CONFIGURATION_CHANGED"} if any(
            change["mode"] == "immutable" for change in changes) else set())
    )
    requires_restart = any(change["mode"] == "restart" for change in changes)
    return {
        "schemaVersion": 1,
        "operation": "project-config-plan",
        "transactionId": str(uuid.uuid4()),
        "createdAt": now(),
        "project": project["name"],
        "manifestSha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "capabilities": {
            "path": relative(root, capability_path),
            "sha256": digest(capabilities),
        },
        "current": {
            "path": relative(root, current_path),
            "documentSha256": digest(current),
            "valuesSha256": current["valuesSha256"],
            "configVersion": current["configVersion"],
        },
        "candidate": {
            "path": relative(root, candidate_path),
            "documentSha256": digest(candidate),
            "valuesSha256": candidate["valuesSha256"],
            "configVersion": candidate["configVersion"],
        },
        "changes": changes,
        "participants": [
            {"id": name, "mode": participants[name]["mode"], "order": index}
            for index, name in enumerate(ordered)
        ],
        "requiresRestart": requires_restart,
        "applicable": not reasons,
        "rejectionReasons": reasons,
    }


def plan_command(args: Any) -> int:
    manifest = Path(args.manifest).resolve()
    root = manifest.parent
    output = confined_path(root, args.output, "transaction plan output")
    plan = create_plan(manifest, Path(args.current), Path(args.candidate))
    atomic_json(output, plan)
    marker = "PASS" if plan["applicable"] else "REJECTED"
    print(
        f"PDR_PROJECT_CONFIG_PLAN_{marker} transaction={plan['transactionId']} "
        f"changes={len(plan['changes'])} participants={len(plan['participants'])} "
        f"output={output}"
    )
    return 0 if plan["applicable"] else 2


def validate_plan(plan: dict[str, Any], manifest: Path, capabilities: dict[str, Any],
                  current: dict[str, Any], candidate: dict[str, Any]) -> None:
    if plan.get("schemaVersion") != 1 or plan.get("operation") != "project-config-plan":
        raise ValueError("unsupported configuration transaction plan")
    try:
        uuid.UUID(plan.get("transactionId", ""))
    except (ValueError, TypeError) as error:
        raise ValueError("configuration transaction plan has an invalid transactionId") from error
    bindings = (
        (plan.get("manifestSha256"), hashlib.sha256(manifest.read_bytes()).hexdigest(), "manifest"),
        (plan.get("capabilities", {}).get("sha256"), digest(capabilities), "capabilities"),
        (plan.get("current", {}).get("documentSha256"), digest(current), "current configuration"),
        (plan.get("candidate", {}).get("documentSha256"), digest(candidate), "candidate configuration"),
    )
    for expected, actual, label in bindings:
        if expected != actual:
            raise ValueError(f"configuration transaction plan has stale {label}")
    if not plan.get("applicable"):
        raise ValueError(
            "configuration transaction plan is not applicable: "
            + ", ".join(plan.get("rejectionReasons", []))
        )


def validate_plan_semantics(plan: dict[str, Any], expected: dict[str, Any]) -> None:
    for field in (
            "project", "manifestSha256", "capabilities", "candidate", "changes",
            "participants", "requiresRestart", "applicable", "rejectionReasons"):
        if plan.get(field) != expected.get(field):
            raise ValueError(f"configuration transaction plan semantics mismatch: {field}")
    current = plan.get("current")
    expected_current = expected.get("current")
    if not isinstance(current, dict) or not isinstance(expected_current, dict):
        raise ValueError("configuration transaction plan has an invalid current binding")
    for field in ("documentSha256", "valuesSha256", "configVersion"):
        if current.get(field) != expected_current.get(field):
            raise ValueError(
                f"configuration transaction plan semantics mismatch: current.{field}"
            )


def validate_journal(journal: dict[str, Any], participants: dict[str, dict[str, Any]]) -> None:
    if (journal.get("schemaVersion") != 1
            or journal.get("operation") != "project-config-transaction"):
        raise ValueError("unsupported configuration transaction journal")
    try:
        uuid.UUID(journal.get("transactionId", ""))
    except (ValueError, TypeError) as error:
        raise ValueError("configuration transaction journal has an invalid transactionId") from error
    if journal.get("status") not in TRANSACTION_STATUSES:
        raise ValueError("configuration transaction journal has an invalid status")
    for field in (
            "preflightCompleted", "commitAttempted", "commitCompleted", "rollbackCompleted"):
        values = journal.get(field)
        if (not isinstance(values, list) or len(values) != len(set(values))
                or any(value not in participants for value in values)):
            raise ValueError(f"configuration transaction journal has invalid {field}")
    if not set(journal["commitCompleted"]).issubset(journal["commitAttempted"]):
        raise ValueError("configuration transaction journal completed a commit never attempted")
    if not set(journal["rollbackCompleted"]).issubset(journal["commitAttempted"]):
        raise ValueError("configuration transaction journal rolled back a commit never attempted")
    if not isinstance(journal.get("events"), list) or not isinstance(journal.get("errors"), list):
        raise ValueError("configuration transaction journal events and errors must be arrays")


def invoke(participant: dict[str, Any], phase: str, plan: dict[str, Any], root: Path,
           current: Path, candidate: Path, journal: Path,
           changed_paths: list[str]) -> dict[str, Any]:
    command = participant["command"]
    if not command:
        raise ValueError(
            f"configuration participant {participant['id']} has no transaction command"
        )
    request = {
        "schemaVersion": 1,
        "protocol": PROTOCOL,
        "transactionId": plan["transactionId"],
        "phase": phase,
        "participant": participant["id"],
        "mode": participant["mode"],
        "changedPaths": changed_paths,
        "currentConfig": str(current),
        "candidateConfig": str(candidate),
        "journal": str(journal),
    }
    try:
        completed = subprocess.run(
            command,
            input=json.dumps(request, separators=(",", ":"), ensure_ascii=False),
            capture_output=True,
            text=True,
            cwd=root,
            timeout=participant["timeoutSeconds"],
            shell=False,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError(
            f"configuration participant {participant['id']} {phase} invocation failed"
        ) from error
    if completed.returncode != 0:
        raise RuntimeError(
            f"configuration participant {participant['id']} {phase} returned "
            f"exit code {completed.returncode}"
        )
    try:
        response = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError(
            f"configuration participant {participant['id']} {phase} returned invalid JSON"
        ) from error
    expected_status = {"preflight": "ready", "commit": "committed", "rollback": "rolled-back"}[phase]
    if (not isinstance(response, dict)
            or response.get("schemaVersion") != 1
            or response.get("transactionId") != plan["transactionId"]
            or response.get("participant") != participant["id"]
            or response.get("status") != expected_status):
        raise RuntimeError(
            f"configuration participant {participant['id']} {phase} protocol response mismatch"
        )
    return {
        "participant": participant["id"],
        "phase": phase,
        "status": expected_status,
        "responseSha256": digest(response),
        "finishedAt": now(),
    }


def process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except (PermissionError, OSError):
        return True
    return True


@contextlib.contextmanager
def transaction_lock(state: Path, transaction_id: str) -> Iterator[None]:
    state.mkdir(parents=True, exist_ok=True)
    lock = state / "config-transaction.lock"
    payload = json.dumps({"pid": os.getpid(), "transactionId": transaction_id})
    while True:
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(payload)
            break
        except FileExistsError:
            try:
                owner = json.loads(lock.read_text(encoding="utf-8"))
                owner_pid = int(owner.get("pid", 0))
            except (OSError, ValueError, json.JSONDecodeError, AttributeError) as error:
                raise RuntimeError(f"configuration transaction lock is invalid: {lock}") from error
            if process_alive(owner_pid):
                raise RuntimeError(
                    f"configuration transaction is already running with pid {owner_pid}"
                )
            try:
                lock.unlink()
            except OSError as error:
                raise RuntimeError(f"cannot recover stale transaction lock: {lock}") from error
    try:
        yield
    finally:
        try:
            current = json.loads(lock.read_text(encoding="utf-8"))
            if current.get("pid") == os.getpid() and current.get("transactionId") == transaction_id:
                lock.unlink()
        except (OSError, json.JSONDecodeError, AttributeError):
            pass


def activate(source: Path, destination: Path) -> None:
    data = source.read_bytes()
    temporary = destination.with_name(destination.name + ".activate.tmp")
    temporary.write_bytes(data)
    temporary.replace(destination)


def changed_paths(plan: dict[str, Any], participant_id: str) -> list[str]:
    return [change["path"] for change in plan["changes"]
            if change["participant"] == participant_id]


def rollback_attempted(journal: dict[str, Any], plan: dict[str, Any],
                       participants: dict[str, dict[str, Any]], root: Path,
                       current: Path, candidate: Path, journal_path: Path) -> list[str]:
    errors: list[str] = []
    journal["status"] = "rolling-back"
    atomic_json(journal_path, journal)
    for identifier in reversed(journal["commitAttempted"]):
        if identifier in journal["rollbackCompleted"]:
            continue
        try:
            evidence = invoke(
                participants[identifier], "rollback", plan, root, current, candidate,
                journal_path, changed_paths(plan, identifier),
            )
            journal["rollbackCompleted"].append(identifier)
            journal["events"].append(evidence)
        except Exception as error:
            errors.append(f"{identifier}: {error}")
        atomic_json(journal_path, journal)
    return errors


def apply_command(args: Any) -> int:
    import project_manager

    manifest = Path(args.manifest).resolve()
    project = project_manager.validate_manifest(manifest, check_paths=True)
    root = manifest.parent
    plan_path = confined_path(root, args.plan, "transaction plan", must_exist=True)
    plan = load_json(plan_path, "configuration transaction plan")
    current_path = confined_path(root, args.current, "current configuration", must_exist=True)
    candidate_path = confined_path(root, args.candidate, "candidate configuration", must_exist=True)
    capabilities, participants, capability_path = load_capabilities(manifest)
    current = load_resolved(current_path, project["name"])
    candidate = load_resolved(candidate_path, project["name"])
    validate_plan(plan, manifest, capabilities, current, candidate)
    validate_plan_semantics(plan, create_plan(manifest, current_path, candidate_path))
    if plan.get("requiresRestart") and not args.allow_restart:
        raise ValueError("configuration transaction requires --allow-restart")
    ordered = [item["id"] for item in plan["participants"]]
    for identifier in ordered:
        if identifier not in participants:
            raise ValueError(f"transaction plan references unknown participant: {identifier}")
        if not participants[identifier]["command"]:
            raise ValueError(f"configuration participant has no transaction command: {identifier}")

    state = confined_path(root, args.state_dir, "configuration transaction state directory")
    transaction_id = plan["transactionId"]
    journal_path = state / f"{transaction_id}.journal.json"
    previous_path = state / f"{transaction_id}.previous-config.json"
    if journal_path.exists() or previous_path.exists():
        raise FileExistsError(f"configuration transaction state already exists: {transaction_id}")

    with transaction_lock(state, transaction_id):
        state.mkdir(parents=True, exist_ok=True)
        previous_path.write_bytes(current_path.read_bytes())
        journal: dict[str, Any] = {
            "schemaVersion": 1,
            "operation": "project-config-transaction",
            "transactionId": transaction_id,
            "project": project["name"],
            "status": "preflighting",
            "startedAt": now(),
            "manifest": relative(root, manifest),
            "manifestSha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
            "plan": relative(root, plan_path),
            "planSha256": digest(plan),
            "capabilities": relative(root, capability_path),
            "capabilitiesSha256": digest(capabilities),
            "currentConfig": relative(root, current_path),
            "candidateConfig": relative(root, candidate_path),
            "previousConfig": relative(root, previous_path),
            "previousConfigSha256": digest(current),
            "preflightCompleted": [],
            "commitAttempted": [],
            "commitCompleted": [],
            "rollbackCompleted": [],
            "events": [],
            "errors": [],
        }
        atomic_json(journal_path, journal)
        try:
            for identifier in ordered:
                evidence = invoke(
                    participants[identifier], "preflight", plan, root, current_path,
                    candidate_path, journal_path, changed_paths(plan, identifier),
                )
                journal["preflightCompleted"].append(identifier)
                journal["events"].append(evidence)
                atomic_json(journal_path, journal)
        except Exception as error:
            journal["status"] = "preflight-failed"
            journal["errors"].append(str(error))
            journal["finishedAt"] = now()
            atomic_json(journal_path, journal)
            raise

        journal["status"] = "committing"
        atomic_json(journal_path, journal)
        failure: Exception | None = None
        try:
            for identifier in ordered:
                journal["commitAttempted"].append(identifier)
                atomic_json(journal_path, journal)
                evidence = invoke(
                    participants[identifier], "commit", plan, root, current_path,
                    candidate_path, journal_path, changed_paths(plan, identifier),
                )
                journal["commitCompleted"].append(identifier)
                journal["events"].append(evidence)
                atomic_json(journal_path, journal)
            journal["status"] = "activating"
            atomic_json(journal_path, journal)
            validate_plan(
                plan, manifest, capabilities,
                load_resolved(current_path, project["name"]),
                load_resolved(candidate_path, project["name"]),
            )
            activate(candidate_path, current_path)
            journal["status"] = "committed"
            journal["activeConfigSha256"] = digest(candidate)
            journal["finishedAt"] = now()
            atomic_json(journal_path, journal)
        except Exception as error:
            failure = error

        if failure is not None:
            journal["errors"].append(str(failure))
            rollback_errors = rollback_attempted(
                journal, plan, participants, root, current_path, candidate_path, journal_path
            )
            if rollback_errors:
                journal["status"] = "rollback-failed"
                journal["errors"].extend(rollback_errors)
            else:
                activate(previous_path, current_path)
                journal["status"] = "rolled-back"
            journal["finishedAt"] = now()
            atomic_json(journal_path, journal)
            raise RuntimeError(
                f"configuration transaction failed with status {journal['status']}: {failure}"
            ) from failure

    print(
        f"PDR_PROJECT_CONFIG_APPLY_PASS transaction={transaction_id} "
        f"participants={len(ordered)} journal={journal_path}"
    )
    return 0


def recover_command(args: Any) -> int:
    import project_manager

    manifest = Path(args.manifest).resolve()
    project = project_manager.validate_manifest(manifest, check_paths=True)
    root = manifest.parent
    journal_path = confined_path(root, args.journal, "transaction journal", must_exist=True)
    journal = load_json(journal_path, "configuration transaction journal")
    if journal.get("project") != project["name"]:
        raise ValueError("configuration transaction journal belongs to another project")
    capabilities, participants, _ = load_capabilities(manifest)
    validate_journal(journal, participants)
    if journal.get("status") in TERMINAL_STATUSES:
        print(
            f"PDR_PROJECT_CONFIG_RECOVER_NOOP transaction={journal['transactionId']} "
            f"status={journal['status']}"
        )
        return 0
    if journal.get("status") == "rollback-failed" and not args.retry_rollback:
        raise ValueError("rollback-failed recovery requires --retry-rollback")

    plan_path = confined_path(root, journal["plan"], "journal plan", must_exist=True)
    current_path = confined_path(root, journal["currentConfig"], "journal current config",
                                   must_exist=True)
    candidate_path = confined_path(root, journal["candidateConfig"],
                                     "journal candidate config", must_exist=True)
    previous_path = confined_path(root, journal["previousConfig"],
                                    "journal previous config", must_exist=True)
    plan = load_json(plan_path, "configuration transaction plan")
    previous = load_resolved(previous_path, project["name"])
    candidate = load_resolved(candidate_path, project["name"])
    if digest(previous) != journal.get("previousConfigSha256"):
        raise ValueError("configuration transaction previous snapshot digest mismatch")
    bindings = (
        (hashlib.sha256(manifest.read_bytes()).hexdigest(), journal.get("manifestSha256"), "manifest"),
        (digest(plan), journal.get("planSha256"), "plan"),
        (digest(capabilities), journal.get("capabilitiesSha256"), "capabilities"),
    )
    for actual, expected, label in bindings:
        if actual != expected:
            raise ValueError(f"configuration transaction journal has stale {label}")
    validate_plan(plan, manifest, capabilities, previous, candidate)
    validate_plan_semantics(plan, create_plan(manifest, previous_path, candidate_path))

    transaction_id = journal["transactionId"]
    state = journal_path.parent
    with transaction_lock(state, transaction_id):
        errors = rollback_attempted(
            journal, plan, participants, root, current_path, candidate_path, journal_path
        )
        if errors:
            journal["status"] = "rollback-failed"
            journal["errors"].extend(errors)
            journal["finishedAt"] = now()
            atomic_json(journal_path, journal)
            raise RuntimeError("configuration transaction recovery rollback failed")
        activate(previous_path, current_path)
        journal["status"] = "rolled-back"
        journal["recoveredAt"] = now()
        journal["finishedAt"] = now()
        atomic_json(journal_path, journal)
    print(
        f"PDR_PROJECT_CONFIG_RECOVER_PASS transaction={transaction_id} journal={journal_path}"
    )
    return 0
