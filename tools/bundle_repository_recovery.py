#!/usr/bin/env python3
"""Inspect or restore a Bundle repository from BundleManager's LKG snapshot.

Restore is intentionally offline. Native OSP Bundle libraries are process-scoped,
so a crashed or unhealthy Runtime must not try to unload and replace them in place.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
from datetime import datetime, timezone
import zipfile


PREFIX = re.compile(r"^\d{4}_(.+)$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
MAX_ROLLOUT_SEQUENCE = (1 << 63) - 1


def fingerprint_update(digest, value: bytes) -> None:
    digest.update(len(value).to_bytes(8, "big"))
    digest.update(value)


def repository_fingerprint(repository: Path) -> str:
    if not repository.is_dir():
        raise ValueError(f"Bundle repository is not a directory: {repository}")
    entries: list[tuple[str, str, Path]] = []
    for path in repository.rglob("*"):
        relative = path.relative_to(repository).as_posix()
        if path.is_symlink():
            kind = "L"
        elif path.is_file():
            kind = "F"
        elif path.is_dir():
            kind = "D"
        else:
            raise ValueError(f"unsupported Bundle repository entry: {path}")
        entries.append((relative, kind, path))
    if not entries:
        raise ValueError(f"Bundle repository is empty: {repository}")
    digest = hashlib.sha256()
    fingerprint_update(digest, b"PDR-BUNDLE-REPOSITORY/1")
    for relative, kind, path in sorted(entries):
        digest.update(kind.encode("ascii"))
        fingerprint_update(digest, relative.encode("utf-8"))
        if kind == "L":
            fingerprint_update(digest, os.readlink(path).replace("\\", "/").encode("utf-8"))
        elif kind == "F":
            size = path.stat().st_size
            digest.update(size.to_bytes(8, "big"))
            read = 0
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(64 * 1024), b""):
                    digest.update(chunk)
                    read += len(chunk)
            if read != size or path.stat().st_size != size:
                raise ValueError(f"Bundle repository changed while fingerprinting: {path}")
    return digest.hexdigest()


def read_properties(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def bundle_name(path: Path) -> str:
    match = PREFIX.match(path.name)
    return match.group(1) if match else path.name


def validate_bundle(path: Path) -> None:
    if path.is_dir():
        manifest = path / "META-INF" / "manifest.mf"
        if not manifest.is_file():
            raise ValueError(f"directory Bundle has no META-INF/manifest.mf: {path}")
        return
    if not path.is_file():
        raise ValueError(f"Bundle entry is neither a file nor a directory: {path}")
    try:
        with zipfile.ZipFile(path) as archive:
            names = {name.replace("\\", "/") for name in archive.namelist()}
            if "META-INF/manifest.mf" not in names:
                raise ValueError(f"archive Bundle has no META-INF/manifest.mf: {path}")
    except zipfile.BadZipFile as error:
        raise ValueError(f"invalid Bundle archive: {path}") from error


def inventory(repository: Path) -> list[dict[str, object]]:
    if not repository.is_dir():
        raise ValueError(f"Bundle repository is not a directory: {repository}")
    result: list[dict[str, object]] = []
    for entry in sorted(repository.iterdir(), key=lambda item: item.name.lower()):
        if entry.name.startswith("."):
            continue
        validate_bundle(entry)
        item: dict[str, object] = {
            "storedName": entry.name,
            "restoreName": bundle_name(entry),
            "kind": "directory" if entry.is_dir() else "archive",
        }
        if entry.is_file():
            digest = hashlib.sha256()
            with entry.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            item["sha256"] = digest.hexdigest()
            item["bytes"] = entry.stat().st_size
        result.append(item)
    if not result:
        raise ValueError(f"Bundle repository is empty: {repository}")
    restore_names = [str(item["restoreName"]).lower() for item in result]
    if len(restore_names) != len(set(restore_names)):
        raise ValueError("last-known-good snapshot contains duplicate restore names")
    return result


def append_audit(state_dir: Path, event: dict[str, object]) -> None:
    event = {"timestamp": datetime.now(timezone.utc).isoformat(), **event}
    state_dir.mkdir(parents=True, exist_ok=True)
    with (state_dir / "recovery-audit.jsonl").open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def rollout_sequence(values: dict[str, str], description: str) -> int:
    try:
        value = int(values.get("rolloutSequence", ""), 10)
    except ValueError as error:
        raise ValueError(f"{description} rolloutSequence is malformed") from error
    if value < 1 or value > MAX_ROLLOUT_SEQUENCE:
        raise ValueError(f"{description} rolloutSequence is outside 1..2^63-1")
    return value


def validate_authorized_lkg(state_dir: Path, backup: Path) -> dict[str, object]:
    accepted = read_properties(state_dir / "repository-rollout-high-water.properties")
    metadata = read_properties(state_dir / "last-known-good.properties")
    if not accepted:
        return {"protected": False, "safe": True, "error": ""}
    try:
        accepted_sequence = rollout_sequence(accepted, "accepted high-water")
        backup_sequence = rollout_sequence(metadata, "last-known-good metadata")
        accepted_digest = accepted.get("candidateDigest", "")
        backup_digest = metadata.get("candidateDigest", "")
        if not SHA256.fullmatch(accepted_digest) or not SHA256.fullmatch(backup_digest):
            raise ValueError("authorized recovery metadata contains an invalid candidateDigest")
        if metadata.get("authorizationVerified") != "true":
            raise ValueError("last-known-good snapshot has no verified authorization metadata")
        if metadata.get("repositoryId") != accepted.get("repositoryId"):
            raise ValueError("last-known-good repository identity differs from the high-water mark")
        if backup_sequence != accepted_sequence:
            raise ValueError(
                f"last-known-good rollout {backup_sequence} differs from accepted high-water {accepted_sequence}"
            )
        if backup_digest != accepted_digest:
            raise ValueError("last-known-good digest differs from the accepted high-water digest")
        provenance: dict[str, str] = {}
        if accepted.get("schemaVersion") == "2":
            if metadata.get("schemaVersion") != "2":
                raise ValueError("last-known-good metadata lacks accepted release provenance")
            for field in ("releaseManifestSha256", "sbomSha256", "artifactSetSha256"):
                if (not SHA256.fullmatch(accepted.get(field, "")) or
                        metadata.get(field) != accepted.get(field)):
                    raise ValueError(
                        f"last-known-good {field} differs from the high-water mark"
                    )
                provenance[field] = accepted[field]
            for field in ("releaseVersion", "gitCommit", "builderId", "buildProfile"):
                if not accepted.get(field) or metadata.get(field) != accepted.get(field):
                    raise ValueError(
                        f"last-known-good {field} differs from the high-water mark"
                    )
                provenance[field] = accepted[field]
        actual_digest = repository_fingerprint(backup)
        if actual_digest != backup_digest:
            raise ValueError(
                f"last-known-good content digest mismatch: expected {backup_digest}, actual {actual_digest}"
            )
        return {
            "protected": True,
            "safe": True,
            "error": "",
            "rolloutSequence": accepted_sequence,
            "candidateDigest": accepted_digest,
            "provenance": provenance,
        }
    except ValueError as error:
        return {"protected": True, "safe": False, "error": str(error)}


def status(state_dir: Path, repository: Path) -> dict[str, object]:
    journal = read_properties(state_dir / "transaction.properties")
    backup = state_dir / "last-known-good"
    try:
        backup_inventory = inventory(backup)
        backup_error = ""
    except ValueError as error:
        backup_inventory = []
        backup_error = str(error)
    rollback = validate_authorized_lkg(state_dir, backup) if backup_inventory else {
        "protected": bool(read_properties(state_dir / "repository-rollout-high-water.properties")),
        "safe": False,
        "error": backup_error or "last-known-good snapshot is unavailable",
    }
    return {
        "stateDirectory": str(state_dir.resolve()),
        "repository": str(repository.resolve()),
        "repositoryExists": repository.is_dir(),
        "transaction": journal,
        "restartRequired": journal.get("state") == "restartRequired",
        "backupAvailable": bool(backup_inventory),
        "backupBundleCount": len(backup_inventory),
        "backupError": backup_error,
        "backupInventory": backup_inventory,
        "rolloutProtection": rollback,
        "previousRepositoryAvailable": repository.with_name(repository.name + ".pdr-previous").is_dir(),
    }


def restore(state_dir: Path, repository: Path, runtime_stopped: bool) -> dict[str, object]:
    if not runtime_stopped:
        raise ValueError("restore requires --runtime-stopped acknowledgement")
    backup = state_dir / "last-known-good"
    backup_inventory = inventory(backup)
    rollback = validate_authorized_lkg(state_dir, backup)
    if rollback["protected"] and not rollback["safe"]:
        raise ValueError(f"authorized Bundle recovery rejected: {rollback['error']}")
    repository = repository.resolve()
    parent = repository.parent
    if not parent.is_dir():
        raise ValueError(f"repository parent does not exist: {parent}")
    staging = repository.with_name(repository.name + ".pdr-staging")
    previous = repository.with_name(repository.name + ".pdr-previous")

    if not repository.exists() and previous.is_dir():
        previous.rename(repository)
    if staging.exists():
        shutil.rmtree(staging)
    if previous.exists():
        shutil.rmtree(previous)
    staging.mkdir()

    try:
        for item in backup_inventory:
            source = backup / str(item["storedName"])
            target = staging / str(item["restoreName"])
            if source.is_dir():
                shutil.copytree(source, target)
            else:
                shutil.copy2(source, target)
        staged_inventory = inventory(staging)
        if len(staged_inventory) != len(backup_inventory):
            raise ValueError("staged Bundle inventory count does not match last-known-good snapshot")
        if rollback["protected"]:
            staged_digest = repository_fingerprint(staging)
            if staged_digest != rollback["candidateDigest"]:
                raise ValueError(
                    "staged Bundle repository does not match the accepted rollout digest"
                )

        repository.rename(previous)
        try:
            staging.rename(repository)
        except Exception:
            previous.rename(repository)
            raise
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise

    result = {
        "result": "RESTORED",
        "repository": str(repository),
        "bundleCount": len(backup_inventory),
        "previousRepository": str(previous),
        "restartRequired": True,
        "rolloutProtection": rollback,
    }
    append_audit(state_dir, result)
    return result


def write_result(result: dict[str, object], report: Path | None) -> None:
    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    print(rendered)
    if report is not None:
        report.parent.mkdir(parents=True, exist_ok=True)
        temporary = report.with_suffix(report.suffix + ".tmp")
        temporary.write_text(rendered + "\n", encoding="utf-8")
        os.replace(temporary, report)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("status", "restore"))
    parser.add_argument("--state-dir", required=True, type=Path)
    parser.add_argument("--repository", required=True, type=Path)
    parser.add_argument("--runtime-stopped", action="store_true")
    parser.add_argument("--report", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        result = (
            status(args.state_dir, args.repository)
            if args.command == "status"
            else restore(args.state_dir, args.repository, args.runtime_stopped)
        )
        write_result(result, args.report)
        return 0
    except (OSError, ValueError) as error:
        print(json.dumps({"result": "ERROR", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
