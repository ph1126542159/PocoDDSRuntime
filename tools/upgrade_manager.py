#!/usr/bin/env python3
"""Verify, atomically install and roll back PocoDDSRuntime release directories."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def audit(path: Path, upgrade_id: str, event: str, **fields: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"timestamp": now(), "upgradeId": upgrade_id, "event": event, **fields}
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + "\n")


def safe_relative(value: str) -> Path:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError(f"unsafe artifact path: {value}")
    return path


def validate_manifest(manifest_path: Path, package: Path) -> dict[str, Any]:
    document = json.loads(manifest_path.read_text(encoding="utf-8"))
    if document.get("product") != "PocoDDSRuntime" or document.get("schemaVersion") != 1:
        raise ValueError("unsupported release manifest")
    if not document.get("files"):
        raise ValueError("release manifest contains no files")
    package_root = package.resolve()
    for entry in document["files"]:
        relative = safe_relative(entry["path"])
        path = package_root / relative
        if not path.is_file():
            raise ValueError(f"missing artifact: {relative.as_posix()}")
        if path.stat().st_size != entry["size"] or sha256(path) != entry["sha256"]:
            raise ValueError(f"artifact verification failed: {relative.as_posix()}")
    return document


def deployed_version(target: Path) -> str | None:
    marker = target / "pdr-release.json"
    if not marker.is_file():
        return None
    return str(json.loads(marker.read_text(encoding="utf-8")).get("version") or "") or None


def major(version: str) -> int:
    parts = version.split(".")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        raise ValueError(f"invalid semantic version: {version}")
    return int(parts[0])


def validate_locations(package: Path, target: Path) -> None:
    package = package.resolve()
    target = target.resolve()
    if target == target.parent or target == Path.cwd().resolve():
        raise ValueError("refusing to replace a filesystem or current workspace root")
    if package == target or package in target.parents or target in package.parents:
        raise ValueError("package and target directories must not overlap")


def stage_files(document: dict[str, Any], package: Path, staging: Path) -> None:
    staging.mkdir(parents=False)
    for entry in document["files"]:
        relative = safe_relative(entry["path"])
        destination = staging / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(package / relative, destination)
        if destination.stat().st_size != entry["size"] or sha256(destination) != entry["sha256"]:
            raise ValueError(f"staged artifact verification failed: {relative.as_posix()}")
    (staging / "pdr-release.json").write_text(
        json.dumps(
            {
                "product": "PocoDDSRuntime",
                "version": document["version"],
                "gitCommit": document.get("gitCommit", "unknown"),
                "installedAt": now(),
            },
            indent=2,
        ),
        encoding="utf-8",
        newline="\n",
    )


def healthy(target: Path, file_probe: str | None, url: str | None, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if file_probe and (target / safe_relative(file_probe)).is_file():
            return True
        if url:
            try:
                with urllib.request.urlopen(url, timeout=min(2.0, timeout)) as response:
                    if 200 <= response.status < 300:
                        return True
            except Exception:
                pass
        if not file_probe and not url:
            return True
        time.sleep(0.1)
    return False


def remove_tree(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)


def apply_upgrade(args: argparse.Namespace) -> int:
    package = args.package.resolve()
    target = args.target.resolve()
    manifest_path = args.manifest.resolve()
    audit_path = args.audit.resolve()
    upgrade_id = str(uuid.uuid4())
    staging = target.parent / f".{target.name}.pdr-staging-{upgrade_id}"
    backup = target.parent / f".{target.name}.pdr-backup-{upgrade_id}"
    failed = target.parent / f".{target.name}.pdr-failed-{upgrade_id}"
    try:
        validate_locations(package, target)
        document = validate_manifest(manifest_path, package)
        from_version = deployed_version(target)
        to_version = str(document["version"])
        major(to_version)
        if from_version:
            major(from_version)
            if major(from_version) != major(to_version) and not args.allow_major_upgrade:
                raise ValueError("major-version upgrade requires --allow-major-upgrade")
            allowed_sources = document.get("compatibility", {}).get("upgradeFrom", [])
            if from_version != to_version and from_version not in allowed_sources:
                raise ValueError(
                    f"compatibility matrix does not allow upgrade from {from_version} to {to_version}"
                )
        audit(audit_path, upgrade_id, "preflight_passed", fromVersion=from_version, toVersion=to_version)
        stage_files(document, package, staging)
        audit(audit_path, upgrade_id, "staging_verified", files=len(document["files"]))
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            target.rename(backup)
        try:
            staging.rename(target)
        except Exception:
            if backup.exists() and not target.exists():
                backup.rename(target)
            raise
        audit(audit_path, upgrade_id, "activated", backup=str(backup) if backup.exists() else None)
        if not healthy(target, args.health_file, args.health_url, args.health_timeout):
            target.rename(failed)
            if backup.exists():
                backup.rename(target)
            audit(audit_path, upgrade_id, "health_failed_rollback", failedPath=str(failed))
            remove_tree(failed)
            return 2
        audit(audit_path, upgrade_id, "health_passed", version=to_version)
        print(f"UPGRADE_PASS id={upgrade_id} from={from_version} to={to_version} backup={backup if backup.exists() else 'none'}")
        return 0
    except Exception as error:
        audit(audit_path, upgrade_id, "upgrade_failed", error=str(error))
        remove_tree(staging)
        print(f"UPGRADE_ERROR: {error}", file=sys.stderr)
        return 1


def rollback(args: argparse.Namespace) -> int:
    target = args.target.resolve()
    audit_path = args.audit.resolve()
    upgrade_id = str(uuid.uuid4())
    backups = sorted(target.parent.glob(f".{target.name}.pdr-backup-*"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not backups:
        print("ROLLBACK_ERROR: no backup is available", file=sys.stderr)
        return 1
    backup = backups[0]
    displaced = target.parent / f".{target.name}.pdr-displaced-{upgrade_id}"
    try:
        if target.exists():
            target.rename(displaced)
        backup.rename(target)
        audit(audit_path, upgrade_id, "manual_rollback", restoredVersion=deployed_version(target))
        remove_tree(displaced)
        print(f"ROLLBACK_PASS id={upgrade_id} version={deployed_version(target)}")
        return 0
    except Exception as error:
        if displaced.exists() and not target.exists():
            displaced.rename(target)
        audit(audit_path, upgrade_id, "rollback_failed", error=str(error))
        print(f"ROLLBACK_ERROR: {error}", file=sys.stderr)
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    apply = commands.add_parser("apply")
    apply.add_argument("--package", type=Path, required=True)
    apply.add_argument("--manifest", type=Path, required=True)
    apply.add_argument("--target", type=Path, required=True)
    apply.add_argument("--audit", type=Path, required=True)
    apply.add_argument("--health-file")
    apply.add_argument("--health-url")
    apply.add_argument("--health-timeout", type=float, default=30.0)
    apply.add_argument("--allow-major-upgrade", action="store_true")
    apply.set_defaults(handler=apply_upgrade)
    restore = commands.add_parser("rollback")
    restore.add_argument("--target", type=Path, required=True)
    restore.add_argument("--audit", type=Path, required=True)
    restore.set_defaults(handler=rollback)
    args = parser.parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
