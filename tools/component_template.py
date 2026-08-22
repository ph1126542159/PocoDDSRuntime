#!/usr/bin/env python3
"""Version and transactionally upgrade generated component scaffolding."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from pathlib import Path
from typing import Any, Callable

import project_template


TEMPLATE_ID = "pdr-component"
CURRENT_TEMPLATE_VERSION = 3
SUPPORTED_TEMPLATE_VERSIONS = {1, 2, 3}
COMPONENT_KINDS = {
    "module", "service", "device", "workflow", "bundle", "plugin", "subprocess",
    "robot-module", "robot-hardware-adapter", "robot-simulation-adapter",
    "robot-process", "ros2-node",
}
COMPONENT_NAME = re.compile(r"[A-Z][A-Za-z0-9]*")
STATE_PATH = Path(".pdr-component.json")
BaseRenderer = Callable[[str, str], dict[str, str]]


def default_base_renderer(kind: str, name: str) -> dict[str, str]:
    """Load the sibling CLI's frozen v1 renderer without relying on PYTHONPATH."""
    path = Path(__file__).resolve().with_name("pdr.py")
    spec = importlib.util.spec_from_file_location("pdr_component_frozen_renderer", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load frozen component renderer: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.templates(kind, name)


def managed_path(path: str) -> bool:
    candidate = Path(path)
    return (
        candidate.name in {"CMakeLists.txt", "README.md", "package.xml"}
        or candidate.suffix == ".bndlspec"
    )


def render_component_template(kind: str, name: str, base_renderer: BaseRenderer,
                              version: int) -> dict[str, str]:
    if version not in SUPPORTED_TEMPLATE_VERSIONS:
        raise ValueError(f"unsupported component template version: {version}")
    rendered = dict(base_renderer(kind, name))
    if version == 1:
        return rendered
    for path, content in list(rendered.items()):
        if Path(path).name != "CMakeLists.txt":
            continue
        lines = content.splitlines(keepends=True)
        if not lines or not lines[0].startswith("cmake_minimum_required("):
            raise ValueError(f"component template CMake entry has no minimum version: {path}")
        lines.insert(1, f"set(PDR_COMPONENT_TEMPLATE_VERSION {version})\n")
        rendered[path] = "".join(lines)
    if version >= 3 and kind in {"module", "service"}:
        cmake = rendered["CMakeLists.txt"]
        legacy_package = "find_package(PocoDDSRuntime 0.1 CONFIG REQUIRED COMPONENTS SDK)"
        if legacy_package not in cmake or "PocoDDS::SDK" not in cmake:
            raise ValueError(f"{kind} scaffold no longer matches the version-3 migration")
        rendered["CMakeLists.txt"] = cmake.replace(
            legacy_package, "find_package(PDRRuntimeCore 0.1 CONFIG REQUIRED)"
        ).replace("PocoDDS::SDK", "PocoDDS::RuntimeCore")
    if "README.md" in rendered:
        rendered["README.md"] = rendered["README.md"].rstrip() + f'''

## Component template lifecycle

This component uses `{TEMPLATE_ID}` version {version}. Framework-owned build metadata can
be checked with `pdr component status . --check` and upgraded with
`pdr component upgrade .`. Files under `src/`, `include/`, `tests/`, `launch/` and
`config/` remain product-owned and are never overwritten by template upgrades.
'''
    if version >= 3 and kind in {"module", "service"}:
        rendered["README.md"] = rendered["README.md"].replace(
            "uses only the public `PocoDDS::SDK` target",
            "uses only the transport-neutral `PocoDDS::RuntimeCore` target",
        ).replace(
            "installed SDK in an isolated build",
            "installed RuntimeCore package in an isolated build",
        )
    return rendered


def split_files(rendered: dict[str, str]) -> tuple[dict[str, str], dict[str, str]]:
    managed = {path: content for path, content in rendered.items() if managed_path(path)}
    project_files = {path: content for path, content in rendered.items() if not managed_path(path)}
    return managed, project_files


def build_state(kind: str, name: str, version: int, managed: dict[str, str],
                project_files: dict[str, str],
                unmanaged: dict[str, str] | None = None) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "template": TEMPLATE_ID,
        "kind": kind,
        "name": name,
        "appliedVersion": version,
        "managedFiles": [
            {"path": path, "baselineSha256": project_template.sha256_text(content)}
            for path, content in sorted(managed.items())
        ],
        "projectFiles": [
            {"path": path, "templateSha256": project_template.sha256_text(content)}
            for path, content in sorted(project_files.items())
        ],
        "unmanagedFiles": [
            {"path": path, "reason": reason}
            for path, reason in sorted((unmanaged or {}).items())
        ],
    }


def _validate_records(document: dict[str, Any], field: str, digest_field: str,
                      seen: set[str]) -> list[dict[str, str]]:
    records = document.get(field)
    if not isinstance(records, list):
        raise ValueError(f"component template {field} must be an array")
    normalized: list[dict[str, str]] = []
    for index, item in enumerate(records):
        if not isinstance(item, dict) or set(item) != {"path", digest_field}:
            raise ValueError(f"component template {field}[{index}] has invalid fields")
        path = project_template.safe_relative(item["path"], f"{field}[{index}].path")
        if path == STATE_PATH.as_posix() or path in seen:
            raise ValueError(f"duplicate or reserved component template path: {path}")
        seen.add(path)
        value = item[digest_field]
        if not isinstance(value, str) or not project_template.SHA256.fullmatch(value):
            raise ValueError(f"component template {field}[{index}] has invalid digest")
        normalized.append({"path": path, digest_field: value})
    return sorted(normalized, key=lambda item: item["path"])


def validate_state(document: dict[str, Any]) -> dict[str, Any]:
    required = {
        "schemaVersion", "template", "kind", "name", "appliedVersion",
        "managedFiles", "projectFiles", "unmanagedFiles",
    }
    if set(document) != required:
        raise ValueError("component template state has an unexpected envelope")
    if document["schemaVersion"] != 1 or document["template"] != TEMPLATE_ID:
        raise ValueError("unsupported component template state contract")
    kind = document["kind"]
    name = document["name"]
    if kind not in COMPONENT_KINDS:
        raise ValueError(f"unsupported component template kind: {kind}")
    if not isinstance(name, str) or COMPONENT_NAME.fullmatch(name) is None:
        raise ValueError("component template name must be PascalCase ASCII")
    version = document["appliedVersion"]
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise ValueError("component template appliedVersion must be a positive integer")
    seen: set[str] = set()
    managed = _validate_records(document, "managedFiles", "baselineSha256", seen)
    project_files = _validate_records(document, "projectFiles", "templateSha256", seen)
    unmanaged_source = document["unmanagedFiles"]
    if not isinstance(unmanaged_source, list):
        raise ValueError("component template unmanagedFiles must be an array")
    unmanaged: list[dict[str, str]] = []
    for index, item in enumerate(unmanaged_source):
        if not isinstance(item, dict) or set(item) != {"path", "reason"}:
            raise ValueError(f"component template unmanagedFiles[{index}] has invalid fields")
        path = project_template.safe_relative(item["path"], f"unmanagedFiles[{index}].path")
        if path == STATE_PATH.as_posix() or path in seen:
            raise ValueError(f"duplicate or reserved component template path: {path}")
        seen.add(path)
        reason = item["reason"]
        if not isinstance(reason, str) or not reason:
            raise ValueError(f"component template unmanagedFiles[{index}] reason is invalid")
        unmanaged.append({"path": path, "reason": reason})
    return {
        "schemaVersion": 1,
        "template": TEMPLATE_ID,
        "kind": kind,
        "name": name,
        "appliedVersion": version,
        "managedFiles": managed,
        "projectFiles": project_files,
        "unmanagedFiles": sorted(unmanaged, key=lambda item: item["path"]),
    }


def load_state(root: Path) -> dict[str, Any]:
    path = root / STATE_PATH
    if not path.is_file():
        raise FileNotFoundError(
            f"component template state not found: {path}; run pdr component adopt"
        )
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read component template state: {path}") from error
    if not isinstance(document, dict):
        raise ValueError("component template state root must be an object")
    return validate_state(document)


def write_initial_state(root: Path, kind: str, name: str,
                        rendered: dict[str, str]) -> None:
    managed, project_files = split_files(rendered)
    project_template.atomic_json(
        root / STATE_PATH,
        build_state(kind, name, CURRENT_TEMPLATE_VERSION, managed, project_files),
    )


def require_current_clean(root: Path,
                          base_renderer: BaseRenderer = default_base_renderer) -> dict[str, Any] | None:
    root = root.resolve()
    if not (root / STATE_PATH).is_file():
        return None
    state = load_state(root)
    if state["appliedVersion"] != CURRENT_TEMPLATE_VERSION:
        raise ValueError(
            f"component template is outdated: {root}; "
            f"applied={state['appliedVersion']} current={CURRENT_TEMPLATE_VERSION}"
        )
    desired, _ = split_files(render_component_template(
        state["kind"], state["name"], base_renderer, CURRENT_TEMPLATE_VERSION
    ))
    managed = {item["path"]: item["baselineSha256"] for item in state["managedFiles"]}
    unmanaged = {item["path"] for item in state["unmanagedFiles"]}
    missing_records = sorted(set(desired) - set(managed) - unmanaged)
    unexpected_records = sorted(set(managed) - set(desired))
    stale_baselines = sorted(
        path for path, baseline in managed.items()
        if path in desired and baseline != project_template.sha256_text(desired[path])
    )
    if missing_records or unexpected_records or stale_baselines:
        details = []
        if missing_records:
            details.append("untracked=" + ",".join(missing_records))
        if unexpected_records:
            details.append("unexpected=" + ",".join(unexpected_records))
        if stale_baselines:
            details.append("stale-baseline=" + ",".join(stale_baselines))
        raise ValueError(
            f"component template state does not match the current renderer in {root}: "
            + "; ".join(details)
        )
    drift = [
        item["path"] for item in state["managedFiles"]
        if project_template.file_sha256(root / item["path"]) != item["baselineSha256"]
    ]
    if drift:
        raise ValueError(
            f"component template managed files drifted in {root}: " + ", ".join(drift)
        )
    return state


def status_document(root: Path, base_renderer: BaseRenderer) -> dict[str, Any]:
    root = root.resolve()
    state = load_state(root)
    if state["appliedVersion"] > CURRENT_TEMPLATE_VERSION:
        raise ValueError("component template was created by a newer pdr CLI")
    desired = render_component_template(
        state["kind"], state["name"], base_renderer, CURRENT_TEMPLATE_VERSION
    )
    desired_managed, desired_project = split_files(desired)
    managed = {item["path"]: item["baselineSha256"] for item in state["managedFiles"]}
    unmanaged_paths = {item["path"] for item in state["unmanagedFiles"]}
    records: list[dict[str, Any]] = []
    drifted = False
    for path, baseline in sorted(managed.items()):
        current = project_template.file_sha256(root / path)
        condition = "clean" if current == baseline else ("missing" if current is None else "modified")
        drifted = drifted or condition != "clean"
        records.append({
            "path": path,
            "condition": condition,
            "baselineSha256": baseline,
            "currentSha256": current,
            "targetSha256": (
                project_template.sha256_text(desired_managed[path])
                if path in desired_managed else None
            ),
        })
    for path in sorted(set(desired_managed) - set(managed) - unmanaged_paths):
        records.append({
            "path": path,
            "condition": "untracked",
            "baselineSha256": None,
            "currentSha256": project_template.file_sha256(root / path),
            "targetSha256": project_template.sha256_text(desired_managed[path]),
        })
        drifted = True
    project_records = []
    for path, content in sorted(desired_project.items()):
        current = project_template.file_sha256(root / path)
        template_sha = project_template.sha256_text(content)
        condition = "missing" if current is None else (
            "template-original" if current == template_sha else "product-owned"
        )
        project_records.append({
            "path": path, "condition": condition,
            "templateSha256": template_sha, "currentSha256": current,
        })
    update_available = state["appliedVersion"] < CURRENT_TEMPLATE_VERSION
    return {
        "schemaVersion": 1,
        "operation": "component-template-status",
        "component": str(root),
        "kind": state["kind"],
        "name": state["name"],
        "appliedVersion": state["appliedVersion"],
        "currentVersion": CURRENT_TEMPLATE_VERSION,
        "updateAvailable": update_available,
        "drifted": drifted,
        "healthy": not update_available and not drifted,
        "managedFiles": records,
        "projectFiles": project_records,
        "unmanagedFiles": state["unmanagedFiles"],
    }


def _write_report(root: Path, value: str | Path | None, document: dict[str, Any]) -> None:
    project_template.write_report(root, value, document)


def status_command(args: Any, base_renderer: BaseRenderer) -> int:
    root = Path(args.component).resolve()
    report = status_document(root, base_renderer)
    _write_report(root, args.report, report)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(
            f"PDR_COMPONENT_TEMPLATE_STATUS kind={report['kind']} "
            f"version={report['appliedVersion']} current={report['currentVersion']} "
            f"update={str(report['updateAvailable']).lower()} "
            f"drift={str(report['drifted']).lower()}"
        )
    return 2 if args.check and not report["healthy"] else 0


def adopt_command(args: Any, base_renderer: BaseRenderer) -> int:
    root = Path(args.component).resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"component directory not found: {root}")
    state_path = root / STATE_PATH
    if state_path.exists():
        raise ValueError("component already has template state")
    rendered = render_component_template(args.kind, args.name, base_renderer, args.version)
    desired_managed, project_files = split_files(rendered)
    managed: dict[str, str] = {}
    unmanaged: dict[str, str] = {}
    for path, content in desired_managed.items():
        current = project_template.file_sha256(root / path)
        if current == project_template.sha256_text(content):
            managed[path] = content
        else:
            unmanaged[path] = "missing" if current is None else "pre-existing-customization"
    state = build_state(
        args.kind, args.name, args.version, managed, project_files, unmanaged
    )
    journal = project_template.transactional_write(
        root,
        "component-template-adopt",
        {STATE_PATH.as_posix(): project_template.pretty_json(state)},
        {STATE_PATH.as_posix(): None},
    )
    report = {
        "schemaVersion": 1,
        "operation": "component-template-adopt",
        "kind": args.kind,
        "name": args.name,
        "version": args.version,
        "managedFiles": sorted(managed),
        "unmanagedFiles": state["unmanagedFiles"],
        "journal": journal.relative_to(root).as_posix(),
    }
    _write_report(root, args.report, report)
    print(
        f"PDR_COMPONENT_TEMPLATE_ADOPT_PASS kind={args.kind} version={args.version} "
        f"managed={len(managed)} unmanaged={len(unmanaged)} journal={journal}"
    )
    return 0


def upgrade_command(args: Any, base_renderer: BaseRenderer) -> int:
    root = Path(args.component).resolve()
    state_before = project_template.file_sha256(root / STATE_PATH)
    state = load_state(root)
    if project_template.file_sha256(root / STATE_PATH) != state_before:
        raise RuntimeError("component template state changed during upgrade planning")
    target = CURRENT_TEMPLATE_VERSION if args.target_version is None else args.target_version
    if target not in SUPPORTED_TEMPLATE_VERSIONS:
        raise ValueError(f"unsupported component template target version: {target}")
    if target < state["appliedVersion"]:
        raise ValueError("component template downgrade is not supported")
    rendered = render_component_template(state["kind"], state["name"], base_renderer, target)
    desired_managed, desired_project = split_files(rendered)
    actions, conflicts, observed = project_template.conflict_plan(root, desired_managed, state)
    accept = project_template.normalize_selections(args.accept_template, "--accept-template")
    keep = project_template.normalize_selections(args.keep_project, "--keep-project")
    if accept & keep:
        raise ValueError("a component template path cannot be both accepted and kept")
    conflict_paths = {item["path"] for item in conflicts}
    unknown = (accept | keep) - conflict_paths
    if unknown:
        raise ValueError("conflict selection is not active: " + ", ".join(sorted(unknown)))
    unresolved = conflict_paths - accept - keep
    report: dict[str, Any] = {
        "schemaVersion": 1,
        "operation": "component-template-upgrade",
        "component": str(root),
        "kind": state["kind"],
        "name": state["name"],
        "fromVersion": state["appliedVersion"],
        "toVersion": target,
        "actions": [{"path": path, "action": action} for path, action in sorted(actions.items())],
        "conflicts": conflicts,
        "unresolvedConflicts": sorted(unresolved),
        "applied": False,
    }
    if unresolved:
        _write_report(root, args.report, report)
        print(
            f"PDR_COMPONENT_TEMPLATE_UPGRADE_CONFLICT conflicts={len(unresolved)} "
            f"report={args.report or '-'}"
        )
        return 2
    file_changes: dict[str, bytes | None] = {}
    managed_content: dict[str, str] = {}
    unmanaged = {item["path"]: item["reason"] for item in state["unmanagedFiles"]}
    for path, action in sorted(actions.items()):
        if path in keep:
            unmanaged[path] = "kept-product-customization"
            continue
        unmanaged.pop(path, None)
        if path in desired_managed:
            managed_content[path] = desired_managed[path]
            if action != "manage" or path in accept:
                file_changes[path] = desired_managed[path].encode("utf-8")
        elif action == "remove" or path in accept:
            file_changes[path] = None
    new_state = build_state(
        state["kind"], state["name"], target,
        managed_content, desired_project, unmanaged,
    )
    file_changes[STATE_PATH.as_posix()] = project_template.pretty_json(new_state)
    preconditions = dict(observed)
    preconditions[STATE_PATH.as_posix()] = state_before
    journal = project_template.transactional_write(
        root, "component-template-upgrade", file_changes, preconditions
    )
    report.update({
        "applied": True,
        "journal": journal.relative_to(root).as_posix(),
        "managedFiles": [item["path"] for item in new_state["managedFiles"]],
        "projectFiles": new_state["projectFiles"],
        "unmanagedFiles": new_state["unmanagedFiles"],
    })
    _write_report(root, args.report, report)
    print(
        f"PDR_COMPONENT_TEMPLATE_UPGRADE_PASS kind={state['kind']} "
        f"from={state['appliedVersion']} to={target} managed={len(new_state['managedFiles'])} "
        f"unmanaged={len(new_state['unmanagedFiles'])} journal={journal}"
    )
    return 0


def recover_command(args: Any) -> int:
    root = Path(args.component).resolve()
    journal = project_template.confined(
        root, args.journal, "component template recovery journal", must_exist=True
    )
    changed, transaction_id, status = project_template.recover_transaction(
        root,
        journal,
        {"component-template-adopt", "component-template-upgrade"},
        args.retry_rollback,
    )
    marker = "PASS" if changed else "NOOP"
    print(
        f"PDR_COMPONENT_TEMPLATE_RECOVER_{marker} transaction={transaction_id} "
        f"status={status} journal={journal}"
    )
    return 0


def baseline_fingerprint(kind: str, base_renderer: BaseRenderer,
                         name: str = "TemplateProbe") -> str:
    rendered = render_component_template(kind, name, base_renderer, 1)
    evidence = {
        path: project_template.sha256_text(content)
        for path, content in sorted(rendered.items())
    }
    return hashlib.sha256(project_template.canonical_json(evidence)).hexdigest()
