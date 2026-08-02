#!/usr/bin/env python3
"""Verify, atomically install and roll back PocoDDSRuntime release directories."""

from __future__ import annotations

import argparse
import base64
import errno
import hashlib
import hmac
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import urllib.parse
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


EXCLUDED_PARTS = {"logs", "data", "codeCache", "disabled-bundles"}
MUTABLE_PARTS = {"logs", "data", "disabled-bundles"}
TRANSACTION_SCHEMA_VERSION = 1


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def trusted_key(environment: str) -> bytes:
    encoded = os.environ.get(environment)
    if not encoded:
        raise ValueError(f"trusted key environment is unset: {environment}")
    try:
        key = base64.b64decode(encoded, validate=True)
    except Exception as error:
        raise ValueError("trusted key must be valid Base64") from error
    if len(key) < 32:
        raise ValueError("trusted key must decode to at least 32 bytes")
    return key


def verify_trusted_manifest(
        manifest_path: Path, args: argparse.Namespace,
        untrusted_package: Path) -> dict[str, Any] | None:
    signature_path = getattr(args, "signature", None)
    if not signature_path:
        if getattr(args, "allow_unsigned_release", False):
            return None
        raise ValueError("detached release signature is required; unsigned releases require explicit diagnostic authorization")
    environment = getattr(args, "trusted_key_environment", None)
    expected_key_id = getattr(args, "expected_key_id", None)
    if not expected_key_id:
        raise ValueError("signature verification requires expected key id")
    document = json.loads(signature_path.resolve().read_text(encoding="utf-8"))
    if (document.get("schemaVersion") != 1 or
            document.get("product") != "PocoDDSRuntime"):
        raise ValueError("unsupported release signature")
    if document.get("keyId") != expected_key_id:
        raise ValueError("release signature key id is not trusted")
    content = manifest_path.read_bytes()
    digest_value = hashlib.sha256(content).hexdigest()
    if not hmac.compare_digest(str(document.get("manifestSha256", "")), digest_value):
        raise ValueError("release signature manifest digest mismatch")
    algorithm = document.get("algorithm")
    if algorithm == "HMAC-SHA256":
        if not environment:
            raise ValueError("HMAC verification requires trusted key environment")
        expected_signature = base64.b64encode(
            hmac.new(trusted_key(environment), content, hashlib.sha256).digest()
        ).decode("ascii")
        if not hmac.compare_digest(str(document.get("signature", "")), expected_signature):
            raise ValueError("release signature verification failed")
        return {"algorithm": algorithm, "keyId": expected_key_id, "publicKeySha256": None}
    if algorithm == "Ed25519":
        public_key = getattr(args, "public_key", None)
        expected_public_key_sha256 = getattr(args, "expected_public_key_sha256", None)
        if not public_key or not expected_public_key_sha256:
            raise ValueError("Ed25519 verification requires public key and expected public key SHA-256")
        public_key = public_key.resolve()
        actual_public_key_sha256 = sha256(public_key)
        if not hmac.compare_digest(actual_public_key_sha256, expected_public_key_sha256.lower()):
            raise ValueError("release public key SHA-256 is not trusted")
        verifier = getattr(args, "signature_check_executable", None) or Path(__file__).resolve().with_name(
            "pdr-signature-check.exe" if os.name == "nt" else "pdr-signature-check"
        )
        verifier = Path(verifier).resolve()
        if not verifier.is_file():
            raise ValueError(f"Ed25519 signature verifier is unavailable: {verifier}")
        try:
            verifier.relative_to(untrusted_package.resolve())
        except ValueError:
            pass
        else:
            raise ValueError("Ed25519 verifier must not come from the unverified package")
        result = subprocess.run(
            [str(verifier), str(manifest_path), str(signature_path.resolve()),
             str(public_key), expected_key_id],
            capture_output=True, text=True, check=False,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise ValueError(detail or "Ed25519 signature verification failed")
        return {
            "algorithm": algorithm, "keyId": expected_key_id,
            "publicKeySha256": actual_public_key_sha256,
        }
    raise ValueError("unsupported release signature")


def policy_time(value: Any, field: str) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"trust policy {field} must be an ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"trust policy {field} is not valid ISO-8601") from error
    if parsed.tzinfo is None:
        raise ValueError(f"trust policy {field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def validate_trust_policy(
        args: argparse.Namespace, signature_evidence: dict[str, Any] | None,
        untrusted_package: Path) -> dict[str, Any] | None:
    if signature_evidence is None:
        return None
    policy_path = getattr(args, "trust_policy", None)
    if not policy_path:
        if getattr(args, "allow_unmanaged_trust", False):
            return {"managed": False, "explicitlyAllowed": True}
        raise ValueError("signed release requires a pinned trust policy")
    policy_path = policy_path.resolve()
    try:
        policy_path.relative_to(untrusted_package.resolve())
    except ValueError:
        pass
    else:
        raise ValueError("trust policy must not come from the unverified package")
    expected_digest = getattr(args, "expected_trust_policy_sha256", None)
    expected_policy_id = getattr(args, "expected_trust_policy_id", None)
    if not expected_digest or not expected_policy_id:
        raise ValueError("trust policy requires expected policy id and SHA-256")
    actual_digest = sha256(policy_path)
    if not hmac.compare_digest(actual_digest, expected_digest.lower()):
        raise ValueError("release trust policy SHA-256 is not trusted")
    document = json.loads(policy_path.read_text(encoding="utf-8"))
    if (document.get("schemaVersion") != 1 or
            document.get("product") != "PocoDDSRuntime" or
            document.get("policyId") != expected_policy_id):
        raise ValueError("unsupported or unexpected release trust policy")
    allowed = document.get("allowedKeys")
    revoked = document.get("revokedKeys", [])
    if not isinstance(allowed, list) or not isinstance(revoked, list):
        raise ValueError("release trust policy key lists are malformed")
    for entry in allowed:
        if (not isinstance(entry, dict) or not isinstance(entry.get("keyId"), str) or
                entry.get("algorithm") not in {"Ed25519", "HMAC-SHA256"}):
            raise ValueError("release trust policy allowed key entry is malformed")
        if (entry["algorithm"] == "Ed25519" and
                (not isinstance(entry.get("publicKeySha256"), str) or
                 not re.fullmatch(r"[0-9a-f]{64}", entry["publicKeySha256"]))):
            raise ValueError("release trust policy Ed25519 public key digest is malformed")
    key_id = signature_evidence["keyId"]
    for entry in revoked:
        if (not isinstance(entry, dict) or not isinstance(entry.get("keyId"), str) or
                not isinstance(entry.get("revokedAt"), str) or
                not isinstance(entry.get("reason"), str) or not entry["reason"]):
            raise ValueError("release trust policy revoked key entry is malformed")
        policy_time(entry["revokedAt"], "revokedAt")
        if entry["keyId"] == key_id:
            reason = str(entry.get("reason") or "no reason recorded")
            raise ValueError(f"release signing key is revoked: {key_id}: {reason}")
    matches = [entry for entry in allowed if isinstance(entry, dict) and entry.get("keyId") == key_id]
    if len(matches) != 1:
        raise ValueError("release signing key is not uniquely allowed by trust policy")
    entry = matches[0]
    if entry.get("algorithm") != signature_evidence["algorithm"]:
        raise ValueError("release signing algorithm is not allowed by trust policy")
    if (signature_evidence["algorithm"] == "Ed25519" and
            entry.get("publicKeySha256") != signature_evidence["publicKeySha256"]):
        raise ValueError("release public key is not allowed by trust policy")
    current = datetime.now(timezone.utc)
    not_before = policy_time(entry.get("notBefore"), "notBefore")
    not_after = policy_time(entry.get("notAfter"), "notAfter")
    if not_before and not_after and not_before >= not_after:
        raise ValueError("release signing key validity window is invalid")
    if not_before and current < not_before:
        raise ValueError("release signing key is not active yet")
    if not_after and current >= not_after:
        raise ValueError("release signing key has expired")
    return {
        "managed": True,
        "policyId": expected_policy_id,
        "policySha256": actual_digest,
        "keyNotBefore": entry.get("notBefore"),
        "keyNotAfter": entry.get("notAfter"),
    }


def is_link_like(path: Path) -> bool:
    if path.is_symlink():
        return True
    attributes = getattr(path.lstat(), "st_file_attributes", 0)
    return bool(attributes & 0x400)  # Windows FILE_ATTRIBUTE_REPARSE_POINT


def audit(path: Path, upgrade_id: str, event: str, **fields: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"timestamp": now(), "upgradeId": upgrade_id, "event": event, **fields}
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def atomic_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(document, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def transaction_paths(target: Path) -> tuple[Path, Path]:
    return (
        target.parent / f".{target.name}.pdr-upgrade-transaction.json",
        target.parent / f".{target.name}.pdr-upgrade.lock",
    )


def acquire_lock(path: Path, upgrade_id: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as error:
        raise ValueError(
            f"upgrade lock already exists: {path}; inspect or recover the interrupted transaction"
        ) from error
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
        json.dump({"upgradeId": upgrade_id, "pid": os.getpid(), "createdAt": now()}, stream)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def release_lock(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def write_transaction(path: Path, transaction: dict[str, Any], state: str) -> None:
    transaction["state"] = state
    transaction["updatedAt"] = now()
    atomic_json(path, transaction)


def inventory(root: Path) -> list[dict[str, Any]]:
    if not root.is_dir():
        return []
    result = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if is_link_like(path):
            raise ValueError(f"release tree contains a link or reparse point: {relative.as_posix()}")
        if (not path.is_file() or
                any(part in EXCLUDED_PARTS for part in relative.parts)):
            continue
        result.append({
            "path": relative.as_posix(),
            "size": path.stat().st_size,
            "sha256": sha256(path),
        })
    return result


def verify_inventory(root: Path, expected: list[dict[str, Any]]) -> None:
    actual = inventory(root)
    if actual != expected:
        raise ValueError(f"restored release integrity verification failed: {root}")


def transfer_mutable(source: Path, destination: Path) -> list[str]:
    if not source.is_dir():
        return []
    candidates = sorted(
        (path for path in source.rglob("*")
         if path.is_dir() and path.name in MUTABLE_PARTS and
         not any(parent.name in MUTABLE_PARTS for parent in path.parents if parent != source)),
        key=lambda path: len(path.parts),
    )
    for path in candidates:
        relative = path.relative_to(source)
        if (destination / relative).exists():
            raise ValueError(f"mutable state destination already exists: {relative.as_posix()}")
    moved: list[str] = []
    for path in candidates:
        relative = path.relative_to(source)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(target))
        moved.append(relative.as_posix())
    return moved


def safe_relative(value: str) -> Path:
    path = Path(value)
    if (path.is_absolute() or "\\" in value or not path.parts or
            any(part in {"", ".", ".."} for part in path.parts)):
        raise ValueError(f"unsafe artifact path: {value}")
    return path


def validate_manifest(manifest_path: Path, package: Path) -> dict[str, Any]:
    document = json.loads(manifest_path.read_text(encoding="utf-8"))
    if document.get("product") != "PocoDDSRuntime" or document.get("schemaVersion") != 1:
        raise ValueError("unsupported release manifest")
    if not document.get("files"):
        raise ValueError("release manifest contains no files")
    package_root = package.resolve()
    for candidate in package_root.rglob("*"):
        if is_link_like(candidate):
            raise ValueError(
                "package contains a link or reparse point: "
                f"{candidate.relative_to(package_root).as_posix()}"
            )
    expected: set[str] = set()
    for entry in document["files"]:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            raise ValueError("malformed artifact entry")
        relative = safe_relative(entry["path"])
        normalized = relative.as_posix()
        if normalized in expected:
            raise ValueError(f"duplicate artifact entry: {normalized}")
        expected.add(normalized)
        path = (package_root / relative).resolve()
        try:
            path.relative_to(package_root)
        except ValueError as error:
            raise ValueError(f"artifact escapes package root: {normalized}") from error
        if not path.is_file():
            raise ValueError(f"missing artifact: {normalized}")
        if (not isinstance(entry.get("size"), int) or
                not isinstance(entry.get("sha256"), str) or
                path.stat().st_size != entry["size"] or sha256(path) != entry["sha256"]):
            raise ValueError(f"artifact verification failed: {normalized}")
    actual = {
        path.relative_to(package_root).as_posix()
        for path in package_root.rglob("*")
        if path.is_file() and not any(
            part in EXCLUDED_PARTS for part in path.relative_to(package_root).parts
        )
    }
    unexpected = sorted(actual - expected)
    if unexpected:
        raise ValueError(f"unexpected artifact: {unexpected[0]}")
    return document


def validate_preflight(
        document: dict[str, Any], package: Path, target: Path,
        allow_initial_install: bool, min_free_bytes: int) -> tuple[str | None, str]:
    if min_free_bytes < 0:
        raise ValueError("--min-free-bytes must not be negative")
    if not target.exists() and not allow_initial_install:
        raise ValueError("target is not installed; use --allow-initial-install explicitly")
    from_version = deployed_version(target)
    if target.exists() and not from_version:
        raise ValueError("installed target has no valid pdr-release.json version marker")
    to_version = str(document.get("version") or "")
    major(to_version)
    compatibility = document.get("compatibility")
    if not isinstance(compatibility, dict) or compatibility.get("runtime") != to_version:
        raise ValueError("release manifest compatibility.runtime does not match version")
    allowed_sources = compatibility.get("upgradeFrom")
    if not isinstance(allowed_sources, list) or not all(isinstance(item, str) for item in allowed_sources):
        raise ValueError("release manifest compatibility.upgradeFrom must be a string array")
    required = sum(int(entry["size"]) for entry in document["files"]) + min_free_bytes
    free = shutil.disk_usage(target.parent if target.parent.exists() else package.parent).free
    if free < required:
        raise ValueError(f"insufficient free space: required={required} available={free}")
    return from_version, to_version


def validate_upgrade_policy(
        document: dict[str, Any], package: Path, target: Path,
        allow_initial_install: bool, allow_major_upgrade: bool,
        allow_development_release: bool, min_free_bytes: int) -> tuple[str | None, str]:
    from_version, to_version = validate_preflight(
        document, package, target, allow_initial_install, min_free_bytes
    )
    if from_version:
        major(from_version)
        if major(from_version) != major(to_version) and not allow_major_upgrade:
            raise ValueError("major-version upgrade requires --allow-major-upgrade")
        allowed_sources = document["compatibility"]["upgradeFrom"]
        if from_version != to_version and from_version not in allowed_sources:
            raise ValueError(
                f"compatibility matrix does not allow upgrade from {from_version} to {to_version}"
            )
    if (not allow_development_release and
            (document.get("cleanRequired") is not True or document.get("dirty") is not False)):
        raise ValueError(
            "release manifest is not production-governed; use --allow-development-release only for isolated validation"
        )
    return from_version, to_version


def preflight_upgrade(args: argparse.Namespace) -> int:
    package = args.package.resolve()
    target = args.target.resolve()
    manifest_path = args.manifest.resolve()
    report: dict[str, Any] = {
        "schemaVersion": 1,
        "verdict": "DENIED",
        "target": str(target),
    }
    try:
        validate_locations(package, target)
        signature_evidence = verify_trusted_manifest(manifest_path, args, package)
        trust_policy_evidence = validate_trust_policy(args, signature_evidence, package)
        if signature_evidence is not None:
            signature_evidence["trustPolicy"] = trust_policy_evidence
        document = validate_manifest(manifest_path, package)
        from_version, to_version = validate_upgrade_policy(
            document, package, target, args.allow_initial_install,
            args.allow_major_upgrade, args.allow_development_release,
            args.min_free_bytes,
        )
        report.update({
            "verdict": "APPROVED",
            "fromVersion": from_version,
            "toVersion": to_version,
            "manifestSha256": sha256(manifest_path),
            "files": len(document["files"]),
            "artifactBytes": sum(int(entry["size"]) for entry in document["files"]),
            "signature": {
                "verified": signature_evidence is not None,
                "keyId": signature_evidence["keyId"] if signature_evidence else None,
                "algorithm": signature_evidence["algorithm"] if signature_evidence else None,
                "publicKeySha256": signature_evidence["publicKeySha256"] if signature_evidence else None,
                "unsignedExplicitlyAllowed": signature_evidence is None,
            },
        })
        return_code = 0
    except (OSError, json.JSONDecodeError, ValueError) as error:
        report["error"] = str(error)
        return_code = 1
    if args.report:
        atomic_json(args.report.resolve(), report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return return_code


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


def healthy(
        target: Path, file_probe: str | None, url: str | None,
        body_pattern: str | None, command: str | None,
        command_arguments: list[str], timeout: float) -> bool:
    if command:
        expanded = [argument.replace("{target}", str(target)) for argument in command_arguments]
        try:
            result = subprocess.run(
                [command, *expanded], cwd=target, timeout=timeout,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, check=False,
            )
            return result.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if file_probe and (target / safe_relative(file_probe)).is_file():
            return True
        if url:
            try:
                with urllib.request.urlopen(url, timeout=min(2.0, timeout)) as response:
                    body = response.read(64 * 1024).decode("utf-8", errors="replace")
                    if (200 <= response.status < 300 and
                            (body_pattern is None or body_pattern in body)):
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


def rename_path(
        source: Path, destination: Path, timeout: float,
        evidence: list[dict[str, Any]], operation: str) -> None:
    if timeout <= 0:
        raise ValueError("--rename-timeout must be greater than zero")
    started = time.monotonic()
    deadline = started + timeout
    attempts = 0
    while True:
        attempts += 1
        try:
            source.rename(destination)
            evidence.append({
                "operation": operation,
                "attempts": attempts,
                "durationSeconds": round(time.monotonic() - started, 3),
            })
            return
        except OSError as error:
            transient = (
                isinstance(error, PermissionError) or
                getattr(error, "winerror", None) in {5, 32, 33} or
                error.errno in {errno.EACCES, errno.EBUSY, errno.EPERM}
            )
            if not transient or time.monotonic() >= deadline:
                evidence.append({
                    "operation": operation,
                    "attempts": attempts,
                    "durationSeconds": round(time.monotonic() - started, 3),
                    "error": str(error),
                })
                raise
            time.sleep(min(0.05 * attempts, 0.5, max(0.0, deadline - time.monotonic())))


def prune_backups(target: Path, keep: int) -> list[str]:
    if keep < 1:
        raise ValueError("--keep-backups must be at least 1")
    backups = sorted(
        (path for path in target.parent.glob(f".{target.name}.pdr-backup-*") if path.is_dir()),
        key=lambda path: path.stat().st_mtime_ns,
        reverse=True,
    )
    removed: list[str] = []
    for path in backups[keep:]:
        if is_link_like(path):
            raise OSError(f"refusing to remove linked backup path: {path}")
        remove_tree(path)
        removed.append(path.name)
    return removed


def apply_upgrade(args: argparse.Namespace) -> int:
    package = args.package.resolve()
    target = args.target.resolve()
    manifest_path = args.manifest.resolve()
    audit_path = args.audit.resolve()
    upgrade_id = str(uuid.uuid4())
    staging = target.parent / f".{target.name}.pdr-staging-{upgrade_id}"
    backup = target.parent / f".{target.name}.pdr-backup-{upgrade_id}"
    failed = target.parent / f".{target.name}.pdr-failed-{upgrade_id}"
    transaction_path, lock_path = transaction_paths(target)
    locked = False
    interrupted_present = False
    transaction: dict[str, Any] = {}
    rename_evidence: list[dict[str, Any]] = []
    try:
        if args.rename_timeout <= 0:
            raise ValueError("--rename-timeout must be greater than zero")
        validate_locations(package, target)
        try:
            audit_path.relative_to(target)
        except ValueError:
            pass
        else:
            raise ValueError("audit log must be outside the replaceable target directory")
        acquire_lock(lock_path, upgrade_id)
        locked = True
        if transaction_path.exists():
            interrupted_present = True
            raise ValueError(
                f"interrupted upgrade transaction exists: {transaction_path}; run recover first"
            )
        signature_evidence = verify_trusted_manifest(manifest_path, args, package)
        trust_policy_evidence = validate_trust_policy(args, signature_evidence, package)
        if signature_evidence is not None:
            signature_evidence["trustPolicy"] = trust_policy_evidence
        document = validate_manifest(manifest_path, package)
        from_version, to_version = validate_upgrade_policy(
            document, package, target, args.allow_initial_install,
            args.allow_major_upgrade, args.allow_development_release,
            args.min_free_bytes,
        )
        if args.health_timeout <= 0:
            raise ValueError("--health-timeout must be greater than zero")
        if args.keep_backups < 1:
            raise ValueError("--keep-backups must be at least 1")
        probes = sum(bool(value) for value in
                     (args.health_file, args.health_url, args.health_command))
        if probes > 1:
            raise ValueError("choose exactly one health probe")
        if args.skip_health_check and probes:
            raise ValueError("--skip-health-check cannot be combined with a health probe")
        if not args.skip_health_check and probes == 0:
            raise ValueError("a health probe is required; use --skip-health-check only for controlled diagnostics")
        if args.health_body_pattern and not args.health_url:
            raise ValueError("--health-body-pattern requires --health-url")
        if args.health_command_arg and not args.health_command:
            raise ValueError("--health-command-arg requires --health-command")
        if args.health_file and (package / safe_relative(args.health_file)).exists():
            raise ValueError(
                "health sentinel must be created after activation and must not be shipped in the package"
            )
        if args.health_url:
            parsed = urllib.parse.urlparse(args.health_url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise ValueError("health URL must be an absolute HTTP(S) URL")
            if parsed.scheme != "https" and parsed.hostname not in {"127.0.0.1", "::1", "localhost"}:
                raise ValueError("non-loopback health URL requires HTTPS")
        transaction = {
            "schemaVersion": TRANSACTION_SCHEMA_VERSION,
            "upgradeId": upgrade_id,
            "target": str(target),
            "staging": str(staging),
            "backup": str(backup),
            "failed": str(failed),
            "audit": str(audit_path),
            "fromVersion": from_version,
            "toVersion": to_version,
            "manifestSha256": sha256(manifest_path),
            "signature": signature_evidence,
            "unsignedExplicitlyAllowed": signature_evidence is None,
            "backupInventory": inventory(target),
            "createdAt": now(),
        }
        write_transaction(transaction_path, transaction, "preflight_passed")
        audit(audit_path, upgrade_id, "preflight_passed", fromVersion=from_version,
              toVersion=to_version, manifestSha256=transaction["manifestSha256"],
              signatureAlgorithm=(signature_evidence or {}).get("algorithm"),
              signatureKeyId=(signature_evidence or {}).get("keyId"),
              publicKeySha256=(signature_evidence or {}).get("publicKeySha256"),
              trustPolicy=(signature_evidence or {}).get("trustPolicy"),
              unsignedExplicitlyAllowed=signature_evidence is None)
        stage_files(document, package, staging)
        write_transaction(transaction_path, transaction, "staging_verified")
        audit(audit_path, upgrade_id, "staging_verified", files=len(document["files"]))
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            rename_path(target, backup, args.rename_timeout, rename_evidence, "target-to-backup")
        write_transaction(transaction_path, transaction, "backup_created")
        if backup.exists():
            verify_inventory(backup, transaction["backupInventory"])
            transaction["mutablePaths"] = transfer_mutable(backup, staging)
            write_transaction(transaction_path, transaction, "mutable_state_transferred")
        try:
            rename_path(staging, target, args.rename_timeout, rename_evidence, "staging-to-target")
        except Exception:
            if backup.exists() and not target.exists():
                rename_path(backup, target, args.rename_timeout, rename_evidence,
                            "activation-failure-restore")
            raise
        audit(audit_path, upgrade_id, "activated", backup=str(backup) if backup.exists() else None,
              renameEvidence=rename_evidence)
        write_transaction(transaction_path, transaction, "activated")
        if (not args.skip_health_check and
                not healthy(target, args.health_file, args.health_url,
                            args.health_body_pattern, args.health_command,
                            args.health_command_arg, args.health_timeout)):
            rename_path(target, failed, args.rename_timeout, rename_evidence,
                        "unhealthy-target-to-failed")
            if backup.exists():
                transfer_mutable(failed, backup)
                rename_path(backup, target, args.rename_timeout, rename_evidence,
                            "health-failure-restore")
                verify_inventory(target, transaction["backupInventory"])
            write_transaction(transaction_path, transaction, "health_failed_rollback_verified")
            audit(audit_path, upgrade_id, "health_failed_rollback", failedPath=str(failed),
                  rollbackVerified=bool(from_version), renameEvidence=rename_evidence)
            remove_tree(failed)
            transaction_path.unlink()
            release_lock(lock_path)
            locked = False
            return 2
        write_transaction(transaction_path, transaction, "health_passed")
        audit(audit_path, upgrade_id, "health_passed", version=to_version)
        try:
            removed_backups = prune_backups(target, args.keep_backups)
            audit(audit_path, upgrade_id, "backup_retention_applied",
                  keep=args.keep_backups, removed=removed_backups)
        except OSError as error:
            audit(audit_path, upgrade_id, "backup_retention_failed",
                  keep=args.keep_backups, error=str(error))
        transaction_path.unlink()
        release_lock(lock_path)
        locked = False
        print(f"UPGRADE_PASS id={upgrade_id} from={from_version} to={to_version} backup={backup if backup.exists() else 'none'}")
        return 0
    except Exception as error:
        audit(audit_path, upgrade_id, "upgrade_failed", error=str(error))
        # Before activation it is safe to remove staging. Once a rename has
        # started, retain all evidence for the explicit recover command.
        if interrupted_present:
            if locked:
                release_lock(lock_path)
                locked = False
        elif not transaction or transaction.get("state") in {"preflight_passed", "staging_verified"}:
            remove_tree(staging)
            if transaction_path.exists():
                transaction_path.unlink()
            if locked:
                release_lock(lock_path)
                locked = False
        print(f"UPGRADE_ERROR: {error}", file=sys.stderr)
        return 1


def rollback(args: argparse.Namespace) -> int:
    target = args.target.resolve()
    audit_path = args.audit.resolve()
    upgrade_id = str(uuid.uuid4())
    if args.rename_timeout <= 0:
        print("ROLLBACK_ERROR: --rename-timeout must be greater than zero", file=sys.stderr)
        return 1
    backups = sorted(target.parent.glob(f".{target.name}.pdr-backup-*"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not backups:
        print("ROLLBACK_ERROR: no backup is available", file=sys.stderr)
        return 1
    transaction_path, lock_path = transaction_paths(target)
    if transaction_path.exists() or lock_path.exists():
        print("ROLLBACK_ERROR: interrupted upgrade exists; run recover first", file=sys.stderr)
        return 1
    backup = backups[0]
    if is_link_like(backup):
        print("ROLLBACK_ERROR: latest backup is a link or reparse point", file=sys.stderr)
        return 1
    displaced = target.parent / f".{target.name}.pdr-displaced-{upgrade_id}"
    expected = inventory(backup)
    rename_evidence: list[dict[str, Any]] = []
    try:
        if target.exists():
            transfer_mutable(target, backup)
        if target.exists():
            rename_path(target, displaced, args.rename_timeout, rename_evidence,
                        "target-to-displaced")
        rename_path(backup, target, args.rename_timeout, rename_evidence,
                    "backup-to-target")
        verify_inventory(target, expected)
        audit(audit_path, upgrade_id, "manual_rollback",
              restoredVersion=deployed_version(target), rollbackVerified=True,
              renameEvidence=rename_evidence)
        remove_tree(displaced)
        print(f"ROLLBACK_PASS id={upgrade_id} version={deployed_version(target)}")
        return 0
    except Exception as error:
        if displaced.exists():
            if target.exists():
                transfer_mutable(target, displaced)
                if backup.exists():
                    raise RuntimeError("rollback reconciliation found both target and backup") from error
                rename_path(target, backup, args.rename_timeout, rename_evidence,
                            "rollback-failure-preserve-backup")
            elif backup.exists():
                transfer_mutable(backup, displaced)
            rename_path(displaced, target, args.rename_timeout, rename_evidence,
                        "rollback-failure-restore-active")
        elif target.exists() and backup.exists():
            transfer_mutable(backup, target)
        audit(audit_path, upgrade_id, "rollback_failed", error=str(error),
              renameEvidence=rename_evidence)
        print(f"ROLLBACK_ERROR: {error}", file=sys.stderr)
        return 1


def recover(args: argparse.Namespace) -> int:
    target = args.target.resolve()
    transaction_path, lock_path = transaction_paths(target)
    if args.rename_timeout <= 0:
        print("RECOVER_ERROR: --rename-timeout must be greater than zero", file=sys.stderr)
        return 1
    if not transaction_path.is_file():
        print("RECOVER_ERROR: no interrupted upgrade transaction is available", file=sys.stderr)
        return 1
    audit_path: Path | None = None
    upgrade_id = "unknown"
    rename_evidence: list[dict[str, Any]] = []
    try:
        transaction = json.loads(transaction_path.read_text(encoding="utf-8"))
        if (transaction.get("schemaVersion") != TRANSACTION_SCHEMA_VERSION or
                Path(str(transaction.get("target", ""))).resolve() != target):
            raise ValueError("invalid upgrade transaction journal")
        upgrade_id = str(transaction["upgradeId"])
        staging = Path(transaction["staging"])
        backup = Path(transaction["backup"])
        failed = Path(transaction["failed"])
        audit_path = Path(transaction["audit"])
        expected_paths = {
            "staging": target.parent / f".{target.name}.pdr-staging-{upgrade_id}",
            "backup": target.parent / f".{target.name}.pdr-backup-{upgrade_id}",
            "failed": target.parent / f".{target.name}.pdr-failed-{upgrade_id}",
        }
        actual_paths = {"staging": staging, "backup": backup, "failed": failed}
        for name, expected_path in expected_paths.items():
            if actual_paths[name].resolve() != expected_path.resolve():
                raise ValueError(f"transaction {name} path is outside its governed location")
        try:
            audit_path.resolve().relative_to(target)
        except ValueError:
            pass
        else:
            raise ValueError("transaction audit path is inside the replaceable target")
        expected = transaction.get("backupInventory", [])
        if not isinstance(expected, list):
            raise ValueError("transaction backup inventory is invalid")

        # Recovery is deliberately fail-closed: if activation may have begun,
        # restore the verified old release instead of guessing that the new
        # release passed its health gate.
        if backup.exists():
            verify_inventory(backup, expected)
            if target.exists():
                transfer_mutable(target, backup)
                if failed.exists():
                    raise ValueError(f"recovery evidence path already exists: {failed}")
                rename_path(target, failed, args.rename_timeout, rename_evidence,
                            "recovery-target-to-failed")
            elif failed.exists():
                transfer_mutable(failed, backup)
            elif staging.exists():
                transfer_mutable(staging, backup)
            rename_path(backup, target, args.rename_timeout, rename_evidence,
                        "recovery-backup-to-target")
            verify_inventory(target, expected)
            remove_tree(failed)
            outcome = "old_release_restored"
        elif target.exists() and transaction.get("fromVersion") is None:
            # An interrupted explicitly authorized initial install has no old
            # release to restore. Remove it rather than approving an unprobed
            # installation.
            rename_path(target, failed, args.rename_timeout, rename_evidence,
                        "recovery-initial-install-to-failed")
            remove_tree(failed)
            outcome = "unverified_initial_install_removed"
        elif target.exists() and transaction.get("state") in {"preflight_passed", "staging_verified"}:
            verify_inventory(target, expected)
            outcome = "original_release_unchanged"
        elif (target.exists() and staging.exists() and
              transaction.get("state") == "backup_created"):
            verify_inventory(target, expected)
            outcome = "original_release_unchanged"
        elif (target.exists() and transaction.get("state") ==
              "health_failed_rollback_verified"):
            verify_inventory(target, expected)
            remove_tree(failed)
            outcome = "verified_automatic_rollback_retained"
        else:
            raise ValueError("cannot reconcile transaction paths safely")
        remove_tree(staging)
        audit(audit_path, upgrade_id, "interrupted_upgrade_recovered",
              outcome=outcome, restoredVersion=deployed_version(target),
              renameEvidence=rename_evidence)
        transaction_path.unlink()
        release_lock(lock_path)
        print(f"RECOVER_PASS id={upgrade_id} outcome={outcome} version={deployed_version(target)}")
        return 0
    except Exception as error:
        if audit_path is not None and upgrade_id != "unknown":
            try:
                audit(audit_path, upgrade_id, "interrupted_upgrade_recovery_failed",
                      error=str(error), renameEvidence=rename_evidence)
            except OSError:
                pass
        print(f"RECOVER_ERROR: {error}", file=sys.stderr)
        return 1
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    preflight = commands.add_parser("preflight")
    preflight.add_argument("--package", type=Path, required=True)
    preflight.add_argument("--manifest", type=Path, required=True)
    preflight.add_argument("--target", type=Path, required=True)
    preflight.add_argument("--report", type=Path)
    preflight.add_argument("--signature", type=Path)
    preflight.add_argument("--trusted-key-environment")
    preflight.add_argument("--expected-key-id")
    preflight.add_argument("--public-key", type=Path)
    preflight.add_argument("--expected-public-key-sha256")
    preflight.add_argument("--signature-check-executable", type=Path)
    preflight.add_argument("--allow-unsigned-release", action="store_true")
    preflight.add_argument("--trust-policy", type=Path)
    preflight.add_argument("--expected-trust-policy-id")
    preflight.add_argument("--expected-trust-policy-sha256")
    preflight.add_argument("--allow-unmanaged-trust", action="store_true")
    preflight.add_argument("--min-free-bytes", type=int, default=64 * 1024 * 1024)
    preflight.add_argument("--allow-initial-install", action="store_true")
    preflight.add_argument("--allow-major-upgrade", action="store_true")
    preflight.add_argument("--allow-development-release", action="store_true")
    preflight.set_defaults(handler=preflight_upgrade)
    apply = commands.add_parser("apply")
    apply.add_argument("--package", type=Path, required=True)
    apply.add_argument("--manifest", type=Path, required=True)
    apply.add_argument("--target", type=Path, required=True)
    apply.add_argument("--audit", type=Path, required=True)
    apply.add_argument("--signature", type=Path)
    apply.add_argument("--trusted-key-environment")
    apply.add_argument("--expected-key-id")
    apply.add_argument("--public-key", type=Path)
    apply.add_argument("--expected-public-key-sha256")
    apply.add_argument("--signature-check-executable", type=Path)
    apply.add_argument("--allow-unsigned-release", action="store_true")
    apply.add_argument("--trust-policy", type=Path)
    apply.add_argument("--expected-trust-policy-id")
    apply.add_argument("--expected-trust-policy-sha256")
    apply.add_argument("--allow-unmanaged-trust", action="store_true")
    apply.add_argument("--health-file")
    apply.add_argument("--health-url")
    apply.add_argument("--health-body-pattern")
    apply.add_argument("--health-command")
    apply.add_argument("--health-command-arg", action="append", default=[])
    apply.add_argument("--health-timeout", type=float, default=30.0)
    apply.add_argument("--skip-health-check", action="store_true")
    apply.add_argument("--min-free-bytes", type=int, default=64 * 1024 * 1024)
    apply.add_argument("--keep-backups", type=int, default=2)
    apply.add_argument("--rename-timeout", type=float, default=5.0)
    apply.add_argument("--allow-initial-install", action="store_true")
    apply.add_argument("--allow-major-upgrade", action="store_true")
    apply.add_argument("--allow-development-release", action="store_true")
    apply.set_defaults(handler=apply_upgrade)
    restore = commands.add_parser("rollback")
    restore.add_argument("--target", type=Path, required=True)
    restore.add_argument("--audit", type=Path, required=True)
    restore.add_argument("--rename-timeout", type=float, default=5.0)
    restore.set_defaults(handler=rollback)
    resume = commands.add_parser("recover")
    resume.add_argument("--target", type=Path, required=True)
    resume.add_argument("--rename-timeout", type=float, default=5.0)
    resume.set_defaults(handler=recover)
    args = parser.parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
