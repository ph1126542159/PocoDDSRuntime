#!/usr/bin/env python3
"""Create, verify and explicitly prune checkpoint-bound Registry audit segments."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Callable

import team_contract_package as package_tool
import team_contract_registry as registry_tool


ARCHIVE_MANIFEST_PRODUCT = \
    "PocoDDSRuntimeTeamContractRegistryRemoteAuditArchiveManifest"
ARCHIVE_MARKER_PRODUCT = \
    "PocoDDSRuntimeTeamContractRegistryRemoteAuditArchiveMarker"
ARCHIVE_BASE_PRODUCT = \
    "PocoDDSRuntimeTeamContractRegistryRemoteAuditArchiveBase"
ARCHIVE_REPORT_PRODUCT = \
    "PocoDDSRuntimeTeamContractRegistryRemoteAuditArchiveReport"
ARCHIVE_STATUS_PRODUCT = \
    "PocoDDSRuntimeTeamContractRegistryRemoteAuditArchiveStatus"
CHECKPOINT_PRODUCT = \
    "PocoDDSRuntimeTeamContractRegistryRemoteAuditCheckpoint"
MAX_ARCHIVE_RECORDS = 1_000_000
MAX_ARCHIVE_BYTES = 4 * 1024 * 1024 * 1024
ZIP_TIME = (1980, 1, 1, 0, 0, 0)


def canonical_sha(document: dict[str, Any]) -> str:
    return package_tool.sha256_bytes(package_tool.canonical_bytes(document))


def archive_base_path(control: Path) -> Path:
    return registry_tool.safe_member(
        control, "audit/archive-base.json", "remote audit archive base"
    )


def archive_markers_root(control: Path) -> Path:
    return registry_tool.safe_member(
        control, "audit/archives", "remote audit archive markers"
    )


def archive_marker_path(control: Path, through: int, digest: str) -> Path:
    return registry_tool.safe_member(
        control,
        f"audit/archives/{through:020d}-{digest}.json",
        "remote audit archive marker",
    )


def validate_base(document: Any, registry_id: str | None = None) -> None:
    fields = {
        "schemaVersion", "product", "registryId", "throughSequence",
        "throughRecordSha256", "lastArchiveMarkerSha256", "updatedAt",
    }
    if (not isinstance(document, dict) or set(document) != fields
            or document.get("schemaVersion") != 1
            or document.get("product") != ARCHIVE_BASE_PRODUCT
            or not package_tool.IDENTIFIER.fullmatch(
                str(document.get("registryId", "")))
            or (registry_id is not None and document["registryId"] != registry_id)
            or type(document.get("throughSequence")) is not int
            or document["throughSequence"] < 1
            or not package_tool.SHA256.fullmatch(
                str(document.get("throughRecordSha256", "")))
            or not package_tool.SHA256.fullmatch(
                str(document.get("lastArchiveMarkerSha256", "")))):
        raise ValueError("remote audit archive base is malformed")
    package_tool.parse_time(document.get("updatedAt"), "audit archive base updatedAt")


def validate_marker(document: Any, registry_id: str | None = None) -> None:
    fields = {
        "schemaVersion", "product", "registryId", "archiveId",
        "fromSequence", "throughSequence", "previousRecordSha256",
        "throughRecordSha256", "archiveFile", "archiveSha256",
        "manifestSha256", "checkpointId", "checkpointSha256",
        "auditPolicyId", "auditPolicySha256",
        "previousArchiveMarkerSha256", "createdAt",
    }
    if (not isinstance(document, dict) or set(document) != fields
            or document.get("schemaVersion") != 1
            or document.get("product") != ARCHIVE_MARKER_PRODUCT
            or any(not package_tool.IDENTIFIER.fullmatch(
                str(document.get(name, "")))
                for name in ("registryId", "archiveId", "checkpointId",
                             "auditPolicyId"))
            or (registry_id is not None and document["registryId"] != registry_id)
            or type(document.get("fromSequence")) is not int
            or type(document.get("throughSequence")) is not int
            or document["fromSequence"] < 1
            or document["throughSequence"] < document["fromSequence"]
            or any(value is not None and not package_tool.SHA256.fullmatch(str(value))
                   for value in (document.get("previousRecordSha256"),
                                 document.get("previousArchiveMarkerSha256")))
            or any(not package_tool.SHA256.fullmatch(str(document.get(name, "")))
                   for name in ("throughRecordSha256", "archiveSha256",
                                "manifestSha256", "checkpointSha256",
                                "auditPolicySha256"))
            or not isinstance(document.get("archiveFile"), str)
            or Path(document["archiveFile"]).name != document["archiveFile"]
            or not document["archiveFile"].endswith(".pdraudit")):
        raise ValueError("remote audit archive marker is malformed")
    package_tool.parse_time(document.get("createdAt"), "audit archive createdAt")


def validate_manifest(document: Any, registry_id: str | None = None) -> None:
    fields = {
        "schemaVersion", "product", "archiveId", "registryId",
        "fromSequence", "throughSequence", "previousRecordSha256",
        "throughRecordSha256", "records", "checkpoint", "auditPolicy",
        "createdAt",
    }
    if (not isinstance(document, dict) or set(document) != fields
            or document.get("schemaVersion") != 1
            or document.get("product") != ARCHIVE_MANIFEST_PRODUCT
            or any(not package_tool.IDENTIFIER.fullmatch(
                str(document.get(name, "")))
                for name in ("archiveId", "registryId"))
            or (registry_id is not None and document["registryId"] != registry_id)
            or type(document.get("fromSequence")) is not int
            or type(document.get("throughSequence")) is not int
            or document["fromSequence"] < 1
            or document["throughSequence"] < document["fromSequence"]
            or (document.get("previousRecordSha256") is not None
                and not package_tool.SHA256.fullmatch(
                    str(document["previousRecordSha256"])))
            or not package_tool.SHA256.fullmatch(
                str(document.get("throughRecordSha256", "")))
            or not isinstance(document.get("records"), list)
            or not 1 <= len(document["records"]) <= MAX_ARCHIVE_RECORDS):
        raise ValueError("remote audit archive manifest is malformed")
    expected_count = document["throughSequence"] - document["fromSequence"] + 1
    if len(document["records"]) != expected_count:
        raise ValueError("remote audit archive record count changed")
    record_fields = {"sequence", "sha256", "path"}
    for offset, item in enumerate(document["records"]):
        sequence = document["fromSequence"] + offset
        if (not isinstance(item, dict) or set(item) != record_fields
                or item.get("sequence") != sequence
                or not package_tool.SHA256.fullmatch(str(item.get("sha256", "")))
                or item.get("path") != f"records/{sequence:020d}-{item.get('sha256')}.json"):
            raise ValueError("remote audit archive record inventory is malformed")
    checkpoint = document.get("checkpoint")
    if (not isinstance(checkpoint, dict) or set(checkpoint) != {
            "checkpointId", "sha256", "auditSequence", "auditRecordSha256"
        } or not package_tool.IDENTIFIER.fullmatch(
            str(checkpoint.get("checkpointId", "")))
            or not package_tool.SHA256.fullmatch(str(checkpoint.get("sha256", "")))
            or checkpoint.get("auditSequence") != document["throughSequence"]
            or checkpoint.get("auditRecordSha256") != document["throughRecordSha256"]):
        raise ValueError("remote audit archive checkpoint binding is malformed")
    policy = document.get("auditPolicy")
    if (not isinstance(policy, dict) or set(policy) != {"policyId", "sha256"}
            or not package_tool.IDENTIFIER.fullmatch(str(policy.get("policyId", "")))
            or not package_tool.SHA256.fullmatch(str(policy.get("sha256", "")))):
        raise ValueError("remote audit archive policy binding is malformed")
    package_tool.parse_time(document.get("createdAt"), "audit archive createdAt")


def safe_archive_directory(value: str | Path, control: Path,
                           create: bool = False) -> Path:
    supplied = Path(value)
    if supplied.is_symlink() or bool(getattr(supplied, "is_junction", lambda: False)()):
        raise ValueError("remote audit archive directory must not be a link")
    directory = supplied.resolve()
    if create:
        directory.mkdir(parents=True, exist_ok=True)
    if not directory.is_dir() or directory.is_symlink():
        raise ValueError("remote audit archive directory is unavailable")
    try:
        directory.relative_to(control.resolve())
    except ValueError:
        pass
    else:
        raise ValueError("remote audit archives must be stored outside control state")
    return directory


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100600 << 16
    info.create_system = 3
    return info


def write_archive(path: Path, manifest: dict[str, Any], checkpoint: bytes,
                  records: list[tuple[int, str, bytes]]) -> None:
    if path.is_symlink():
        raise ValueError("remote audit archive output must not be a link")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(8)}.tmp")
    try:
        with zipfile.ZipFile(temporary, "w", allowZip64=True) as archive:
            archive.writestr(_zip_info("manifest.json"), package_tool.json_bytes(manifest))
            archive.writestr(_zip_info("checkpoint.json"), checkpoint)
            for sequence, digest, content in records:
                archive.writestr(
                    _zip_info(f"records/{sequence:020d}-{digest}.json"), content
                )
        descriptor = os.open(temporary, os.O_RDWR)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        if path.exists():
            if (not path.is_file()
                    or package_tool.sha256_file(path)
                    != package_tool.sha256_file(temporary)):
                raise ValueError("remote audit archive output already differs")
        else:
            os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def read_archive(path: Path, registry_id: str | None = None,
                 record_validator: Callable[[Any, str | None], None] | None = None) \
        -> tuple[dict[str, Any], bytes, dict[int, tuple[str, dict[str, Any], bytes]]]:
    if path.is_symlink() or not path.is_file():
        raise ValueError("remote audit archive is unavailable or is a link")
    if path.stat().st_size > MAX_ARCHIVE_BYTES:
        raise ValueError("remote audit archive exceeds maximum bytes")
    try:
        archive_context = zipfile.ZipFile(path, "r")
    except (OSError, zipfile.BadZipFile) as error:
        raise ValueError("remote audit archive container is invalid") from error
    with archive_context as archive:
        try:
            infos = archive.infolist()
        except (OSError, zipfile.BadZipFile) as error:
            raise ValueError("remote audit archive inventory is invalid") from error
        names = [item.filename for item in infos]
        if (len(names) != len(set(names)) or any(item.is_dir() for item in infos)
                or any(item.flag_bits & 0x1 for item in infos)
                or any(item.file_size > MAX_ARCHIVE_BYTES for item in infos)):
            raise ValueError("remote audit archive entry inventory is unsafe")
        if "manifest.json" not in names or "checkpoint.json" not in names:
            raise ValueError("remote audit archive lacks manifest or checkpoint")
        manifest_raw = archive.read("manifest.json")
        try:
            manifest = json.loads(manifest_raw)
        except (UnicodeError, json.JSONDecodeError) as error:
            raise ValueError("remote audit archive manifest is invalid JSON") from error
        validate_manifest(manifest, registry_id)
        if manifest_raw != package_tool.json_bytes(manifest):
            raise ValueError("remote audit archive manifest encoding changed")
        expected = {"manifest.json", "checkpoint.json"} | {
            item["path"] for item in manifest["records"]
        }
        if set(names) != expected:
            raise ValueError("remote audit archive contains unexpected or missing entries")
        checkpoint = archive.read("checkpoint.json")
        if package_tool.sha256_bytes(checkpoint) != manifest["checkpoint"]["sha256"]:
            raise ValueError("remote audit archive checkpoint digest changed")
        total = len(manifest_raw) + len(checkpoint)
        records: dict[int, tuple[str, dict[str, Any], bytes]] = {}
        previous = manifest["previousRecordSha256"]
        for item in manifest["records"]:
            content = archive.read(item["path"])
            total += len(content)
            if total > MAX_ARCHIVE_BYTES:
                raise ValueError("remote audit archive expanded bytes exceed capacity")
            digest = package_tool.sha256_bytes(content)
            if digest != item["sha256"]:
                raise ValueError("remote audit archive record digest changed")
            try:
                record = json.loads(content)
            except (UnicodeError, json.JSONDecodeError) as error:
                raise ValueError("remote audit archive record is invalid JSON") from error
            if record_validator is not None:
                record_validator(record, registry_id)
            if (record.get("sequence") != item["sequence"]
                    or record.get("previousRecordSha256") != previous):
                raise ValueError("remote audit archive record chain changed")
            previous = digest
            records[item["sequence"]] = (digest, record, content)
        if previous != manifest["throughRecordSha256"]:
            raise ValueError("remote audit archive terminal digest changed")
        return manifest, checkpoint, records


def load_registered_archives(
        control: Path, archive_directory: str | Path | None, registry_id: str,
        record_validator: Callable[[Any, str | None], None] | None = None
        ) -> dict[str, Any]:
    base_path = archive_base_path(control)
    markers_root = archive_markers_root(control)
    marker_paths = sorted(markers_root.glob("*.json")) if markers_root.is_dir() else []
    if not base_path.is_file():
        if marker_paths:
            raise ValueError("remote audit archive registration is incomplete")
        return {
            "baseSequence": 0, "baseRecordSha256": None,
            "lastArchiveMarkerSha256": None, "archiveCount": 0,
            "archiveBytes": 0, "recordsBySequence": {}, "recordsByDigest": {},
            "segments": [],
        }
    base = json.loads(base_path.read_bytes())
    validate_base(base, registry_id)
    if archive_directory is None:
        raise ValueError("remote audit archive directory is required by registered segments")
    directory = safe_archive_directory(archive_directory, control)
    expected_from = 1
    previous_record = None
    previous_marker = None
    records_by_sequence: dict[int, tuple[str, dict[str, Any], bytes]] = {}
    records_by_digest: dict[str, dict[str, Any]] = {}
    archive_bytes = 0
    segments: list[dict[str, Any]] = []
    for marker_path in marker_paths:
        if marker_path.is_symlink() or not marker_path.is_file():
            raise ValueError("remote audit archive marker must be a regular file")
        marker_content = marker_path.read_bytes()
        marker_digest = package_tool.sha256_bytes(marker_content)
        marker = json.loads(marker_content)
        validate_marker(marker, registry_id)
        if marker_path.name != f"{marker['throughSequence']:020d}-{marker_digest}.json":
            raise ValueError("remote audit archive marker filename changed")
        if (marker["fromSequence"] != expected_from
                or marker["previousRecordSha256"] != previous_record
                or marker["previousArchiveMarkerSha256"] != previous_marker):
            raise ValueError("remote audit archive marker chain changed")
        archive_path = registry_tool.safe_member(
            directory, marker["archiveFile"], "registered remote audit archive"
        )
        if package_tool.sha256_file(archive_path) != marker["archiveSha256"]:
            raise ValueError("registered remote audit archive digest changed")
        try:
            manifest, checkpoint, records = read_archive(
                archive_path, registry_id, record_validator
            )
        except (KeyError, zipfile.BadZipFile) as error:
            raise ValueError("registered remote audit archive is unreadable") from error
        if (manifest["archiveId"] != marker["archiveId"]
                or manifest["fromSequence"] != marker["fromSequence"]
                or manifest["throughSequence"] != marker["throughSequence"]
                or manifest["previousRecordSha256"] != marker["previousRecordSha256"]
                or manifest["throughRecordSha256"] != marker["throughRecordSha256"]
                or package_tool.sha256_bytes(package_tool.json_bytes(manifest))
                    != marker["manifestSha256"]
                or package_tool.sha256_bytes(checkpoint) != marker["checkpointSha256"]
                or manifest["checkpoint"]["checkpointId"] != marker["checkpointId"]
                or manifest["auditPolicy"]["policyId"] != marker["auditPolicyId"]
                or manifest["auditPolicy"]["sha256"] != marker["auditPolicySha256"]):
            raise ValueError("remote audit archive marker binding changed")
        checkpoint_document = json.loads(checkpoint)
        if (checkpoint_document.get("product") != CHECKPOINT_PRODUCT
                or checkpoint_document.get("checkpointId") != marker["checkpointId"]
                or checkpoint_document.get("auditSequence") != marker["throughSequence"]
                or checkpoint_document.get("auditRecordSha256")
                    != marker["throughRecordSha256"]):
            raise ValueError("remote audit archive checkpoint scope changed")
        for sequence, value in records.items():
            digest, record, _ = value
            if sequence in records_by_sequence or digest in records_by_digest:
                raise ValueError("remote audit archive record identity is duplicated")
            records_by_sequence[sequence] = value
            records_by_digest[digest] = record
        expected_from = marker["throughSequence"] + 1
        previous_record = marker["throughRecordSha256"]
        previous_marker = marker_digest
        archive_bytes += archive_path.stat().st_size
        segments.append({
            "marker": marker, "markerSha256": marker_digest,
            "archivePath": archive_path, "manifest": manifest,
            "checkpoint": checkpoint,
        })
    if (not marker_paths or base["throughSequence"] != expected_from - 1
            or base["throughRecordSha256"] != previous_record
            or base["lastArchiveMarkerSha256"] != previous_marker):
        raise ValueError("remote audit archive base does not match registered segments")
    return {
        "baseSequence": base["throughSequence"],
        "baseRecordSha256": base["throughRecordSha256"],
        "lastArchiveMarkerSha256": base["lastArchiveMarkerSha256"],
        "archiveCount": len(marker_paths), "archiveBytes": archive_bytes,
        "recordsBySequence": records_by_sequence,
        "recordsByDigest": records_by_digest,
        "segments": segments,
    }


def status_document(control: Path, archive_directory: str | Path | None,
                    registry_id: str,
                    record_validator: Callable[[Any, str | None], None] | None = None
                    ) -> dict[str, Any]:
    loaded = load_registered_archives(
        control, archive_directory, registry_id, record_validator
    )
    online_root = control / "audit" / "records"
    online = len(list(online_root.glob("*.json"))) if online_root.is_dir() else 0
    return {
        "schemaVersion": 1, "product": ARCHIVE_STATUS_PRODUCT, "passed": True,
        "registryId": registry_id, "archiveCount": loaded["archiveCount"],
        "archivedThroughSequence": loaded["baseSequence"],
        "archivedThroughRecordSha256": loaded["baseRecordSha256"],
        "archiveBytes": loaded["archiveBytes"], "onlineAuditRecords": online,
        "verifiedAt": registry_tool.utc_time(None),
    }


def _remote_tool() -> Any:
    import team_contract_registry_remote as remote_tool
    return remote_tool


def _archive_output(directory: Path, value: str | Path) -> Path:
    supplied = Path(value)
    if supplied.is_absolute():
        output = supplied.resolve()
        if output.parent != directory:
            raise ValueError("remote audit archive output is outside archive directory")
        return output
    return registry_tool.safe_member(directory, supplied, "remote audit archive output")


def _checkpoint_verify(args: argparse.Namespace, checkpoint: Path,
                       archive_directory: Path | None) -> None:
    remote = _remote_tool()
    result = remote.audit_checkpoint_verify_command(argparse.Namespace(
        control_directory=args.control_directory, registry_id=args.registry_id,
        checkpoint=str(checkpoint), audit_policy=args.audit_policy,
        expected_audit_policy_id=args.expected_audit_policy_id,
        expected_audit_policy_sha256=args.expected_audit_policy_sha256,
        verification_time=args.verification_time,
        audit_archive_directory=(str(archive_directory)
                                 if archive_directory is not None else None),
        report=None,
    ))
    if result != 0:
        raise ValueError("remote audit archive checkpoint verification failed")


def _write_report(path: str | None, document: dict[str, Any]) -> None:
    if path:
        package_tool.write_json(Path(path).resolve(), document)


def create_command(args: argparse.Namespace) -> int:
    try:
        remote = _remote_tool()
        control = Path(args.control_directory).resolve()
        directory = safe_archive_directory(args.archive_directory, control, create=True)
        output = _archive_output(directory, args.output)
        if not output.name.endswith(".pdraudit"):
            raise ValueError("remote audit archive output must use .pdraudit")
        if (not package_tool.IDENTIFIER.fullmatch(str(args.archive_id))
                or not package_tool.IDENTIFIER.fullmatch(str(args.registry_id))):
            raise ValueError("remote audit archive identity is invalid")
        checkpoint_path = package_tool.resolved_path(
            args.checkpoint, "remote audit checkpoint"
        )
        _checkpoint_verify(args, checkpoint_path, directory)
        checkpoint = checkpoint_path.read_bytes()
        checkpoint_document = json.loads(checkpoint)
        through = checkpoint_document["auditSequence"]
        if args.through_sequence is not None and args.through_sequence != through:
            raise ValueError("remote audit archive through sequence changed")
        policy_path = package_tool.resolved_path(args.audit_policy, "remote audit policy")
        policy_sha = package_tool.sha256_file(policy_path)
        if (checkpoint_document["registryId"] != args.registry_id
                or policy_sha != str(args.expected_audit_policy_sha256).lower()):
            raise ValueError("remote audit archive trust policy is not pinned")
        with remote.ControlLease(control) as lease:
            lease.assert_current()
            verification = remote.verify_audit_chain(
                control, args.registry_id, archive_directory=directory
            )
            loaded = load_registered_archives(
                control, directory, args.registry_id, remote.validate_audit_record
            )
            start = loaded["baseSequence"] + 1
            if through < start or through > verification["sequence"]:
                raise ValueError("remote audit archive sequence range is unavailable")
            previous = loaded["baseRecordSha256"]
            records: list[tuple[int, str, bytes]] = []
            inventory: list[dict[str, Any]] = []
            for sequence in range(start, through + 1):
                candidates = list((control / "audit" / "records").glob(
                    f"{sequence:020d}-*.json"
                ))
                if len(candidates) != 1:
                    raise ValueError("remote audit archive source record is unavailable")
                path = candidates[0]
                content = path.read_bytes()
                digest = package_tool.sha256_bytes(content)
                record = json.loads(content)
                remote.validate_audit_record(record, args.registry_id)
                if (path.name != f"{sequence:020d}-{digest}.json"
                        or record["sequence"] != sequence
                        or record["previousRecordSha256"] != previous):
                    raise ValueError("remote audit archive source chain changed")
                records.append((sequence, digest, content))
                inventory.append({
                    "sequence": sequence, "sha256": digest,
                    "path": f"records/{sequence:020d}-{digest}.json",
                })
                previous = digest
            if previous != checkpoint_document["auditRecordSha256"]:
                raise ValueError("remote audit archive checkpoint boundary changed")
            manifest = {
                "schemaVersion": 1, "product": ARCHIVE_MANIFEST_PRODUCT,
                "archiveId": args.archive_id, "registryId": args.registry_id,
                "fromSequence": start, "throughSequence": through,
                "previousRecordSha256": loaded["baseRecordSha256"],
                "throughRecordSha256": previous,
                "records": inventory,
                "checkpoint": {
                    "checkpointId": checkpoint_document["checkpointId"],
                    "sha256": package_tool.sha256_bytes(checkpoint),
                    "auditSequence": through,
                    "auditRecordSha256": previous,
                },
                "auditPolicy": {
                    "policyId": args.expected_audit_policy_id,
                    "sha256": policy_sha,
                },
                "createdAt": registry_tool.utc_time(args.created_at),
            }
            validate_manifest(manifest, args.registry_id)
            lease.assert_current()
            write_archive(output, manifest, checkpoint, records)
            archive_sha = package_tool.sha256_file(output)
            marker = {
                "schemaVersion": 1, "product": ARCHIVE_MARKER_PRODUCT,
                "archiveId": args.archive_id, "registryId": args.registry_id,
                "fromSequence": start, "throughSequence": through,
                "previousRecordSha256": loaded["baseRecordSha256"],
                "throughRecordSha256": previous,
                "archiveFile": output.name, "archiveSha256": archive_sha,
                "manifestSha256": package_tool.sha256_bytes(
                    package_tool.json_bytes(manifest)
                ),
                "checkpointId": checkpoint_document["checkpointId"],
                "checkpointSha256": package_tool.sha256_bytes(checkpoint),
                "auditPolicyId": args.expected_audit_policy_id,
                "auditPolicySha256": policy_sha,
                "previousArchiveMarkerSha256": loaded["lastArchiveMarkerSha256"],
                "createdAt": manifest["createdAt"],
            }
            validate_marker(marker, args.registry_id)
            marker_content = package_tool.json_bytes(marker)
            marker_sha = package_tool.sha256_bytes(marker_content)
            registry_tool.exclusive_bytes(
                archive_marker_path(control, through, marker_sha), marker_content
            )
            lease.assert_current()
            base = {
                "schemaVersion": 1, "product": ARCHIVE_BASE_PRODUCT,
                "registryId": args.registry_id, "throughSequence": through,
                "throughRecordSha256": previous,
                "lastArchiveMarkerSha256": marker_sha,
                "updatedAt": manifest["createdAt"],
            }
            validate_base(base, args.registry_id)
            package_tool.write_json(archive_base_path(control), base)
            remote.verify_audit_chain(
                control, args.registry_id, archive_directory=directory
            )
        report = {
            "schemaVersion": 1, "product": ARCHIVE_REPORT_PRODUCT,
            "passed": True, "operation": "create", "registryId": args.registry_id,
            "archiveId": args.archive_id, "fromSequence": start,
            "throughSequence": through, "throughRecordSha256": previous,
            "archiveFile": output.name, "archiveSha256": archive_sha,
            "affectedRecords": len(records), "affectedBytes": output.stat().st_size,
            "completedAt": registry_tool.utc_time(None),
        }
        _write_report(args.report, report)
        print("PDR_TEAM_CONTRACT_REGISTRY_REMOTE_AUDIT_ARCHIVE_CREATE_PASS "
              f"from={start} through={through} records={len(records)}")
        return 0
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError,
            zipfile.BadZipFile) as error:
        print(f"PDR_TEAM_CONTRACT_REGISTRY_REMOTE_AUDIT_ARCHIVE_ERROR: {error}",
              file=sys.stderr)
        return 2


def verify_command(args: argparse.Namespace) -> int:
    try:
        remote = _remote_tool()
        control = Path(args.control_directory).resolve()
        directory = safe_archive_directory(args.archive_directory, control)
        loaded = load_registered_archives(
            control, directory, args.registry_id, remote.validate_audit_record
        )
        verification = remote.verify_audit_chain(
            control, args.registry_id, archive_directory=directory
        )
        with tempfile.TemporaryDirectory(prefix="pdr-audit-checkpoint-") as temporary:
            for index, segment in enumerate(loaded["segments"]):
                marker = segment["marker"]
                if (marker["auditPolicyId"] != args.expected_audit_policy_id
                        or marker["auditPolicySha256"]
                        != str(args.expected_audit_policy_sha256).lower()):
                    raise ValueError("registered audit archive policy pin changed")
                checkpoint = Path(temporary) / f"checkpoint-{index}.json"
                checkpoint.write_bytes(segment["checkpoint"])
                _checkpoint_verify(args, checkpoint, directory)
        report = {
            **status_document(
                control, directory, args.registry_id, remote.validate_audit_record
            ),
            "product": ARCHIVE_REPORT_PRODUCT, "operation": "verify",
            "currentSequence": verification["sequence"],
        }
        _write_report(args.report, report)
        print("PDR_TEAM_CONTRACT_REGISTRY_REMOTE_AUDIT_ARCHIVE_VERIFY_PASS "
              f"archives={loaded['archiveCount']} through={loaded['baseSequence']}")
        return 0
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError,
            zipfile.BadZipFile) as error:
        print(f"PDR_TEAM_CONTRACT_REGISTRY_REMOTE_AUDIT_ARCHIVE_ERROR: {error}",
              file=sys.stderr)
        return 2


def prune_command(args: argparse.Namespace) -> int:
    try:
        if not args.confirm_prune:
            raise ValueError("remote audit archive prune requires --confirm-prune")
        remote = _remote_tool()
        control = Path(args.control_directory).resolve()
        directory = safe_archive_directory(args.archive_directory, control)
        with remote.ControlLease(control) as lease:
            lease.assert_current()
            loaded = load_registered_archives(
                control, directory, args.registry_id, remote.validate_audit_record
            )
            if (loaded["baseSequence"] != args.expected_through_sequence
                    or loaded["baseRecordSha256"]
                    != str(args.expected_through_record_sha256).lower()):
                raise ValueError("remote audit archive prune baseline changed")
            remote.verify_audit_chain(
                control, args.registry_id, archive_directory=directory
            )
            candidates: list[Path] = []
            affected_bytes = 0
            for sequence, (digest, _record, archived) in \
                    loaded["recordsBySequence"].items():
                paths = list((control / "audit" / "records").glob(
                    f"{sequence:020d}-*.json"
                ))
                if not paths:
                    continue
                if (len(paths) != 1 or paths[0].name
                        != f"{sequence:020d}-{digest}.json"
                        or paths[0].read_bytes() != archived):
                    raise ValueError("online audit record differs from registered archive")
                candidates.append(paths[0])
                affected_bytes += paths[0].stat().st_size
            lease.assert_current()
            for path in candidates:
                path.unlink()
            remote.verify_audit_chain(
                control, args.registry_id, archive_directory=directory
            )
        report = {
            "schemaVersion": 1, "product": ARCHIVE_REPORT_PRODUCT,
            "passed": True, "operation": "prune", "registryId": args.registry_id,
            "archiveId": None, "fromSequence": 1,
            "throughSequence": loaded["baseSequence"],
            "throughRecordSha256": loaded["baseRecordSha256"],
            "archiveFile": None, "archiveSha256": None,
            "affectedRecords": len(candidates), "affectedBytes": affected_bytes,
            "completedAt": registry_tool.utc_time(None),
        }
        _write_report(args.report, report)
        print("PDR_TEAM_CONTRACT_REGISTRY_REMOTE_AUDIT_ARCHIVE_PRUNE_PASS "
              f"through={loaded['baseSequence']} records={len(candidates)}")
        return 0
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError,
            zipfile.BadZipFile) as error:
        print(f"PDR_TEAM_CONTRACT_REGISTRY_REMOTE_AUDIT_ARCHIVE_ERROR: {error}",
              file=sys.stderr)
        return 2


def status_command(args: argparse.Namespace) -> int:
    try:
        remote = _remote_tool()
        control = Path(args.control_directory).resolve()
        report = status_document(
            control, args.archive_directory, args.registry_id,
            remote.validate_audit_record,
        )
        _write_report(args.report, report)
        print("PDR_TEAM_CONTRACT_REGISTRY_REMOTE_AUDIT_ARCHIVE_STATUS_PASS "
              f"archives={report['archiveCount']} "
              f"through={report['archivedThroughSequence']}")
        return 0
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError,
            zipfile.BadZipFile) as error:
        print(f"PDR_TEAM_CONTRACT_REGISTRY_REMOTE_AUDIT_ARCHIVE_ERROR: {error}",
              file=sys.stderr)
        return 2


def _common(command: argparse.ArgumentParser) -> None:
    command.add_argument("--control-directory", required=True)
    command.add_argument("--audit-archive-directory", dest="archive_directory",
                         required=True)
    command.add_argument("--registry-id", required=True)
    command.add_argument("--report")


def _trust(command: argparse.ArgumentParser) -> None:
    command.add_argument("--audit-policy", required=True)
    command.add_argument("--expected-audit-policy-id", required=True)
    command.add_argument("--expected-audit-policy-sha256", required=True)
    command.add_argument("--verification-time")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create")
    _common(create)
    _trust(create)
    create.add_argument("--archive-id", required=True)
    create.add_argument("--checkpoint", required=True)
    create.add_argument("--through-sequence", type=int)
    create.add_argument("--created-at")
    create.add_argument("--output", required=True)
    create.set_defaults(handler=create_command)
    verify = commands.add_parser("verify")
    _common(verify)
    _trust(verify)
    verify.set_defaults(handler=verify_command)
    prune = commands.add_parser("prune")
    _common(prune)
    prune.add_argument("--expected-through-sequence", type=int, required=True)
    prune.add_argument("--expected-through-record-sha256", required=True)
    prune.add_argument("--confirm-prune", action="store_true")
    prune.set_defaults(handler=prune_command)
    status = commands.add_parser("status")
    _common(status)
    status.set_defaults(handler=status_command)
    return result


def main() -> int:
    args = parser().parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
