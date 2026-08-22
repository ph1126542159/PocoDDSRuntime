#!/usr/bin/env python3
"""Version, inspect and transactionally upgrade product project templates."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


TEMPLATE_ID = "pdr-product"
CURRENT_TEMPLATE_VERSION = 4
SUPPORTED_TEMPLATE_VERSIONS = {1, 2, 3, 4}
STATE_PATH = Path(".pdr/template-state.json")
BACKUP_DIRECTORY = Path(".pdr/template-backups")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sha256_text(content: str) -> str:
    return sha256_bytes(content.encode("utf-8"))


def canonical_json(document: Any) -> bytes:
    return json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def pretty_json(document: Any) -> bytes:
    return (json.dumps(document, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def template_context(project: dict[str, Any]) -> dict[str, Any]:
    return {
        "displayName": project["displayName"],
        "profile": project["runtime"]["profile"],
        "runtimeVersion": project["runtime"]["version"],
        "host": project["runtime"]["host"],
        "transports": project["runtime"]["transports"],
    }


def render_template(project: dict[str, Any], version: int) -> dict[str, str]:
    if version not in SUPPORTED_TEMPLATE_VERSIONS:
        raise ValueError(f"unsupported project template version: {version}")
    name = project["displayName"]
    profile = project["runtime"]["profile"]
    runtime_version = project["runtime"]["version"]
    robotics_default = "ON" if profile == "robotics" else "OFF"
    management_default = (
        "ON" if profile in {"embedded", "edge-industrial", "edge-test", "server"}
        else "OFF"
    )
    template_marker = (
        "" if version == 1 else f"set(PDR_PROJECT_TEMPLATE_VERSION {version})\n"
    )
    runtime_core = "" if version < 4 else f'''find_package(PDRRuntimeCore {runtime_version.replace("x", "0")} CONFIG REQUIRED)
set(PDR_PROJECT_HOST_MODEL "{project["runtime"]["host"]}")
set(PDR_PROJECT_TRANSPORTS {' '.join(project["runtime"]["transports"])})
'''
    cmake = f'''cmake_minimum_required(VERSION 3.24)
project({name} LANGUAGES CXX)
{template_marker}
include(CTest)
option(PDR_PROJECT_BUILD_ROBOTICS "Build robotics control-plane components" {robotics_default})
option(PDR_PROJECT_BUILD_APPLICATION "Build transport-neutral modules and services" ON)
option(PDR_PROJECT_BUILD_MANAGEMENT "Build application and management-plane components" {management_default})

{runtime_core}if(PDR_PROJECT_BUILD_ROBOTICS)
    find_package(PDRRoboticsRuntime {runtime_version.replace("x", "0")} CONFIG REQUIRED)
endif()
if(PDR_PROJECT_BUILD_MANAGEMENT)
    find_package(PocoDDSRuntime 0.1 CONFIG REQUIRED COMPONENTS SDK Plugins)
endif()

include("${{CMAKE_CURRENT_SOURCE_DIR}}/pdr-project.components.cmake")
'''
    build_configuration = ', "configuration": "Release"' if version >= 4 else ""
    test_configuration = '\n    "configuration": "Release",' if version >= 4 else ""
    presets = f'''{{
  "version": 5,
  "configurePresets": [{{
    "name": "default",
    "binaryDir": "${{sourceDir}}/build",
    "cacheVariables": {{
      "CMAKE_BUILD_TYPE": "Release",
      "CMAKE_PREFIX_PATH": "$env{{PDR_SDK_PREFIX}}",
      "CMAKE_INSTALL_PREFIX": "${{sourceDir}}/build/install",
      "BUILD_TESTING": "ON"
    }}
  }}],
  "buildPresets": [{{"name": "default", "configurePreset": "default", "jobs": 2{build_configuration}}}],
  "testPresets": [{{"name": "default", "configurePreset": "default",{test_configuration}
    "output": {{"outputOnFailure": true}}}}]
}}
'''
    cli = "python tools/pdr.py" if version == 1 else "python $Pdr"
    cli_prelude = "" if version == 1 else '$Pdr = "$env:PDR_SDK_PREFIX/bin/pdr.py"\n'
    template_commands = "" if version == 1 else f'''
{cli} project template status pdr-project.yaml --check
{cli} project template upgrade pdr-project.yaml --report build/template-upgrade.json
'''
    readme = f'''# {name}

Generated PocoDDSRuntime product project. The framework is consumed through installed
CMake packages; product code must not modify Runtime core.

```powershell
$env:PDR_SDK_PREFIX = "C:/PocoDDSRuntime/build/install"
{cli_prelude}{cli} project validate pdr-project.yaml
{cli} project config resolve pdr-project.yaml --output build/resolved-config.json
{template_commands}cmake --preset default
cmake --build --preset default
ctest --preset default -C Release
cmake --install build --config Release
```

`pdr new` auto-registers components when run inside this project. The generated CMake
composition is manifest-hash-bound and never scans directories. Core robotics components
build by default for the robotics profile. Configure with
`-DPDR_PROJECT_BUILD_MANAGEMENT=ON` only when the product needs application services or
OSP Bundles; keep them outside the robot control core.

`config/capabilities.json` is empty by default. Register a JSON Pointer owner only after
that component implements the `pdr-config-transaction/1` preflight/commit/rollback
protocol; unowned and immutable changes fail closed during `project config plan`.
'''
    if version >= 3:
        readme += '''
Components created by `pdr new` carry `.pdr-component.json`. `project validate` rejects
outdated or drifted framework-owned component build metadata while leaving business source
files product-owned. Resolve component conflicts with `pdr component upgrade <path>`.
'''
    if version >= 4:
        readme += f'''
Framework model: `{profile}`; Host: `{project["runtime"]["host"]}`; Transports:
`{", ".join(project["runtime"]["transports"])}`. Business modules depend on
`PocoDDS::RuntimeCore`; only project adapter components may include DDS, ROS 2, MQTT,
HTTP or device SDK headers. See the installed framework-model selection guide before
adding a transport.
'''
    gitignore = "build/\ninstall/\n*.user\n"
    if version >= 2:
        gitignore += ".pdr/template-backups/\n.pdr/template-conflicts/\n"
    if version >= 3:
        gitignore += "**/.pdr/template-backups/\n"
    return {
        "CMakeLists.txt": cmake,
        "CMakePresets.json": presets,
        "README.md": readme,
        ".gitignore": gitignore,
    }


def safe_relative(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty relative path")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{field} contains an unsafe path: {value}")
    return path.as_posix()


def confined(root: Path, value: str | Path, field: str,
             must_exist: bool = False) -> Path:
    supplied = Path(value)
    candidate = supplied.resolve() if supplied.is_absolute() else (root / supplied).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise ValueError(f"{field} must stay inside the project root") from error
    if must_exist and not candidate.is_file():
        raise FileNotFoundError(f"{field} not found: {candidate}")
    return candidate


def atomic_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    try:
        temporary.write_bytes(content)
        temporary.replace(path)
    except Exception:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def atomic_json(path: Path, document: dict[str, Any]) -> None:
    atomic_bytes(path, pretty_json(document))


def file_sha256(path: Path) -> str | None:
    return sha256_bytes(path.read_bytes()) if path.is_file() else None


def build_state(project: dict[str, Any], version: int, managed: dict[str, str],
                unmanaged: dict[str, str] | None = None) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "template": TEMPLATE_ID,
        "appliedVersion": version,
        "project": project["name"],
        "context": template_context(project),
        "managedFiles": [
            {"path": path, "baselineSha256": sha256_text(content)}
            for path, content in sorted(managed.items())
        ],
        "unmanagedFiles": [
            {"path": path, "reason": reason}
            for path, reason in sorted((unmanaged or {}).items())
        ],
    }


def validate_state(document: dict[str, Any], project: dict[str, Any]) -> dict[str, Any]:
    required = {
        "schemaVersion", "template", "appliedVersion", "project", "context",
        "managedFiles", "unmanagedFiles",
    }
    if set(document) != required:
        raise ValueError("project template state has an unexpected envelope")
    if document["schemaVersion"] != 1 or document["template"] != TEMPLATE_ID:
        raise ValueError("unsupported project template state contract")
    version = document["appliedVersion"]
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise ValueError("project template appliedVersion must be a positive integer")
    if document["project"] != project["name"]:
        raise ValueError("project template state belongs to another project")
    context = document["context"]
    context_required = {"displayName", "profile", "runtimeVersion"}
    context_allowed = context_required | {"host", "transports"}
    if (not isinstance(context, dict) or not context_required.issubset(context)
            or set(context) - context_allowed
            or any(not isinstance(context[key], str) or not context[key]
                   for key in context_required)
            or ("host" in context and
                (not isinstance(context["host"], str) or not context["host"]))
            or ("transports" in context and
                (not isinstance(context["transports"], list) or
                 not context["transports"] or
                 any(not isinstance(item, str) or not item
                     for item in context["transports"])))):
        raise ValueError("project template state has an invalid context")

    managed: list[dict[str, str]] = []
    unmanaged: list[dict[str, str]] = []
    seen: set[str] = set()
    for field, source, destination in (
            ("managedFiles", document["managedFiles"], managed),
            ("unmanagedFiles", document["unmanagedFiles"], unmanaged)):
        if not isinstance(source, list):
            raise ValueError(f"project template state {field} must be an array")
        for index, item in enumerate(source):
            if not isinstance(item, dict):
                raise ValueError(f"project template state {field}[{index}] must be an object")
            expected = {"path", "baselineSha256"} if field == "managedFiles" else {
                "path", "reason"}
            if set(item) != expected:
                raise ValueError(f"project template state {field}[{index}] has invalid fields")
            path = safe_relative(item["path"], f"{field}[{index}].path")
            if path in seen:
                raise ValueError(f"duplicate project template state path: {path}")
            seen.add(path)
            if field == "managedFiles":
                value = item["baselineSha256"]
                if not isinstance(value, str) or not SHA256.fullmatch(value):
                    raise ValueError(f"project template state has invalid digest for {path}")
                destination.append({"path": path, "baselineSha256": value})
            else:
                reason = item["reason"]
                if not isinstance(reason, str) or not reason:
                    raise ValueError(f"project template state has invalid reason for {path}")
                destination.append({"path": path, "reason": reason})
    return {
        "schemaVersion": 1,
        "template": TEMPLATE_ID,
        "appliedVersion": version,
        "project": project["name"],
        "context": dict(context),
        "managedFiles": sorted(managed, key=lambda item: item["path"]),
        "unmanagedFiles": sorted(unmanaged, key=lambda item: item["path"]),
    }


def load_state(root: Path, project: dict[str, Any]) -> dict[str, Any]:
    path = root / STATE_PATH
    if not path.is_file():
        raise FileNotFoundError(
            f"project template state not found: {path}; run project template adopt"
        )
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read project template state: {path}") from error
    if not isinstance(document, dict):
        raise ValueError("project template state root must be an object")
    return validate_state(document, project)


def initial_state(project: dict[str, Any], version: int | None = None) -> dict[str, Any]:
    selected = CURRENT_TEMPLATE_VERSION if version is None else version
    return build_state(project, selected, render_template(project, selected))


def status_document(manifest: Path) -> dict[str, Any]:
    import project_manager

    manifest = manifest.resolve()
    project = project_manager.validate_manifest(manifest, check_paths=True)
    template = project.get("template")
    if not template:
        raise ValueError("project manifest has no template metadata; run project template adopt")
    if template["id"] != TEMPLATE_ID:
        raise ValueError(f"unsupported project template: {template['id']}")
    state = load_state(manifest.parent, project)
    if state["appliedVersion"] != template["version"]:
        raise ValueError("project template manifest and state versions do not match")
    if state["appliedVersion"] > CURRENT_TEMPLATE_VERSION:
        raise ValueError("project template was created by a newer pdr CLI")
    desired = render_template(project, CURRENT_TEMPLATE_VERSION)
    managed = {item["path"]: item["baselineSha256"] for item in state["managedFiles"]}
    unmanaged_paths = {item["path"] for item in state["unmanagedFiles"]}
    files: list[dict[str, Any]] = []
    drifted = False
    for path, baseline in sorted(managed.items()):
        current = file_sha256(manifest.parent / path)
        condition = "clean" if current == baseline else ("missing" if current is None else "modified")
        drifted = drifted or condition != "clean"
        files.append({
            "path": path,
            "condition": condition,
            "baselineSha256": baseline,
            "currentSha256": current,
            "targetSha256": sha256_text(desired[path]) if path in desired else None,
        })
    for path in sorted(set(desired) - set(managed) - unmanaged_paths):
        current = file_sha256(manifest.parent / path)
        files.append({
            "path": path,
            "condition": "untracked",
            "baselineSha256": None,
            "currentSha256": current,
            "targetSha256": sha256_text(desired[path]),
        })
        drifted = True
    context_changed = state["context"] != template_context(project)
    update_available = state["appliedVersion"] < CURRENT_TEMPLATE_VERSION or context_changed
    return {
        "schemaVersion": 1,
        "operation": "project-template-status",
        "project": project["name"],
        "template": TEMPLATE_ID,
        "appliedVersion": state["appliedVersion"],
        "currentVersion": CURRENT_TEMPLATE_VERSION,
        "updateAvailable": update_available,
        "contextChanged": context_changed,
        "drifted": drifted,
        "healthy": not update_available and not drifted,
        "managedFiles": files,
        "unmanagedFiles": state["unmanagedFiles"],
    }


def write_report(root: Path, value: str | Path | None, document: dict[str, Any]) -> None:
    if value is not None:
        atomic_json(confined(root, value, "template report"), document)


def status_command(args: Any) -> int:
    manifest = Path(args.manifest).resolve()
    report = status_document(manifest)
    write_report(manifest.parent, args.report, report)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(
            f"PDR_PROJECT_TEMPLATE_STATUS version={report['appliedVersion']} "
            f"current={report['currentVersion']} update={str(report['updateAvailable']).lower()} "
            f"drift={str(report['drifted']).lower()}"
        )
    return 2 if args.check and not report["healthy"] else 0


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
def template_lock(root: Path, transaction_id: str) -> Iterator[None]:
    state_root = root / ".pdr"
    state_root.mkdir(parents=True, exist_ok=True)
    lock = state_root / "template-upgrade.lock"
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
                raise RuntimeError(f"project template lock is invalid: {lock}") from error
            if process_alive(owner_pid):
                raise RuntimeError(f"project template operation is running with pid {owner_pid}")
            lock.unlink()
    try:
        yield
    finally:
        try:
            owner = json.loads(lock.read_text(encoding="utf-8"))
            if owner.get("pid") == os.getpid() and owner.get("transactionId") == transaction_id:
                lock.unlink()
        except (OSError, json.JSONDecodeError, AttributeError):
            pass


def restore_entries(root: Path, journal: dict[str, Any], backup_root: Path) -> None:
    attempted = set(journal["attempted"])
    for entry in reversed(journal["entries"]):
        if entry["path"] not in attempted:
            continue
        destination = confined(root, entry["path"], "template recovery entry")
        if entry["existed"]:
            backup = confined(root, entry["backup"], "template backup", must_exist=True)
            try:
                backup.relative_to((backup_root / "files").resolve())
            except ValueError as error:
                raise ValueError(
                    f"project template backup escapes transaction directory: {entry['path']}"
                ) from error
            content = backup.read_bytes()
            if sha256_bytes(content) != entry["sha256"]:
                raise ValueError(f"project template backup digest mismatch: {entry['path']}")
            atomic_bytes(destination, content)
        elif destination.exists():
            if not destination.is_file():
                raise ValueError(f"template recovery target is not a file: {destination}")
            destination.unlink()


def transactional_write(root: Path, operation: str, changes: dict[str, bytes | None],
                        preconditions: dict[str, str | None]) -> Path:
    transaction_id = str(uuid.uuid4())
    backup_root = root / BACKUP_DIRECTORY / transaction_id
    journal_path = backup_root / "journal.json"
    with template_lock(root, transaction_id):
        for relative_path, expected in preconditions.items():
            actual = file_sha256(confined(root, relative_path, "template precondition"))
            if actual != expected:
                raise RuntimeError(
                    f"project template input changed before apply: {relative_path}"
                )
        backup_root.mkdir(parents=True, exist_ok=False)
        entries: list[dict[str, Any]] = []
        for relative_path in sorted(changes):
            path = confined(root, relative_path, "template transaction path")
            existed = path.is_file()
            entry: dict[str, Any] = {"path": relative_path, "existed": existed}
            if existed:
                content = path.read_bytes()
                backup = backup_root / "files" / relative_path
                backup.parent.mkdir(parents=True, exist_ok=True)
                backup.write_bytes(content)
                entry.update({
                    "sha256": sha256_bytes(content),
                    "backup": backup.relative_to(root).as_posix(),
                })
            entries.append(entry)
        journal: dict[str, Any] = {
            "schemaVersion": 1,
            "operation": operation,
            "transactionId": transaction_id,
            "status": "applying",
            "startedAt": now(),
            "entries": entries,
            "attempted": [],
        }
        atomic_json(journal_path, journal)
        try:
            for relative_path, content in changes.items():
                journal["attempted"].append(relative_path)
                atomic_json(journal_path, journal)
                path = confined(root, relative_path, "template transaction path")
                if content is None:
                    if path.exists():
                        if not path.is_file():
                            raise ValueError(f"template removal target is not a file: {path}")
                        path.unlink()
                else:
                    atomic_bytes(path, content)
            journal["status"] = "completed"
            journal["finishedAt"] = now()
            atomic_json(journal_path, journal)
        except Exception as error:
            journal["error"] = str(error)
            try:
                restore_entries(root, journal, backup_root)
                journal["status"] = "rolled-back"
            except Exception as rollback_error:
                journal["status"] = "rollback-failed"
                journal["rollbackError"] = str(rollback_error)
            journal["finishedAt"] = now()
            atomic_json(journal_path, journal)
            raise RuntimeError(
                f"project template transaction failed with status {journal['status']}"
            ) from error
    return journal_path


def manifest_and_composition_changes(manifest: Path, project: dict[str, Any],
                                     state: dict[str, Any],
                                     file_changes: dict[str, bytes | None]) -> dict[str, bytes | None]:
    import project_manager

    manifest_content = pretty_json(project)
    composition = "\n".join(project_manager.composition_lines(
        project, sha256_bytes(manifest_content)
    )) + "\n"
    result = dict(file_changes)
    result[manifest.name] = manifest_content
    result[project_manager.COMPOSITION_FILE] = composition.encode("utf-8")
    result[STATE_PATH.as_posix()] = pretty_json(state)
    return result


def adopt_command(args: Any) -> int:
    import project_manager

    manifest = Path(args.manifest).resolve()
    manifest_before = file_sha256(manifest)
    project = project_manager.validate_manifest(manifest, check_paths=True)
    if file_sha256(manifest) != manifest_before:
        raise RuntimeError("project manifest changed during template adoption planning")
    root = manifest.parent
    if project.get("template") or (root / STATE_PATH).exists():
        raise ValueError("project already has template metadata or state")
    version = args.version
    if version not in SUPPORTED_TEMPLATE_VERSIONS:
        raise ValueError(f"unsupported project template version: {version}")
    rendered = render_template(project, version)
    managed: dict[str, str] = {}
    unmanaged: dict[str, str] = {}
    for path, content in rendered.items():
        current = file_sha256(root / path)
        if current == sha256_text(content):
            managed[path] = content
        else:
            unmanaged[path] = "missing" if current is None else "pre-existing-customization"
    project["template"] = {"id": TEMPLATE_ID, "version": version}
    state = build_state(project, version, managed, unmanaged)
    changes = manifest_and_composition_changes(manifest, project, state, {})
    preconditions = {
        manifest.name: manifest_before,
        "pdr-project.components.cmake": file_sha256(root / "pdr-project.components.cmake"),
        STATE_PATH.as_posix(): None,
    }
    journal = transactional_write(
        root, "project-template-adopt", changes, preconditions
    )
    report = {
        "schemaVersion": 1,
        "operation": "project-template-adopt",
        "project": project["name"],
        "version": version,
        "managedFiles": sorted(managed),
        "unmanagedFiles": state["unmanagedFiles"],
        "journal": journal.relative_to(root).as_posix(),
    }
    write_report(root, args.report, report)
    print(
        f"PDR_PROJECT_TEMPLATE_ADOPT_PASS version={version} managed={len(managed)} "
        f"unmanaged={len(unmanaged)} journal={journal}"
    )
    return 0


def conflict_plan(root: Path, desired: dict[str, str], state: dict[str, Any]) -> tuple[
        dict[str, str], list[dict[str, Any]], dict[str, str | None]]:
    managed = {item["path"]: item["baselineSha256"] for item in state["managedFiles"]}
    known = set(managed) | {item["path"] for item in state["unmanagedFiles"]} | set(desired)
    actions: dict[str, str] = {}
    conflicts: list[dict[str, Any]] = []
    observed: dict[str, str | None] = {}
    for path in sorted(known):
        current = file_sha256(root / path)
        observed[path] = current
        target = sha256_text(desired[path]) if path in desired else None
        baseline = managed.get(path)
        if current == target:
            actions[path] = "manage"
        elif path in managed and current == baseline:
            actions[path] = "remove" if target is None else "update"
        elif current is None and target is not None:
            actions[path] = "create"
        elif current is None and target is None:
            actions[path] = "forget"
        else:
            actions[path] = "conflict"
            conflicts.append({
                "path": path,
                "baselineSha256": baseline,
                "currentSha256": current,
                "targetSha256": target,
            })
    return actions, conflicts, observed


def normalize_selections(values: list[str], field: str) -> set[str]:
    result = {safe_relative(value, field) for value in values}
    if len(result) != len(values):
        raise ValueError(f"{field} contains duplicate paths")
    return result


def upgrade_command(args: Any) -> int:
    import project_manager

    manifest = Path(args.manifest).resolve()
    manifest_before = file_sha256(manifest)
    project = project_manager.validate_manifest(manifest, check_paths=True)
    if file_sha256(manifest) != manifest_before:
        raise RuntimeError("project manifest changed during template upgrade planning")
    root = manifest.parent
    template = project.get("template")
    if not template:
        raise ValueError("project has no template metadata; run project template adopt")
    if template["id"] != TEMPLATE_ID:
        raise ValueError(f"unsupported project template: {template['id']}")
    state_before = file_sha256(root / STATE_PATH)
    state = load_state(root, project)
    if file_sha256(root / STATE_PATH) != state_before:
        raise RuntimeError("project template state changed during upgrade planning")
    if state["appliedVersion"] != template["version"]:
        raise ValueError("project template manifest and state versions do not match")
    target = CURRENT_TEMPLATE_VERSION if args.target_version is None else args.target_version
    if target not in SUPPORTED_TEMPLATE_VERSIONS:
        raise ValueError(f"unsupported project template target version: {target}")
    if target < state["appliedVersion"]:
        raise ValueError("project template downgrade is not supported")
    desired = render_template(project, target)
    actions, conflicts, observed = conflict_plan(root, desired, state)
    accept = normalize_selections(args.accept_template, "--accept-template")
    keep = normalize_selections(args.keep_project, "--keep-project")
    if accept & keep:
        raise ValueError("a template path cannot be both accepted and kept")
    conflict_paths = {item["path"] for item in conflicts}
    unknown = (accept | keep) - conflict_paths
    if unknown:
        raise ValueError("conflict selection is not an active conflict: " + ", ".join(sorted(unknown)))
    unresolved = conflict_paths - accept - keep
    report: dict[str, Any] = {
        "schemaVersion": 1,
        "operation": "project-template-upgrade",
        "project": project["name"],
        "fromVersion": state["appliedVersion"],
        "toVersion": target,
        "actions": [{"path": path, "action": action} for path, action in sorted(actions.items())],
        "conflicts": conflicts,
        "unresolvedConflicts": sorted(unresolved),
        "applied": False,
    }
    if unresolved:
        write_report(root, args.report, report)
        print(
            f"PDR_PROJECT_TEMPLATE_UPGRADE_CONFLICT conflicts={len(unresolved)} "
            f"report={args.report or '-'}"
        )
        return 2

    file_changes: dict[str, bytes | None] = {}
    managed_content: dict[str, str] = {}
    unmanaged = {item["path"]: item["reason"] for item in state["unmanagedFiles"]}
    for path, action in sorted(actions.items()):
        if path in keep:
            unmanaged[path] = "kept-project-customization"
            continue
        unmanaged.pop(path, None)
        if path in desired:
            managed_content[path] = desired[path]
            if action != "manage" or path in accept:
                file_changes[path] = desired[path].encode("utf-8")
        elif action == "remove" or path in accept:
            file_changes[path] = None
    project["template"] = {"id": TEMPLATE_ID, "version": target}
    new_state = build_state(project, target, managed_content, unmanaged)
    changes = manifest_and_composition_changes(manifest, project, new_state, file_changes)
    preconditions = dict(observed)
    preconditions.update({
        manifest.name: manifest_before,
        "pdr-project.components.cmake": file_sha256(root / "pdr-project.components.cmake"),
        STATE_PATH.as_posix(): state_before,
    })
    journal = transactional_write(
        root, "project-template-upgrade", changes, preconditions
    )
    report.update({
        "applied": True,
        "journal": journal.relative_to(root).as_posix(),
        "managedFiles": [item["path"] for item in new_state["managedFiles"]],
        "unmanagedFiles": new_state["unmanagedFiles"],
    })
    write_report(root, args.report, report)
    print(
        f"PDR_PROJECT_TEMPLATE_UPGRADE_PASS from={state['appliedVersion']} to={target} "
        f"managed={len(new_state['managedFiles'])} unmanaged={len(new_state['unmanagedFiles'])} "
        f"journal={journal}"
    )
    return 0


def recover_transaction(root: Path, journal_path: Path, allowed_operations: set[str],
                        retry_rollback: bool) -> tuple[bool, str, str]:
    root = root.resolve()
    journal_path = confined(root, journal_path, "template recovery journal", must_exist=True)
    try:
        journal = json.loads(journal_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read template recovery journal: {journal_path}") from error
    if (not isinstance(journal, dict) or journal.get("schemaVersion") != 1
            or journal.get("operation") not in allowed_operations):
        raise ValueError("unsupported project template recovery journal")
    status = journal.get("status")
    if status not in {"applying", "completed", "rolled-back", "rollback-failed"}:
        raise ValueError("project template recovery journal status is invalid")
    entries = journal.get("entries")
    if not isinstance(entries, list):
        raise ValueError("project template recovery journal entries must be an array")
    transaction_id = journal.get("transactionId")
    try:
        uuid.UUID(transaction_id)
    except (ValueError, TypeError) as error:
        raise ValueError("project template recovery transactionId is invalid") from error
    expected_journal = (root / BACKUP_DIRECTORY / transaction_id / "journal.json").resolve()
    if journal_path != expected_journal:
        raise ValueError("project template recovery journal is outside its transaction directory")
    entry_paths: set[str] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict) or not isinstance(entry.get("existed"), bool):
            raise ValueError(f"project template recovery entry {index} is invalid")
        path = safe_relative(entry.get("path"), f"entries[{index}].path")
        if path in entry_paths:
            raise ValueError(f"duplicate project template recovery entry: {path}")
        entry_paths.add(path)
        if entry["existed"]:
            if (not isinstance(entry.get("sha256"), str)
                    or not SHA256.fullmatch(entry["sha256"])):
                raise ValueError(f"project template recovery entry digest is invalid: {path}")
            safe_relative(entry.get("backup"), f"entries[{index}].backup")
    attempted = journal.get("attempted")
    if (not isinstance(attempted, list) or len(attempted) != len(set(attempted))
            or any(path not in entry_paths for path in attempted)):
        raise ValueError("project template recovery attempted paths are invalid")
    if status in {"completed", "rolled-back"}:
        return False, transaction_id, status
    if status == "rollback-failed" and not retry_rollback:
        raise ValueError("rollback-failed template recovery requires --retry-rollback")
    backup_root = journal_path.parent
    with template_lock(root, transaction_id):
        try:
            restore_entries(root, journal, backup_root)
            journal["status"] = "rolled-back"
            journal["recoveredAt"] = now()
            journal["finishedAt"] = now()
            atomic_json(journal_path, journal)
        except Exception as error:
            journal["status"] = "rollback-failed"
            journal["rollbackError"] = str(error)
            journal["finishedAt"] = now()
            atomic_json(journal_path, journal)
            raise RuntimeError("project template recovery rollback failed") from error
    return True, transaction_id, "rolled-back"


def recover_command(args: Any) -> int:
    manifest = Path(args.manifest).resolve()
    root = manifest.parent
    journal_path = confined(root, args.journal, "template recovery journal", must_exist=True)
    changed, transaction_id, status = recover_transaction(
        root,
        journal_path,
        {"project-template-adopt", "project-template-upgrade"},
        args.retry_rollback,
    )
    if not changed:
        print(
            f"PDR_PROJECT_TEMPLATE_RECOVER_NOOP transaction={transaction_id} "
            f"status={status}"
        )
        return 0
    print(
        f"PDR_PROJECT_TEMPLATE_RECOVER_PASS transaction={transaction_id} journal={journal_path}"
    )
    return 0
