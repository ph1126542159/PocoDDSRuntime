#!/usr/bin/env python3
"""Verify and transactionally publish stopped-Runtime PocoDDS plugins."""

from __future__ import annotations

import argparse
import base64
import fnmatch
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any

MAX_ARCHIVE_BYTES = 128 * 1024 * 1024
MAX_EXPANDED_BYTES = 512 * 1024 * 1024
MAX_FILES = 4096
CONTRACT_FILE = "pdr-plugin-runtime.json"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".new")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(document, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def append_audit(path: Path, event: str, transaction_id: str, **fields: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"timestamp": now(), "transactionId": transaction_id,
              "event": event, **fields}
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def parse_manifest(content: bytes) -> dict[str, str]:
    text = content.decode("utf-8", errors="strict")
    unfolded: list[str] = []
    for line in text.splitlines():
        if line.startswith(" ") and unfolded:
            previous = unfolded[-1].rstrip()
            if previous.endswith("\\"):
                previous = previous[:-1].rstrip()
            unfolded[-1] = previous + " " + line[1:].lstrip()
        else:
            unfolded.append(line)
    result: dict[str, str] = {}
    for line in unfolded:
        key, separator, value = line.partition(":")
        if separator:
            result[key.strip()] = value.strip()
    return result


def split_dependencies(value: str) -> list[str]:
    items: list[str] = []
    start = 0
    depth = 0
    for index, character in enumerate(value):
        if character in "[(":
            depth += 1
        elif character in "])" and depth:
            depth -= 1
        elif character == "," and depth == 0:
            items.append(value[start:index].strip())
            start = index + 1
    if value[start:].strip():
        items.append(value[start:].strip())
    return items


def version_tuple(value: str) -> tuple[int, ...]:
    match = re.fullmatch(r"[vV]?(\d+(?:\.\d+){0,3})(?:[-+].*)?", value.strip())
    if not match:
        raise ValueError(f"unsupported Bundle version: {value}")
    parts = tuple(int(part) for part in match.group(1).split("."))
    return parts + (0,) * (4 - len(parts))


def version_matches(version: str, requested: str) -> bool:
    requested = requested.strip()
    if not requested or requested == "*":
        return True
    current = version_tuple(version)
    if requested[0] in "[(" and requested[-1] in ")]" and "," in requested:
        lower, upper = (part.strip() for part in requested[1:-1].split(",", 1))
        lower_ok = not lower or current > version_tuple(lower) or (
            current == version_tuple(lower) and requested[0] == "[")
        upper_ok = not upper or current < version_tuple(upper) or (
            current == version_tuple(upper) and requested[-1] == "]")
        return lower_ok and upper_ok
    return current == version_tuple(requested)


def inspect_bundle(path: Path, require_plugin: bool = True) -> dict[str, Any]:
    path = path.resolve()
    if not path.is_file() or path.suffix.lower() != ".bndl":
        raise ValueError("plugin artifact must be an existing .bndl file")
    if path.is_symlink() or path.stat().st_size > MAX_ARCHIVE_BYTES:
        raise ValueError("plugin artifact is a link or exceeds the archive size limit")
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        if not entries or len(entries) > MAX_FILES:
            raise ValueError("plugin archive has an invalid file count")
        names: set[str] = set()
        expanded = 0
        for entry in entries:
            normalized = PurePosixPath(entry.filename.replace("\\", "/"))
            normalized_name = normalized.as_posix()
            is_link = ((entry.external_attr >> 16) & 0o170000) == 0o120000
            if (normalized.is_absolute() or ".." in normalized.parts or is_link or
                    not normalized.parts or normalized_name in names):
                raise ValueError(f"unsafe or duplicate plugin archive entry: {entry.filename}")
            names.add(normalized_name)
            expanded += entry.file_size
            if expanded > MAX_EXPANDED_BYTES:
                raise ValueError("plugin archive exceeds the expanded size limit")
        manifests = [entry for entry in entries if entry.filename == "META-INF/manifest.mf"]
        if len(manifests) != 1:
            raise ValueError("plugin archive must contain exactly one META-INF/manifest.mf")
        manifest = parse_manifest(archive.read(manifests[0]))
    symbolic = manifest.get("Bundle-SymbolicName", "")
    version = manifest.get("Bundle-Version", "")
    if not symbolic or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", symbolic):
        raise ValueError("Bundle manifest contains an invalid symbolic name")
    if require_plugin and not re.fullmatch(r"pdr\.plugin\.[a-z0-9][a-z0-9._-]*", symbolic):
        raise ValueError("only pdr.plugin.* Bundle symbolic names can use plugin transactions")
    version_tuple(version)
    canonical = f"{symbolic}_{version}.bndl"
    dependencies: list[dict[str, str]] = []
    for item in split_dependencies(manifest.get("Require-Bundle", "")):
        parts = [part.strip() for part in item.split(";") if part.strip()]
        if not parts:
            continue
        requested = "*"
        for parameter in parts[1:]:
            if parameter.startswith("bundle-version="):
                requested = parameter.split("=", 1)[1].strip().strip('"')
        dependencies.append({"id": parts[0], "requestedVersion": requested})
    return {
        "path": str(path), "fileName": path.name, "canonicalFileName": canonical,
        "size": path.stat().st_size, "sha256": sha256(path),
        "symbolicName": symbolic, "version": version, "dependencies": dependencies,
        "entryCount": len(entries), "expandedBytes": expanded,
        "pluginContract": {
            "apiVersion": manifest.get("PDR-Plugin-API", ""),
            "abiVersion": manifest.get("PDR-Plugin-ABI", ""),
            "abiFingerprint": manifest.get("PDR-Plugin-ABI-Fingerprint", ""),
            "runtimeVersionRange": manifest.get("PDR-Runtime-Version", ""),
        },
    }


def inventory(directory: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    if not directory.is_dir():
        return result
    for artifact in sorted(directory.glob("*.bndl")):
        try:
            info = inspect_bundle(artifact, require_plugin=False)
        except (OSError, UnicodeError, ValueError, zipfile.BadZipFile) as error:
            raise ValueError(f"cannot inventory installed Bundle {artifact.name}: {error}") from error
        symbolic = str(info["symbolicName"])
        if symbolic in result:
            raise ValueError(f"runtime contains duplicate Bundle symbolic name: {symbolic}")
        result[symbolic] = info
    return result


def load_runtime_contract(bundles: Path, explicit: Path | None = None) -> dict[str, Any]:
    path = (explicit or bundles.resolve().parent / CONTRACT_FILE).resolve()
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"runtime plugin contract is missing or unsafe: {path}")
    document = json.loads(path.read_text(encoding="utf-8"))
    required = ("runtimeVersion", "pluginApiVersion", "pluginAbiVersion",
                "abiFingerprint", "targetOs", "targetArch", "compilerId",
                "compilerMajor")
    if (not isinstance(document, dict) or document.get("schemaVersion") != 1 or
            any(not isinstance(document.get(key), str) or not document[key]
                for key in required)):
        raise ValueError("runtime plugin contract is malformed or incomplete")
    version_tuple(document["runtimeVersion"])
    version_tuple(document["pluginApiVersion"])
    version_tuple(document["pluginAbiVersion"])
    return {**document, "path": str(path), "sha256": sha256(path)}


def policy_time(value: Any, field: str) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"plugin trust policy {field} must be an ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"plugin trust policy {field} is invalid") from error
    if parsed.tzinfo is None:
        raise ValueError(f"plugin trust policy {field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def sign_plugin(args: argparse.Namespace) -> int:
    try:
        info = inspect_bundle(args.artifact.resolve())
        if (not args.publisher_id or any(character.isspace() for character in args.publisher_id) or
                not args.key_id or any(character.isspace() for character in args.key_id)):
            raise ValueError("publisher id and key id must be non-empty and contain no whitespace")
        key_path_value = os.environ.get(args.private_key_path_environment)
        if not key_path_value:
            raise ValueError("plugin private key path environment is unset")
        passphrase = None
        if args.private_key_passphrase_environment:
            value = os.environ.get(args.private_key_passphrase_environment)
            if value is None:
                raise ValueError("plugin private key passphrase environment is unset")
            passphrase = value.encode("utf-8")
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
            from cryptography.hazmat.primitives.serialization import load_pem_private_key
        except ImportError as error:
            raise ValueError("Ed25519 signing requires the release-host cryptography package") from error
        key = load_pem_private_key(Path(key_path_value).read_bytes(), password=passphrase)
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError("plugin private key is not Ed25519")
        attestation = {
            "schemaVersion": 1, "product": "PocoDDSRuntimePlugin",
            "publisherId": args.publisher_id, "issuedAt": now(),
            "artifact": {
                "symbolicName": info["symbolicName"], "version": info["version"],
                "size": info["size"], "sha256": info["sha256"],
                "pluginContract": info["pluginContract"],
            },
        }
        atomic_json(args.attestation.resolve(), attestation)
        content = args.attestation.resolve().read_bytes()
        signature = {
            "schemaVersion": 1, "product": "PocoDDSRuntimePlugin",
            "algorithm": "Ed25519", "keyId": args.key_id,
            "manifestSha256": hashlib.sha256(content).hexdigest(),
            "signature": base64.b64encode(key.sign(content)).decode("ascii"),
        }
        atomic_json(args.signature.resolve(), signature)
        print(f"PLUGIN_SIGN_PASS publisher={args.publisher_id} keyId={args.key_id}")
        return 0
    except (OSError, UnicodeError, ValueError, zipfile.BadZipFile) as error:
        print(f"PLUGIN_SIGN_ERROR: {error}", file=sys.stderr)
        return 1


def verify_plugin_provenance(info: dict[str, Any], args: argparse.Namespace | None) -> dict[str, Any]:
    if args is None:
        return {"verified": False, "diagnosticBypass": True, "reason": "library-call"}
    if getattr(args, "allow_unsigned_plugin", False):
        return {"verified": False, "diagnosticBypass": True, "reason": "explicit-authorization"}
    required = ("attestation", "signature", "public_key", "trust_policy",
                "expected_trust_policy_id", "expected_trust_policy_sha256")
    if any(not getattr(args, name, None) for name in required):
        raise ValueError("signed plugin requires attestation, signature, public key and pinned trust policy")
    attestation_path = args.attestation.resolve()
    signature_path = args.signature.resolve()
    public_key = args.public_key.resolve()
    policy_path = args.trust_policy.resolve()
    actual_policy_digest = sha256(policy_path)
    if actual_policy_digest != args.expected_trust_policy_sha256.lower():
        raise ValueError("plugin trust policy SHA-256 is not trusted")
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    if (policy.get("schemaVersion") != 1 or policy.get("product") != "PocoDDSRuntimePlugin" or
            policy.get("policyId") != args.expected_trust_policy_id):
        raise ValueError("unsupported or unexpected plugin trust policy")
    attestation = json.loads(attestation_path.read_text(encoding="utf-8"))
    if attestation.get("schemaVersion") != 1 or attestation.get("product") != "PocoDDSRuntimePlugin":
        raise ValueError("unsupported plugin attestation")
    artifact = attestation.get("artifact")
    expected_artifact = {
        "symbolicName": info["symbolicName"], "version": info["version"],
        "size": info["size"], "sha256": info["sha256"],
        "pluginContract": info["pluginContract"],
    }
    if artifact != expected_artifact:
        raise ValueError("plugin attestation does not match the artifact")
    issued_at = policy_time(attestation.get("issuedAt"), "issuedAt")
    current = datetime.now(timezone.utc)
    if issued_at is None or issued_at > current + timedelta(minutes=5):
        raise ValueError("plugin attestation issue time is invalid or in the future")
    signature = json.loads(signature_path.read_text(encoding="utf-8"))
    if (signature.get("schemaVersion") != 1 or signature.get("product") != "PocoDDSRuntimePlugin" or
            signature.get("algorithm") != "Ed25519" or not isinstance(signature.get("keyId"), str)):
        raise ValueError("unsupported plugin signature envelope")
    key_id = signature["keyId"]
    revoked = policy.get("revokedKeys", [])
    if not isinstance(revoked, list):
        raise ValueError("plugin trust policy revocation list is malformed")
    for entry in revoked:
        if not isinstance(entry, dict) or not entry.get("keyId") or not entry.get("reason"):
            raise ValueError("plugin trust policy revocation entry is malformed")
        policy_time(entry.get("revokedAt"), "revokedAt")
        if entry["keyId"] == key_id:
            raise ValueError(f"plugin signing key is revoked: {key_id}: {entry['reason']}")
    publisher_id = attestation.get("publisherId")
    allowed = policy.get("allowedPublishers")
    if not isinstance(allowed, list):
        raise ValueError("plugin trust policy publisher list is malformed")
    matches = [entry for entry in allowed if isinstance(entry, dict) and
               entry.get("publisherId") == publisher_id and entry.get("keyId") == key_id]
    if len(matches) != 1:
        raise ValueError("plugin publisher and signing key are not uniquely allowed")
    publisher = matches[0]
    patterns = publisher.get("pluginPatterns")
    if (publisher.get("algorithm") != "Ed25519" or not isinstance(patterns, list) or
            not patterns or any(not isinstance(pattern, str) or
                not pattern.startswith("pdr.plugin.") or pattern.count("*") > 1 or
                ("*" in pattern and not pattern.endswith("*")) for pattern in patterns)):
        raise ValueError("plugin publisher policy entry is malformed")
    if not any(fnmatch.fnmatchcase(info["symbolicName"], pattern) for pattern in patterns):
        raise ValueError("plugin publisher is not allowed for this symbolic name")
    public_key_digest = sha256(public_key)
    if publisher.get("publicKeySha256") != public_key_digest:
        raise ValueError("plugin public key is not allowed by trust policy")
    not_before = policy_time(publisher.get("notBefore"), "notBefore")
    not_after = policy_time(publisher.get("notAfter"), "notAfter")
    if not_before and not_after and not_before >= not_after:
        raise ValueError("plugin publisher validity window is invalid")
    if not_before and (current < not_before or issued_at < not_before):
        raise ValueError("plugin publisher key is not active yet")
    if not_after and (current >= not_after or issued_at >= not_after):
        raise ValueError("plugin publisher key has expired")
    verifier = getattr(args, "signature_check_executable", None) or Path(__file__).resolve().with_name(
        "pdr-signature-check.exe" if os.name == "nt" else "pdr-signature-check")
    verifier = Path(verifier).resolve()
    if not verifier.is_file():
        raise ValueError(f"plugin signature verifier is unavailable: {verifier}")
    result = subprocess.run(
        [str(verifier), str(attestation_path), str(signature_path), str(public_key),
         key_id, "PocoDDSRuntimePlugin"], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise ValueError((result.stderr or result.stdout).strip() or "plugin signature verification failed")
    return {"verified": True, "diagnosticBypass": False, "publisherId": publisher_id,
            "keyId": key_id, "algorithm": "Ed25519", "publicKeySha256": public_key_digest,
            "policyId": policy["policyId"], "policySha256": actual_policy_digest,
            "attestationSha256": sha256(attestation_path)}


def preflight(artifact: Path, bundles: Path, expected_sha256: str | None,
              runtime_contract: Path | None = None,
              provenance_args: argparse.Namespace | None = None) -> dict[str, Any]:
    info = inspect_bundle(artifact)
    if expected_sha256:
        normalized = expected_sha256.lower()
        if not re.fullmatch(r"[0-9a-f]{64}", normalized):
            raise ValueError("expected SHA-256 must contain exactly 64 hexadecimal characters")
        if info["sha256"] != normalized:
            raise ValueError("plugin artifact SHA-256 does not match the approved digest")
    contract = load_runtime_contract(bundles, runtime_contract)
    provenance = verify_plugin_provenance(info, provenance_args)
    declared = info["pluginContract"]
    contract_checks = [
        {"name": "pluginApiVersion", "requested": declared["apiVersion"],
         "available": contract["pluginApiVersion"],
         "compatible": declared["apiVersion"] == contract["pluginApiVersion"]},
        {"name": "pluginAbiVersion", "requested": declared["abiVersion"],
         "available": contract["pluginAbiVersion"],
         "compatible": declared["abiVersion"] == contract["pluginAbiVersion"]},
        {"name": "abiFingerprint", "requested": declared["abiFingerprint"],
         "available": contract["abiFingerprint"],
         "compatible": declared["abiFingerprint"] == contract["abiFingerprint"]},
        {"name": "runtimeVersion", "requested": declared["runtimeVersionRange"],
         "available": contract["runtimeVersion"],
         "compatible": bool(declared["runtimeVersionRange"]) and version_matches(
             contract["runtimeVersion"], declared["runtimeVersionRange"])},
    ]
    installed = inventory(bundles)
    candidate_inventory = dict(installed)
    candidate_inventory[str(info["symbolicName"])] = info
    checks: list[dict[str, Any]] = []
    compatible = all(check["compatible"] for check in contract_checks)
    for dependency in info["dependencies"]:
        available = candidate_inventory.get(dependency["id"])
        matched = bool(available) and version_matches(
            str(available["version"]), dependency["requestedVersion"])
        checks.append({**dependency, "available": bool(available),
                       "availableVersion": str(available["version"]) if available else "",
                       "compatible": matched})
        compatible = compatible and matched
    current = installed.get(str(info["symbolicName"]))
    return {"schemaVersion": 1, "operation": "plugin-preflight", "passed": compatible,
            "checkedAt": now(), "artifact": info, "dependencies": checks,
            "pluginCompatibility": contract_checks, "runtimeContract": contract,
            "provenance": provenance,
            "current": current, "bundleDirectory": str(bundles.resolve())}


def resolved_directory(value: Path, name: str) -> Path:
    path = value.resolve()
    if value.is_symlink() or (path.exists() and not path.is_dir()):
        raise ValueError(f"{name} must be a real directory, not a link")
    path.mkdir(parents=True, exist_ok=True)
    return path


def acquire_lock(path: Path, transaction_id: str) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
        json.dump({"transactionId": transaction_id, "pid": os.getpid(), "createdAt": now()}, stream)
        stream.flush()
        os.fsync(stream.fileno())


def install_plugin(args: argparse.Namespace) -> int:
    transaction_id = str(uuid.uuid4())
    bundles = resolved_directory(args.bundle_directory, "bundle directory")
    backups = resolved_directory(args.backup_directory or bundles.parent / "plugin-backups",
                                 "backup directory")
    lock = bundles.parent / ".pdr-plugin.lock"
    journal = bundles.parent / ".pdr-plugin-transaction.json"
    audit_path = args.audit or bundles.parent / "plugin-transactions.audit.jsonl"
    report: dict[str, Any] = {"schemaVersion": 1, "operation": "plugin-install",
                              "transactionId": transaction_id, "startedAt": now(), "passed": False}
    stage: Path | None = None
    backup_artifact: Path | None = None
    published: Path | None = None
    lock_acquired = False
    try:
        if not args.confirm_runtime_stopped:
            raise ValueError("refusing plugin installation without --confirm-runtime-stopped")
        if journal.exists():
            raise ValueError("an interrupted plugin transaction exists; inspect it before retrying")
        acquire_lock(lock, transaction_id)
        lock_acquired = True
        evidence = preflight(args.artifact.resolve(), bundles, args.expected_sha256,
                             getattr(args, "runtime_contract", None), args)
        report["preflight"] = evidence
        if not evidence["passed"]:
            raise ValueError("plugin dependency preflight failed")
        info = evidence["artifact"]
        current = evidence["current"]
        published = bundles / info["canonicalFileName"]
        stage = bundles / f".{info['canonicalFileName']}.staging-{transaction_id}"
        transaction = {"schemaVersion": 1, "transactionId": transaction_id,
                       "operation": "install", "state": "staging",
                       "symbolicName": info["symbolicName"],
                       "artifactSha256": info["sha256"], "target": str(published),
                       "stage": str(stage), "backup": None,
                       "previousTarget": current["path"] if current else None,
                       "startedAt": report["startedAt"]}
        atomic_json(journal, transaction)
        shutil.copyfile(args.artifact.resolve(), stage)
        if sha256(stage) != info["sha256"]:
            raise OSError("staged plugin digest changed during copy")
        if current:
            current_path = Path(current["path"])
            backup_root = backups / info["symbolicName"] / transaction_id
            backup_root.mkdir(parents=True, exist_ok=False)
            backup_artifact = backup_root / current_path.name
            os.replace(current_path, backup_artifact)
            transaction.update({"state": "backup-created", "backup": str(backup_artifact),
                                "backupSha256": current["sha256"]})
            atomic_json(journal, transaction)
        os.replace(stage, published)
        if sha256(published) != info["sha256"]:
            raise OSError("published plugin digest does not match staged artifact")
        transaction["state"] = "committed"
        atomic_json(journal, transaction)
        report.update({"passed": True, "finishedAt": now(), "published": str(published),
                       "backup": str(backup_artifact) if backup_artifact else None,
                       "artifact": info})
        append_audit(audit_path, "plugin_install_committed", transaction_id,
                     symbolicName=info["symbolicName"], version=info["version"],
                     sha256=info["sha256"], backup=report["backup"],
                     publisherId=evidence["provenance"].get("publisherId"),
                     signingKeyId=evidence["provenance"].get("keyId"),
                     trustPolicyId=evidence["provenance"].get("policyId"),
                     unsignedDiagnosticBypass=evidence["provenance"].get(
                         "diagnosticBypass", False))
        journal.unlink()
        print(f"PLUGIN_INSTALL_PASS id={transaction_id} artifact={published}")
        return 0
    except (OSError, UnicodeError, ValueError, zipfile.BadZipFile) as error:
        rollback_verified = False
        try:
            if backup_artifact and backup_artifact.exists():
                if published and published.exists():
                    failed = backups / "failed" / transaction_id / published.name
                    failed.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(published, failed)
                original = bundles / backup_artifact.name
                os.replace(backup_artifact, original)
                rollback_verified = original.exists()
            elif published and published.exists():
                failed = backups / "failed" / transaction_id / published.name
                failed.parent.mkdir(parents=True, exist_ok=True)
                os.replace(published, failed)
                rollback_verified = not published.exists()
        except OSError as rollback_error:
            report["rollbackError"] = str(rollback_error)
        report.update({"error": str(error), "rollbackVerified": rollback_verified,
                       "finishedAt": now()})
        append_audit(audit_path, "plugin_install_failed", transaction_id,
                     error=str(error), rollbackVerified=rollback_verified)
        if (rollback_verified or not journal.exists() or
                (backup_artifact is None and (published is None or not published.exists()))):
            journal.unlink(missing_ok=True)
        print(f"PLUGIN_INSTALL_ERROR: {error}", file=sys.stderr)
        return 1
    finally:
        if stage and stage.exists():
            stage.unlink()
        if args.report:
            atomic_json(args.report.resolve(), report)
        if lock_acquired:
            lock.unlink(missing_ok=True)


def rollback_plugin(args: argparse.Namespace) -> int:
    transaction_id = str(uuid.uuid4())
    bundles = resolved_directory(args.bundle_directory, "bundle directory")
    backups = resolved_directory(args.backup_directory or bundles.parent / "plugin-backups",
                                 "backup directory")
    lock = bundles.parent / ".pdr-plugin.lock"
    journal = bundles.parent / ".pdr-plugin-transaction.json"
    audit_path = args.audit or bundles.parent / "plugin-transactions.audit.jsonl"
    report: dict[str, Any] = {"schemaVersion": 1, "operation": "plugin-rollback",
                              "passed": False, "transactionId": transaction_id,
                              "startedAt": now(), "symbolicName": args.symbolic_name}
    displaced: Path | None = None
    restored: Path | None = None
    current_path: Path | None = None
    backup: Path | None = None
    lock_acquired = False
    if not args.confirm_runtime_stopped:
        print("PLUGIN_ROLLBACK_ERROR: --confirm-runtime-stopped is required", file=sys.stderr)
        return 1
    candidates = sorted((backups / args.symbolic_name).glob("*/*.bndl"),
                        key=lambda item: item.stat().st_mtime_ns, reverse=True)
    if not candidates:
        print("PLUGIN_ROLLBACK_ERROR: no plugin backup is available", file=sys.stderr)
        return 1
    backup = candidates[0]
    try:
        if journal.exists():
            raise ValueError("an interrupted plugin transaction exists; inspect it before retrying")
        acquire_lock(lock, transaction_id)
        lock_acquired = True
        backup_info = inspect_bundle(backup)
        if backup_info["symbolicName"] != args.symbolic_name:
            raise ValueError("backup symbolic name does not match rollback target")
        if backup_info["sha256"] != args.expected_backup_sha256.lower():
            raise ValueError("backup SHA-256 does not match the approved digest")
        current_items = [item for item in inventory(bundles).values()
                         if item["symbolicName"] == args.symbolic_name]
        if len(current_items) != 1:
            raise ValueError("rollback requires exactly one currently installed plugin")
        current = current_items[0]
        if current["sha256"] != args.expected_current_sha256.lower():
            raise ValueError("current plugin SHA-256 does not match the approved digest")
        current_path = Path(current["path"])
        displaced = backups / args.symbolic_name / transaction_id / Path(current["path"]).name
        displaced.parent.mkdir(parents=True, exist_ok=False)
        atomic_json(journal, {"schemaVersion": 1, "transactionId": transaction_id,
                              "operation": "rollback", "state": "prepared",
                              "current": str(current_path), "backup": str(backup),
                              "displaced": str(displaced), "startedAt": report["startedAt"]})
        os.replace(current_path, displaced)
        atomic_json(journal, {"schemaVersion": 1, "transactionId": transaction_id,
                              "operation": "rollback", "state": "current-displaced",
                              "current": str(current_path), "backup": str(backup),
                              "displaced": str(displaced), "startedAt": report["startedAt"]})
        restored = bundles / backup_info["canonicalFileName"]
        os.replace(backup, restored)
        if sha256(restored) != backup_info["sha256"]:
            raise OSError("restored plugin digest verification failed")
        report.update({"passed": True, "finishedAt": now(), "restored": str(restored),
                       "restoredSha256": backup_info["sha256"],
                       "displaced": str(displaced)})
        append_audit(audit_path, "plugin_rollback_committed", transaction_id,
                     symbolicName=args.symbolic_name, restored=str(restored),
                     restoredSha256=backup_info["sha256"], displaced=str(displaced))
        if args.report:
            atomic_json(args.report.resolve(), report)
        journal.unlink()
        print(f"PLUGIN_ROLLBACK_PASS id={transaction_id} artifact={restored}")
        return 0
    except (OSError, UnicodeError, ValueError, zipfile.BadZipFile) as error:
        rollback_verified = False
        try:
            if restored and restored.exists() and backup:
                backup.parent.mkdir(parents=True, exist_ok=True)
                os.replace(restored, backup)
            if displaced and displaced.exists() and current_path:
                os.replace(displaced, current_path)
                rollback_verified = current_path.exists()
        except OSError as recovery_error:
            report["recoveryError"] = str(recovery_error)
        report.update({"error": str(error), "rollbackVerified": rollback_verified,
                       "finishedAt": now()})
        append_audit(audit_path, "plugin_rollback_failed", transaction_id,
                     symbolicName=args.symbolic_name, error=str(error),
                     rollbackVerified=rollback_verified)
        if rollback_verified or not journal.exists():
            journal.unlink(missing_ok=True)
        if args.report:
            atomic_json(args.report.resolve(), report)
        print(f"PLUGIN_ROLLBACK_ERROR: {error}", file=sys.stderr)
        return 1
    finally:
        if lock_acquired:
            lock.unlink(missing_ok=True)


def path_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def recover_plugin(args: argparse.Namespace) -> int:
    bundles = resolved_directory(args.bundle_directory, "bundle directory")
    backups = resolved_directory(args.backup_directory or bundles.parent / "plugin-backups",
                                 "backup directory")
    journal = bundles.parent / ".pdr-plugin-transaction.json"
    lock = bundles.parent / ".pdr-plugin.lock"
    audit_path = args.audit or bundles.parent / "plugin-transactions.audit.jsonl"
    if not args.confirm_runtime_stopped:
        print("PLUGIN_RECOVER_ERROR: --confirm-runtime-stopped is required", file=sys.stderr)
        return 1
    if not journal.is_file():
        print("PLUGIN_RECOVER_ERROR: no interrupted plugin transaction exists", file=sys.stderr)
        return 1
    transaction_id = "unknown"
    lock_acquired = False
    try:
        document = json.loads(journal.read_text(encoding="utf-8"))
        if (not isinstance(document, dict) or document.get("schemaVersion") != 1 or
                document.get("operation") != "install" or
                not isinstance(document.get("transactionId"), str)):
            raise ValueError("unsupported plugin transaction journal")
        transaction_id = document["transactionId"]
        acquire_lock(lock, transaction_id)
        lock_acquired = True
        state = document.get("state")
        target = Path(str(document.get("target", "")))
        stage = Path(str(document.get("stage", "")))
        backup_value = document.get("backup")
        backup = Path(backup_value) if backup_value else None
        previous_value = document.get("previousTarget")
        previous = Path(previous_value) if previous_value else None
        if not path_within(target, bundles) or not path_within(stage, bundles):
            raise ValueError("transaction target or staging path escapes the Bundle directory")
        if backup and not path_within(backup, backups):
            raise ValueError("transaction backup path escapes the backup directory")
        if previous and not path_within(previous, bundles):
            raise ValueError("transaction previous target escapes the Bundle directory")
        outcome = ""
        if state == "staging":
            stage.unlink(missing_ok=True)
            outcome = "staging-discarded"
        elif state == "backup-created":
            if not backup or not backup.is_file() or not previous:
                raise ValueError("backup-created transaction is missing recovery material")
            if target.exists():
                failed = backups / "failed" / transaction_id / target.name
                failed.parent.mkdir(parents=True, exist_ok=True)
                os.replace(target, failed)
            os.replace(backup, previous)
            expected = str(document.get("backupSha256", ""))
            if expected and sha256(previous) != expected:
                raise OSError("recovered plugin digest does not match transaction journal")
            stage.unlink(missing_ok=True)
            outcome = "previous-plugin-restored"
        elif state == "committed":
            if not target.is_file() or sha256(target) != document.get("artifactSha256"):
                raise ValueError("committed plugin cannot be verified")
            stage.unlink(missing_ok=True)
            outcome = "committed-plugin-verified"
        else:
            raise ValueError(f"unsupported plugin transaction state: {state}")
        journal.unlink()
        report = {"schemaVersion": 1, "operation": "plugin-recover", "passed": True,
                  "transactionId": transaction_id, "outcome": outcome, "finishedAt": now()}
        append_audit(audit_path, "plugin_transaction_recovered", transaction_id,
                     outcome=outcome)
        if args.report:
            atomic_json(args.report.resolve(), report)
        print(f"PLUGIN_RECOVER_PASS id={transaction_id} outcome={outcome}")
        return 0
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        append_audit(audit_path, "plugin_transaction_recovery_failed", transaction_id,
                     error=str(error))
        print(f"PLUGIN_RECOVER_ERROR: {error}", file=sys.stderr)
        return 1
    finally:
        if lock_acquired:
            lock.unlink(missing_ok=True)


def preflight_command(args: argparse.Namespace) -> int:
    try:
        result = preflight(args.artifact.resolve(), args.bundle_directory.resolve(),
                           args.expected_sha256, getattr(args, "runtime_contract", None), args)
        if args.report:
            atomic_json(args.report.resolve(), result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["passed"] else 1
    except (OSError, UnicodeError, ValueError, zipfile.BadZipFile) as error:
        if args.report:
            atomic_json(args.report.resolve(), {
                "schemaVersion": 1, "operation": "plugin-preflight", "passed": False,
                "checkedAt": now(), "error": str(error),
            })
        print(f"PLUGIN_PREFLIGHT_ERROR: {error}", file=sys.stderr)
        return 2


def add_provenance_arguments(command: argparse.ArgumentParser) -> None:
    command.add_argument("--attestation", type=Path)
    command.add_argument("--signature", type=Path)
    command.add_argument("--public-key", type=Path)
    command.add_argument("--trust-policy", type=Path)
    command.add_argument("--expected-trust-policy-id")
    command.add_argument("--expected-trust-policy-sha256")
    command.add_argument("--signature-check-executable", type=Path)
    command.add_argument("--allow-unsigned-plugin", action="store_true")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    sign = commands.add_parser("sign")
    sign.add_argument("artifact", type=Path)
    sign.add_argument("--publisher-id", required=True)
    sign.add_argument("--key-id", required=True)
    sign.add_argument("--private-key-path-environment", required=True)
    sign.add_argument("--private-key-passphrase-environment")
    sign.add_argument("--attestation", required=True, type=Path)
    sign.add_argument("--signature", required=True, type=Path)
    sign.set_defaults(handler=sign_plugin)
    check = commands.add_parser("preflight")
    check.add_argument("artifact", type=Path)
    check.add_argument("--bundle-directory", required=True, type=Path)
    check.add_argument("--expected-sha256")
    check.add_argument("--runtime-contract", type=Path)
    add_provenance_arguments(check)
    check.add_argument("--report", type=Path)
    check.set_defaults(handler=preflight_command)
    install = commands.add_parser("install")
    install.add_argument("artifact", type=Path)
    install.add_argument("--bundle-directory", required=True, type=Path)
    install.add_argument("--backup-directory", type=Path)
    install.add_argument("--expected-sha256", required=True)
    install.add_argument("--runtime-contract", type=Path)
    add_provenance_arguments(install)
    install.add_argument("--confirm-runtime-stopped", action="store_true")
    install.add_argument("--audit", type=Path)
    install.add_argument("--report", type=Path)
    install.set_defaults(handler=install_plugin)
    rollback = commands.add_parser("rollback")
    rollback.add_argument("symbolic_name")
    rollback.add_argument("--bundle-directory", required=True, type=Path)
    rollback.add_argument("--backup-directory", type=Path)
    rollback.add_argument("--expected-current-sha256", required=True)
    rollback.add_argument("--expected-backup-sha256", required=True)
    rollback.add_argument("--confirm-runtime-stopped", action="store_true")
    rollback.add_argument("--audit", type=Path)
    rollback.add_argument("--report", type=Path)
    rollback.set_defaults(handler=rollback_plugin)
    recover = commands.add_parser("recover")
    recover.add_argument("--bundle-directory", required=True, type=Path)
    recover.add_argument("--backup-directory", type=Path)
    recover.add_argument("--confirm-runtime-stopped", action="store_true")
    recover.add_argument("--audit", type=Path)
    recover.add_argument("--report", type=Path)
    recover.set_defaults(handler=recover_plugin)
    return result


def main() -> int:
    args = parser().parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
