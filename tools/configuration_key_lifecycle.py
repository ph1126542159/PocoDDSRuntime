#!/usr/bin/env python3
"""Validate Bundle-owned configuration key lifecycles and project migrations."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any

import configuration_participant_contract as participant_contract


LIFECYCLE_NAME = "configuration-key-lifecycle.json"
MAXIMUM_DOCUMENT_BYTES = 64 * 1024
MAXIMUM_DOCUMENT_ENTRIES = 128
MAXIMUM_ENTRIES = 1024
MAXIMUM_BASELINE_BYTES = 1024 * 1024
BASELINE_PRODUCT = "PocoDDSRuntimeConfigurationKeyLifecycleBaseline"
ENTRY_ID = re.compile(r"^PDR-CFG-[0-9]{4,}$")
VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")


class ContractError(ValueError):
    def __init__(self, code: str, detail: str, path: Path | None = None) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.path = path


def semver(value: str) -> tuple[int, int, int]:
    if not isinstance(value, str) or VERSION.fullmatch(value) is None:
        raise ValueError("version must use MAJOR.MINOR.PATCH")
    return tuple(int(part) for part in value.split("."))  # type: ignore[return-value]


def discover(root: Path, filename: str) -> list[Path]:
    root = root.resolve()
    paths: set[Path] = set()
    direct = root / "bundle" / filename
    if direct.is_file():
        paths.add(direct.resolve())
    for name in participant_contract.DISCOVERY_ROOTS:
        search_root = root / name
        if not search_root.is_dir():
            continue
        for path in search_root.rglob(filename):
            relative_parts = path.relative_to(search_root).parts[:-1]
            if any(part in participant_contract.IGNORED_DIRECTORY_NAMES or
                   part.startswith("build") for part in relative_parts):
                continue
            if path.parent.name == "bundle":
                paths.add(path.resolve())
    return sorted(paths)


def discover_lifecycles(root: Path) -> list[Path]:
    return discover(root, LIFECYCLE_NAME)


def discover_participants(root: Path) -> list[Path]:
    return participant_contract.discover(root)


def read_json(path: Path, code: str) -> tuple[dict[str, Any], bytes]:
    path = path.resolve()
    try:
        data = path.read_bytes()
    except OSError as error:
        raise ContractError(code, "document cannot be read", path) from error
    if len(data) > MAXIMUM_DOCUMENT_BYTES:
        raise ContractError(code, "document exceeds 64 KiB", path)
    try:
        document = json.loads(data.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ContractError(code, "document is not valid UTF-8 JSON", path) from error
    if not isinstance(document, dict):
        raise ContractError(code, "document root must be an object", path)
    return document, data


def lifecycle_owner(path: Path) -> tuple[str, Path]:
    if path.name != LIFECYCLE_NAME or path.parent.name != "bundle":
        raise ContractError(
            "lifecycle-location-invalid",
            f"lifecycle must be named bundle/{LIFECYCLE_NAME}",
            path,
        )
    participant_path = path.with_name("configuration-participants.json")
    if not participant_path.is_file():
        raise ContractError(
            "participant-declaration-missing",
            "key lifecycle requires a sibling configuration-participants.json",
            path,
        )
    try:
        return participant_contract.bundle_owner(participant_path), participant_path.resolve()
    except participant_contract.ContractError as error:
        raise ContractError(error.code, error.detail, error.path) from error


def parse_lifecycle(path: Path, runtime_version: tuple[int, int, int]) \
        -> tuple[str, list[dict[str, Any]], str, Path]:
    path = path.resolve()
    owner, participant_path = lifecycle_owner(path)
    document, data = read_json(path, "lifecycle-invalid")
    if set(document) != {"schemaVersion", "entries"} or \
            document.get("schemaVersion") != 1 or \
            isinstance(document.get("schemaVersion"), bool) or \
            not isinstance(document.get("entries"), list) or \
            len(document["entries"]) > MAXIMUM_DOCUMENT_ENTRIES:
        raise ContractError("lifecycle-invalid", "lifecycle envelope is invalid", path)

    entries: list[dict[str, Any]] = []
    local_ids: set[str] = set()
    local_sources: set[str] = set()
    expected = {
        "id", "participantId", "operation", "sourceKey", "replacementKey",
        "deprecatedSince", "removalAllowedFrom",
    }
    for index, item in enumerate(document["entries"]):
        if not isinstance(item, dict) or set(item) != expected:
            raise ContractError(
                "lifecycle-invalid", f"entry {index} has unexpected fields", path
            )
        entry_id = item["id"]
        participant_id = item["participantId"]
        operation = item["operation"]
        source = item["sourceKey"]
        replacement = item["replacementKey"]
        if not isinstance(entry_id, str) or ENTRY_ID.fullmatch(entry_id) is None:
            raise ContractError("lifecycle-invalid", f"entry {index} id is invalid", path)
        if (not isinstance(participant_id, str) or
                participant_contract.ID.fullmatch(participant_id) is None):
            raise ContractError(
                "lifecycle-invalid", f"entry {entry_id} participantId is invalid", path
            )
        if operation not in {"rename", "remove"}:
            raise ContractError(
                "lifecycle-invalid", f"entry {entry_id} operation is invalid", path
            )
        if (not isinstance(source, str) or
                participant_contract.PREFIX.fullmatch(source) is None):
            raise ContractError(
                "lifecycle-invalid", f"entry {entry_id} sourceKey is invalid", path
            )
        if operation == "rename":
            if (not isinstance(replacement, str) or
                    participant_contract.PREFIX.fullmatch(replacement) is None or
                    replacement == source):
                raise ContractError(
                    "lifecycle-invalid",
                    f"entry {entry_id} rename replacementKey is invalid",
                    path,
                )
        elif replacement is not None:
            raise ContractError(
                "lifecycle-invalid",
                f"entry {entry_id} remove replacementKey must be null",
                path,
            )
        try:
            deprecated = semver(item["deprecatedSince"])
            removal = semver(item["removalAllowedFrom"])
        except ValueError as error:
            raise ContractError(
                "lifecycle-invalid", f"entry {entry_id}: {error}", path
            ) from error
        if deprecated > runtime_version:
            raise ContractError(
                "lifecycle-version-future",
                f"entry {entry_id} deprecatedSince is newer than the candidate Runtime",
                path,
            )
        if removal <= deprecated or removal[0] <= deprecated[0]:
            raise ContractError(
                "lifecycle-removal-window-invalid",
                f"entry {entry_id} must retain the key until a later major version",
                path,
            )
        if entry_id in local_ids or source in local_sources:
            raise ContractError(
                "lifecycle-duplicate", "lifecycle repeats an id or sourceKey", path
            )
        local_ids.add(entry_id)
        local_sources.add(source)
        entries.append({
            "owner": owner,
            "id": entry_id,
            "participantId": participant_id,
            "operation": operation,
            "sourceKey": source,
            "replacementKey": replacement,
            "deprecatedSince": item["deprecatedSince"],
            "removalAllowedFrom": item["removalAllowedFrom"],
        })
    return owner, entries, hashlib.sha256(data).hexdigest(), participant_path


def parse_migration(path: Path) -> tuple[list[dict[str, Any]], str]:
    path = path.resolve()
    document, data = read_json(path, "migration-invalid")
    if (set(document) != {"from", "to", "operations"} or
            not isinstance(document.get("from"), int) or
            isinstance(document.get("from"), bool) or
            not isinstance(document.get("to"), int) or
            isinstance(document.get("to"), bool) or
            document["to"] != document["from"] + 1 or
            not isinstance(document.get("operations"), list) or
            len(document["operations"]) > MAXIMUM_DOCUMENT_ENTRIES):
        raise ContractError("migration-invalid", "migration envelope is invalid", path)
    checked: list[dict[str, Any]] = []
    for index, operation in enumerate(document["operations"]):
        if not isinstance(operation, dict) or operation.get("op") not in {
                "rename", "remove", "set-default"}:
            raise ContractError(
                "migration-invalid", f"migration operation {index} is invalid", path
            )
        kind = operation["op"]
        expected = ({"op", "from", "path"} if kind == "rename" else
                    {"op", "path"} if kind == "remove" else
                    {"op", "path", "value"})
        if set(operation) != expected:
            raise ContractError(
                "migration-invalid",
                f"migration operation {index} has unexpected fields",
                path,
            )
        destination = operation.get("path")
        if (not isinstance(destination, str) or
                participant_contract.PREFIX.fullmatch(destination) is None):
            raise ContractError(
                "migration-invalid", f"migration operation {index} path is invalid", path
            )
        if kind == "set-default":
            continue
        source = operation.get("from") if kind == "rename" else destination
        if (not isinstance(source, str) or
                participant_contract.PREFIX.fullmatch(source) is None or
                (kind == "rename" and source == destination)):
            raise ContractError(
                "migration-invalid", f"migration operation {index} source is invalid", path
            )
        checked.append({
            "path": str(path),
            "op": kind,
            "sourceKey": source,
            "replacementKey": destination if kind == "rename" else None,
        })
    return checked, hashlib.sha256(data).hexdigest()


def replacement_cycle(entries: list[dict[str, Any]]) -> bool:
    graph = {
        item["sourceKey"]: item["replacementKey"]
        for item in entries if item["replacementKey"] is not None
    }
    for start in graph:
        seen: set[str] = set()
        node: str | None = start
        while node in graph:
            if node in seen:
                return True
            seen.add(node)
            node = graph[node]
    return False


def load_baseline(path: Path) -> tuple[dict[str, Any], str]:
    path = path.resolve()
    try:
        data = path.read_bytes()
    except OSError as error:
        raise ContractError("baseline-invalid", "baseline cannot be read", path) from error
    if len(data) > MAXIMUM_BASELINE_BYTES:
        raise ContractError("baseline-invalid", "baseline exceeds 1 MiB", path)
    try:
        document = json.loads(data.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ContractError(
            "baseline-invalid", "baseline is not valid UTF-8 JSON", path
        ) from error
    if (not isinstance(document, dict) or set(document) != {
            "schemaVersion", "product", "runtimeVersion", "entries"} or
            document.get("schemaVersion") != 1 or
            isinstance(document.get("schemaVersion"), bool) or
            document.get("product") != BASELINE_PRODUCT or
            not isinstance(document.get("runtimeVersion"), str) or
            VERSION.fullmatch(document["runtimeVersion"]) is None or
            not isinstance(document.get("entries"), list) or
            len(document["entries"]) > MAXIMUM_ENTRIES):
        raise ContractError("baseline-invalid", "baseline envelope is invalid", path)
    baseline_version = semver(document["runtimeVersion"])
    expected = {
        "owner", "id", "participantId", "operation", "sourceKey",
        "replacementKey", "deprecatedSince", "removalAllowedFrom",
    }
    ids: set[str] = set()
    sources: set[str] = set()
    entries: list[dict[str, Any]] = []
    for index, item in enumerate(document["entries"]):
        if not isinstance(item, dict) or set(item) != expected:
            raise ContractError(
                "baseline-invalid", f"baseline entry {index} has unexpected fields", path
            )
        owner = item["owner"]
        entry_id = item["id"]
        participant_id = item["participantId"]
        operation = item["operation"]
        source = item["sourceKey"]
        replacement = item["replacementKey"]
        if (not isinstance(owner, str) or
                participant_contract.SERVICE.fullmatch(owner) is None or
                not isinstance(entry_id, str) or ENTRY_ID.fullmatch(entry_id) is None or
                not isinstance(participant_id, str) or
                participant_contract.ID.fullmatch(participant_id) is None or
                operation not in {"rename", "remove"} or
                not isinstance(source, str) or
                participant_contract.PREFIX.fullmatch(source) is None):
            raise ContractError(
                "baseline-invalid", f"baseline entry {index} identity is invalid", path
            )
        if operation == "rename":
            if (not isinstance(replacement, str) or
                    participant_contract.PREFIX.fullmatch(replacement) is None or
                    replacement == source):
                raise ContractError(
                    "baseline-invalid",
                    f"baseline entry {entry_id} replacement is invalid",
                    path,
                )
        elif replacement is not None:
            raise ContractError(
                "baseline-invalid",
                f"baseline entry {entry_id} remove replacement must be null",
                path,
            )
        try:
            deprecated = semver(item["deprecatedSince"])
            removal = semver(item["removalAllowedFrom"])
        except ValueError as error:
            raise ContractError(
                "baseline-invalid", f"baseline entry {entry_id}: {error}", path
            ) from error
        if (deprecated > baseline_version or removal <= deprecated or
                removal[0] <= deprecated[0]):
            raise ContractError(
                "baseline-invalid",
                f"baseline entry {entry_id} version window is invalid",
                path,
            )
        if entry_id in ids or source in sources:
            raise ContractError(
                "baseline-invalid", "baseline repeats an id or sourceKey", path
            )
        ids.add(entry_id)
        sources.add(source)
        entries.append(dict(item))
    if replacement_cycle(entries):
        raise ContractError(
            "baseline-invalid", "baseline replacement graph has a cycle", path
        )
    return {
        "schemaVersion": 1,
        "product": BASELINE_PRODUCT,
        "runtimeVersion": document["runtimeVersion"],
        "entries": sorted(entries, key=lambda item: item["id"]),
    }, hashlib.sha256(data).hexdigest()


def baseline_violations(entries: list[dict[str, Any]], baseline: dict[str, Any],
                        runtime_version: tuple[int, int, int]) \
        -> list[dict[str, str]]:
    current_by_id = {item["id"]: item for item in entries}
    violations: list[dict[str, str]] = []
    stable_fields = (
        "owner", "participantId", "operation", "sourceKey", "replacementKey",
        "deprecatedSince",
    )
    for published in baseline["entries"]:
        current = current_by_id.get(published["id"])
        if current is None:
            if runtime_version < semver(published["removalAllowedFrom"]):
                violations.append({
                    "code": "published-lifecycle-removed-early",
                    "path": "",
                    "sourceKey": published["sourceKey"],
                    "detail": (
                        f"published lifecycle {published['id']} must remain until "
                        f"{published['removalAllowedFrom']}"
                    ),
                })
            continue
        changed = next((field for field in stable_fields
                        if current[field] != published[field]), None)
        if changed is not None:
            violations.append({
                "code": "published-lifecycle-changed",
                "path": "",
                "sourceKey": published["sourceKey"],
                "detail": f"published lifecycle {published['id']} changed {changed}",
            })
        if semver(current["removalAllowedFrom"]) < \
                semver(published["removalAllowedFrom"]):
            violations.append({
                "code": "published-removal-window-shortened",
                "path": "",
                "sourceKey": published["sourceKey"],
                "detail": (
                    f"published lifecycle {published['id']} shortened its removal window"
                ),
            })
    return violations


def validate(lifecycle_paths: list[Path], participant_paths: list[Path],
             migration_paths: list[Path], runtime_version_text: str,
             baseline_path: Path | None = None) -> dict[str, Any]:
    try:
        runtime_version = semver(runtime_version_text)
    except ValueError as error:
        raise ContractError("runtime-version-invalid", str(error)) from error
    lifecycle_paths = sorted({path.resolve() for path in lifecycle_paths})
    participant_paths = sorted({path.resolve() for path in participant_paths})
    migration_paths = sorted({path.resolve() for path in migration_paths})
    if not lifecycle_paths:
        raise ContractError("lifecycle-missing", "no key lifecycle declarations were supplied")
    if not participant_paths:
        raise ContractError(
            "participant-declaration-missing", "no participant declarations were supplied"
        )
    try:
        participant_report = participant_contract.validate(participant_paths)
    except participant_contract.ContractError as error:
        raise ContractError(error.code, error.detail, error.path) from error
    participants = {item["id"]: item for item in participant_report["participants"]}
    inputs = [{
        "kind": "participant",
        "owner": item["owner"],
        "path": item["path"],
        "sha256": item["sha256"],
    } for item in participant_report["inputs"]]

    entries: list[dict[str, Any]] = []
    ids: set[str] = set()
    sources: set[str] = set()
    required_participant_paths: set[Path] = set()
    for path in lifecycle_paths:
        owner, parsed, digest, participant_path = parse_lifecycle(path, runtime_version)
        required_participant_paths.add(participant_path)
        inputs.append({
            "kind": "lifecycle", "owner": owner,
            "path": str(path), "sha256": digest,
        })
        for entry in parsed:
            if entry["id"] in ids or entry["sourceKey"] in sources:
                raise ContractError(
                    "lifecycle-duplicate",
                    "multiple Bundles repeat a lifecycle id or sourceKey",
                    path,
                )
            participant = participants.get(entry["participantId"])
            if participant is None:
                raise ContractError(
                    "lifecycle-participant-missing",
                    f"entry {entry['id']} references an unknown participant",
                    path,
                )
            if participant["owner"] != entry["owner"]:
                raise ContractError(
                    "lifecycle-owner-mismatch",
                    f"entry {entry['id']} references another Bundle's participant",
                    path,
                )
            for field in ("sourceKey", "replacementKey"):
                key = entry[field]
                if key is not None and not any(
                        participant_contract.owns(prefix, key)
                        for prefix in participant["ownedPrefixes"]):
                    raise ContractError(
                        "lifecycle-key-outside-owner",
                        f"entry {entry['id']} {field} is outside participant ownership",
                        path,
                    )
            ids.add(entry["id"])
            sources.add(entry["sourceKey"])
            entries.append(entry)
            if len(entries) > MAXIMUM_ENTRIES:
                raise ContractError(
                    "lifecycle-capacity-exceeded", "lifecycle entries exceed capacity", path
                )
    missing_participants = required_participant_paths - set(participant_paths)
    if missing_participants:
        raise ContractError(
            "participant-declaration-missing",
            "a lifecycle sibling participant declaration was not supplied",
            sorted(missing_participants)[0],
        )
    if replacement_cycle(entries):
        raise ContractError(
            "lifecycle-replacement-cycle", "configuration key replacement graph has a cycle"
        )

    migration_operations: list[dict[str, Any]] = []
    for path in migration_paths:
        operations, digest = parse_migration(path)
        inputs.append({
            "kind": "migration", "owner": "",
            "path": str(path), "sha256": digest,
        })
        migration_operations.extend(operations)
    lifecycle_by_source = {item["sourceKey"]: item for item in entries}
    violations: list[dict[str, str]] = []
    for operation in migration_operations:
        lifecycle = lifecycle_by_source.get(operation["sourceKey"])
        if lifecycle is None:
            violations.append({
                "code": "migration-lifecycle-missing",
                "path": operation["path"],
                "sourceKey": operation["sourceKey"],
                "detail": "rename/remove has no Bundle-owned lifecycle declaration",
            })
        elif (lifecycle["operation"] != operation["op"] or
              lifecycle["replacementKey"] != operation["replacementKey"]):
            violations.append({
                "code": "migration-lifecycle-mismatch",
                "path": operation["path"],
                "sourceKey": operation["sourceKey"],
                "detail": "migration operation does not match the published lifecycle",
            })
    baseline_evidence = None
    if baseline_path is not None:
        baseline, baseline_sha256 = load_baseline(baseline_path)
        if semver(baseline["runtimeVersion"]) > runtime_version:
            raise ContractError(
                "baseline-invalid", "baseline is newer than the candidate Runtime",
                baseline_path,
            )
        baseline_evidence = {
            "path": str(baseline_path.resolve()),
            "sha256": baseline_sha256,
            "runtimeVersion": baseline["runtimeVersion"],
            "entryCount": len(baseline["entries"]),
        }
        violations.extend(baseline_violations(entries, baseline, runtime_version))
    inputs = sorted(inputs, key=lambda item: (item["kind"], item["owner"], item["sha256"]))
    identity = [{
        "kind": item["kind"], "owner": item["owner"], "sha256": item["sha256"]
    } for item in inputs]
    input_set_sha256 = hashlib.sha256(json.dumps(
        identity, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()
    compatible = not violations
    return {
        "schemaVersion": 1,
        "operation": "configuration-key-lifecycle-contract",
        "passed": compatible,
        "compatible": compatible,
        "runtimeVersion": runtime_version_text,
        "participantDeclarationCount": len(participant_paths),
        "lifecycleDeclarationCount": len(lifecycle_paths),
        "entryCount": len(entries),
        "migrationDocumentCount": len(migration_paths),
        "inputSetSha256": input_set_sha256,
        "inputs": inputs,
        "entries": sorted(entries, key=lambda item: item["id"]),
        "migrationOperations": sorted(
            migration_operations,
            key=lambda item: (item["path"], item["sourceKey"]),
        ),
        "baseline": baseline_evidence,
        "violations": sorted(
            violations, key=lambda item: (item["path"], item["sourceKey"], item["code"])
        ),
        "errors": [],
    }


def atomic_json(path: Path, document: dict[str, Any]) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(document, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8", newline="\n",
    )
    temporary.replace(path)


def execute(lifecycle_paths: list[Path], participant_paths: list[Path],
            migration_paths: list[Path], runtime_version: str,
            report_path: Path | None = None,
            baseline_path: Path | None = None) -> int:
    try:
        report = validate(
            lifecycle_paths, participant_paths, migration_paths, runtime_version,
            baseline_path,
        )
    except ContractError as error:
        report = {
            "schemaVersion": 1,
            "operation": "configuration-key-lifecycle-contract",
            "passed": False,
            "compatible": False,
            "runtimeVersion": (
                runtime_version if VERSION.fullmatch(runtime_version) else None
            ),
            "participantDeclarationCount": len({p.resolve() for p in participant_paths}),
            "lifecycleDeclarationCount": len({p.resolve() for p in lifecycle_paths}),
            "entryCount": 0,
            "migrationDocumentCount": len({p.resolve() for p in migration_paths}),
            "inputSetSha256": None,
            "inputs": [],
            "entries": [],
            "migrationOperations": [],
            "baseline": None,
            "violations": [],
            "errors": [{
                "code": error.code,
                "path": str(error.path.resolve()) if error.path else "",
                "detail": error.detail,
            }],
        }
        if report_path:
            atomic_json(report_path, report)
        print(
            f"PDR_CONFIGURATION_KEY_LIFECYCLE_FAIL code={error.code} "
            f"path={error.path or '-'}",
            file=sys.stderr,
        )
        return 2
    if report_path:
        atomic_json(report_path, report)
    if not report["compatible"]:
        print(
            "PDR_CONFIGURATION_KEY_LIFECYCLE_INCOMPATIBLE "
            f"violations={len(report['violations'])}",
            file=sys.stderr,
        )
        return 1
    print(
        "PDR_CONFIGURATION_KEY_LIFECYCLE_PASS "
        f"declarations={report['lifecycleDeclarationCount']} "
        f"entries={report['entryCount']} migrations={report['migrationDocumentCount']}"
    )
    return 0


def validate_command(args: argparse.Namespace) -> int:
    return execute(
        [Path(args.declaration)] + [Path(path) for path in args.provider_declaration],
        [Path(path) for path in args.participant_declaration],
        [Path(path) for path in args.migration],
        args.runtime_version,
        Path(args.report) if args.report else None,
        Path(args.baseline) if getattr(args, "baseline", None) else None,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate Bundle-owned key lifecycles and project migrations."
    )
    parser.add_argument("--root", type=Path)
    parser.add_argument("--declaration", type=Path, action="append", default=[])
    parser.add_argument(
        "--participant-declaration", type=Path, action="append", default=[]
    )
    parser.add_argument("--migration", type=Path, action="append", default=[])
    parser.add_argument("--runtime-version", required=True)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    lifecycles = list(args.declaration)
    participants = list(args.participant_declaration)
    if args.root:
        lifecycles.extend(discover_lifecycles(args.root))
        participants.extend(discover_participants(args.root))
    return execute(
        lifecycles, participants, args.migration, args.runtime_version, args.report,
        args.baseline,
    )


if __name__ == "__main__":
    raise SystemExit(main())
