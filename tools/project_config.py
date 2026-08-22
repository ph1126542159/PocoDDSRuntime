#!/usr/bin/env python3
"""Resolve deterministic, layered and migration-aware product configuration."""

from __future__ import annotations

import hashlib
import json
import os
import re
from copy import deepcopy
from pathlib import Path
from typing import Any


ENVIRONMENT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
LAYER_SUFFIXES = {".json", ".yaml", ".yml"}
SECRET_TOKENS = ("password", "secret", "token", "privatekey", "private_key")


def canonical_json(document: Any) -> bytes:
    return json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def load_document(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    try:
        document = json.loads(text)
    except json.JSONDecodeError as json_error:
        try:
            import yaml  # type: ignore[import-not-found]
        except ImportError as error:
            raise ValueError(
                f"{path} must use JSON-compatible YAML when PyYAML is unavailable"
            ) from json_error
        document = yaml.safe_load(text)
    if not isinstance(document, dict):
        raise ValueError(f"configuration document root must be an object: {path}")
    return document


def is_environment_reference(value: Any) -> bool:
    return isinstance(value, dict) and set(value) == {"$env"} and isinstance(value["$env"], str)


def sensitive_key(path: tuple[str, ...]) -> bool:
    if not path:
        return False
    lowered = path[-1].lower()
    if lowered.endswith(("environment", "file", "path")):
        return False
    return any(token in lowered for token in SECRET_TOKENS)


def inspect_secrets(value: Any, path: tuple[str, ...], references: set[str]) -> None:
    if is_environment_reference(value):
        variable = value["$env"]
        if not ENVIRONMENT_NAME.fullmatch(variable):
            raise ValueError(f"invalid environment reference at {'.'.join(path)}: {variable}")
        references.add(variable)
        return
    if sensitive_key(path) and value not in (None, ""):
        raise ValueError(
            f"inline secret is prohibited at {'.'.join(path)}; use {{\"$env\": \"NAME\"}}"
        )
    if isinstance(value, dict):
        for key, nested in value.items():
            if not isinstance(key, str) or not key:
                raise ValueError("configuration object keys must be non-empty strings")
            inspect_secrets(nested, (*path, key), references)
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            inspect_secrets(nested, (*path, str(index)), references)


def merge_values(base: dict[str, Any], override: dict[str, Any], source: str,
                 path: tuple[str, ...] = ()) -> None:
    for key, value in override.items():
        current_path = (*path, key)
        if key not in base:
            base[key] = deepcopy(value)
            continue
        current = base[key]
        if isinstance(current, dict) and isinstance(value, dict):
            if is_environment_reference(current) or is_environment_reference(value):
                if not (is_environment_reference(current) and is_environment_reference(value)):
                    raise ValueError(
                        f"configuration type changed at {'.'.join(current_path)} in {source}"
                    )
                base[key] = deepcopy(value)
            else:
                merge_values(current, value, source, current_path)
            continue
        if type(current) is not type(value):
            raise ValueError(
                f"configuration type changed at {'.'.join(current_path)} in {source}: "
                f"{type(current).__name__} -> {type(value).__name__}"
            )
        base[key] = deepcopy(value)


def configuration_files(root: Path, layers: list[str]) -> list[tuple[str, Path]]:
    result: list[tuple[str, Path]] = []
    for layer in layers:
        directory = root / layer
        files = sorted(
            path for path in directory.iterdir()
            if path.is_file() and path.suffix.lower() in LAYER_SUFFIXES
        )
        if not files:
            raise ValueError(f"configuration layer contains no JSON/YAML documents: {layer}")
        result.extend((layer, path) for path in files)
    return result


def get_parent(document: dict[str, Any], dotted: str, create: bool = False) -> tuple[dict[str, Any], str]:
    parts = dotted.split(".")
    if not dotted or any(not part for part in parts):
        raise ValueError(f"invalid migration path: {dotted}")
    current = document
    for part in parts[:-1]:
        nested = current.get(part)
        if nested is None and create:
            nested = {}
            current[part] = nested
        if not isinstance(nested, dict):
            raise ValueError(f"migration path is not an object: {dotted}")
        current = nested
    return current, parts[-1]


def apply_migration(values: dict[str, Any], migration: dict[str, Any], source: Path) -> None:
    operations = migration.get("operations")
    if not isinstance(operations, list):
        raise ValueError(f"migration operations must be an array: {source}")
    for operation in operations:
        if not isinstance(operation, dict):
            raise ValueError(f"migration operation must be an object: {source}")
        kind = operation.get("op")
        path = operation.get("path")
        if kind == "rename":
            old_path = operation.get("from")
            if not isinstance(old_path, str) or not isinstance(path, str):
                raise ValueError(f"rename requires from and path: {source}")
            old_parent, old_key = get_parent(values, old_path)
            if old_key not in old_parent:
                raise ValueError(f"migration source does not exist: {old_path}")
            new_parent, new_key = get_parent(values, path, create=True)
            if new_key in new_parent:
                raise ValueError(f"migration destination already exists: {path}")
            new_parent[new_key] = old_parent.pop(old_key)
        elif kind == "remove":
            if not isinstance(path, str):
                raise ValueError(f"remove requires path: {source}")
            parent, key = get_parent(values, path)
            if key not in parent:
                raise ValueError(f"migration remove path does not exist: {path}")
            del parent[key]
        elif kind == "set-default":
            if not isinstance(path, str) or "value" not in operation:
                raise ValueError(f"set-default requires path and value: {source}")
            parent, key = get_parent(values, path, create=True)
            parent.setdefault(key, deepcopy(operation["value"]))
        else:
            raise ValueError(f"unsupported migration operation {kind!r}: {source}")


def migrate(values: dict[str, Any], root: Path, directory: str,
            current: int, target: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if target < current:
        raise ValueError("configuration downgrade is not supported")
    result = deepcopy(values)
    applied: list[dict[str, Any]] = []
    version = current
    while version < target:
        path = root / directory / f"v{version}-to-v{version + 1}.json"
        if not path.is_file():
            raise ValueError(f"configuration migration not found: {path.relative_to(root)}")
        document = load_document(path)
        if document.get("from") != version or document.get("to") != version + 1:
            raise ValueError(f"configuration migration version mismatch: {path.relative_to(root)}")
        apply_migration(result, document, path)
        applied.append({
            "from": version, "to": version + 1,
            "path": path.relative_to(root).as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        })
        version += 1
    return result, applied


def resolve_configuration(manifest: Path, target_version: int | None = None,
                          require_environment: bool = False) -> dict[str, Any]:
    import project_manager

    manifest = manifest.resolve()
    project = project_manager.validate_manifest(manifest, check_paths=True)
    root = manifest.parent
    expected_version = project["config"]["version"]
    merged: dict[str, Any] = {}
    layer_evidence: list[dict[str, Any]] = []
    for layer, path in configuration_files(root, project["config"]["layers"]):
        document = load_document(path)
        if set(document) - {"version", "values"}:
            raise ValueError(f"unknown configuration document fields: {path.relative_to(root)}")
        if document.get("version") != expected_version:
            raise ValueError(
                f"configuration version mismatch in {path.relative_to(root)}: "
                f"expected {expected_version}"
            )
        values = document.get("values")
        if not isinstance(values, dict):
            raise ValueError(f"configuration values must be an object: {path.relative_to(root)}")
        merge_values(merged, values, path.relative_to(root).as_posix())
        layer_evidence.append({
            "layer": layer, "path": path.relative_to(root).as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        })
    target = target_version if target_version is not None else expected_version
    resolved, migrations = migrate(
        merged, root, project["config"]["migrations"], expected_version, target
    )
    references: set[str] = set()
    inspect_secrets(resolved, (), references)
    missing = sorted(name for name in references if not os.environ.get(name))
    if require_environment and missing:
        raise ValueError("required configuration environment variables are unset: " + ", ".join(missing))
    return {
        "schemaVersion": 1,
        "operation": "project-config-resolve",
        "project": project["name"],
        "sourceVersion": expected_version,
        "configVersion": target,
        "layers": layer_evidence,
        "migrations": migrations,
        "environmentReferences": sorted(references),
        "missingEnvironmentReferences": missing,
        "valuesSha256": hashlib.sha256(canonical_json(resolved)).hexdigest(),
        "values": resolved,
    }


def resolve_project_config(args: Any) -> int:
    import project_manager

    manifest = Path(args.manifest).resolve()
    output = Path(args.output).resolve()
    try:
        output.relative_to(manifest.parent)
    except ValueError as error:
        raise ValueError("resolved configuration output must stay inside the project root") from error
    result = resolve_configuration(manifest, args.target_version, args.require_environment)
    project_manager.atomic_json(output, result)
    print(
        f"PDR_PROJECT_CONFIG_RESOLVE_PASS version={result['configVersion']} "
        f"layers={len(result['layers'])} output={output}"
    )
    return 0
