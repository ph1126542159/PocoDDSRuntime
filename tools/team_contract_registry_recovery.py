#!/usr/bin/env python3
"""Create, verify and restore externally anchored Registry recovery points."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any

import team_contract_package as package_tool
import team_contract_provenance as provenance_tool
import team_contract_registry as registry_tool


MANIFEST_PRODUCT = "PocoDDSRuntimeTeamContractRegistryRecoveryManifest"
REPORT_PRODUCT = "PocoDDSRuntimeTeamContractRegistryRecoveryReport"
EXTENSION = ".pdrregistry"
ZIP_TIME = (1980, 1, 1, 0, 0, 0)
MAX_ENTRIES = 200_000
MAX_RECOVERY_BYTES = 8 * 1024 * 1024 * 1024


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100600 << 16
    info.create_system = 3
    return info


def _outside(path: Path, root: Path, label: str) -> None:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return
    raise ValueError(f"{label} must be stored outside the Registry root")


def _trust_args(args: argparse.Namespace, registry: Path) -> argparse.Namespace:
    return argparse.Namespace(
        registry=str(registry), trust_policy=args.trust_policy,
        expected_trust_policy_id=args.expected_trust_policy_id,
        expected_trust_policy_sha256=args.expected_trust_policy_sha256,
        verification_time=args.verification_time,
        maximum_files=args.maximum_files,
        maximum_expanded_bytes=args.maximum_expanded_bytes,
    )


def _verify_anchor(args: argparse.Namespace, registry: Path, anchor: Path) -> None:
    report = anchor.with_name(f".{anchor.name}.{secrets.token_hex(8)}.verify.json")
    try:
        result = provenance_tool.registry_anchor_verify_command(argparse.Namespace(
            **vars(_trust_args(args, registry)), anchor=str(anchor),
            anchor_policy=args.anchor_policy,
            expected_anchor_policy_id=args.expected_anchor_policy_id,
            expected_anchor_policy_sha256=args.expected_anchor_policy_sha256,
            verification_report=str(report),
        ))
        if result != 0:
            raise ValueError("Registry recovery anchor verification failed")
    finally:
        report.unlink(missing_ok=True)


def _chain_paths(root: Path, pointer: dict[str, Any], state: dict[str, Any]) \
        -> list[Path]:
    result: list[Path] = []
    revision = pointer["revision"]
    digest = pointer["stateSha256"]
    current = state
    while True:
        path = registry_tool.state_path(root, revision, digest)
        result.append(path)
        if revision == 0:
            break
        digest = current["previousStateSha256"]
        revision -= 1
        current = registry_tool.load_json(
            registry_tool.state_path(root, revision, digest),
            f"Registry recovery state revision {revision}",
        )
        registry_tool.validate_state(current)
    result.reverse()
    return result


def _registry_files(root: Path, pointer: dict[str, Any], state: dict[str, Any]) \
        -> list[tuple[str, str, Path]]:
    files: list[tuple[str, str, Path]] = [
        ("pointer", "registry.json", registry_tool.pointer_path(root))
    ]
    files.extend((
        "state", path.relative_to(root).as_posix(), path
    ) for path in _chain_paths(root, pointer, state))
    for item in state["packages"]:
        files.append((
            "package", item["blob"],
            registry_tool.safe_member(root, item["blob"], "Registry recovery package"),
        ))
    for item in state["locks"]:
        files.append((
            "lock", item["blob"],
            registry_tool.safe_member(root, item["blob"], "Registry recovery lock"),
        ))
    files.sort(key=lambda value: value[1])
    if len(files) != len({value[1] for value in files}):
        raise ValueError("Registry recovery inventory contains duplicate paths")
    return files


def validate_manifest(document: Any) -> None:
    fields = {
        "schemaVersion", "product", "recoveryPointId", "registryId",
        "registryRevision", "registryStateSha256", "registryPointerSha256",
        "registryTrustPolicy", "anchor", "anchorPolicy", "fileCount",
        "expandedBytes", "files", "createdAt", "operator",
    }
    if (not isinstance(document, dict) or set(document) != fields
            or document.get("schemaVersion") != 1
            or document.get("product") != MANIFEST_PRODUCT
            or any(not package_tool.IDENTIFIER.fullmatch(
                str(document.get(name, "")))
                for name in ("recoveryPointId", "registryId", "operator"))
            or type(document.get("registryRevision")) is not int
            or document["registryRevision"] < 0
            or any(not package_tool.SHA256.fullmatch(str(document.get(name, "")))
                   for name in ("registryStateSha256", "registryPointerSha256"))
            or type(document.get("fileCount")) is not int
            or not 2 <= document["fileCount"] <= MAX_ENTRIES
            or type(document.get("expandedBytes")) is not int
            or not 1 <= document["expandedBytes"] <= MAX_RECOVERY_BYTES
            or not isinstance(document.get("files"), list)
            or len(document["files"]) != document["fileCount"]):
        raise ValueError("Registry recovery manifest is malformed")
    trust = document.get("registryTrustPolicy")
    if (not isinstance(trust, dict)
            or set(trust) != {"policyId", "policySha256"}
            or not package_tool.IDENTIFIER.fullmatch(str(trust.get("policyId", "")))
            or not package_tool.SHA256.fullmatch(
                str(trust.get("policySha256", "")))):
        raise ValueError("Registry recovery trust-policy binding is malformed")
    anchor = document.get("anchor")
    if (not isinstance(anchor, dict) or set(anchor) != {
            "anchorId", "sha256", "registryRevision", "registryStateSha256"
        } or not package_tool.IDENTIFIER.fullmatch(str(anchor.get("anchorId", "")))
            or not package_tool.SHA256.fullmatch(str(anchor.get("sha256", "")))
            or anchor.get("registryRevision") != document["registryRevision"]
            or anchor.get("registryStateSha256") != document["registryStateSha256"]):
        raise ValueError("Registry recovery anchor binding is malformed")
    anchor_policy = document.get("anchorPolicy")
    if (not isinstance(anchor_policy, dict)
            or set(anchor_policy) != {"policyId", "policySha256"}
            or not package_tool.IDENTIFIER.fullmatch(
                str(anchor_policy.get("policyId", "")))
            or not package_tool.SHA256.fullmatch(
                str(anchor_policy.get("policySha256", "")))):
        raise ValueError("Registry recovery anchor-policy binding is malformed")
    item_fields = {"role", "path", "sizeBytes", "sha256"}
    allowed_roles = {"pointer", "state", "package", "lock"}
    paths: set[str] = set()
    total = 0
    for item in document["files"]:
        if (not isinstance(item, dict) or set(item) != item_fields
                or item.get("role") not in allowed_roles
                or not isinstance(item.get("path"), str)
                or package_tool.safe_archive_path(item["path"]).as_posix()
                    != item["path"]
                or item["path"] in paths
                or type(item.get("sizeBytes")) is not int
                or not 0 <= item["sizeBytes"] <= MAX_RECOVERY_BYTES
                or not package_tool.SHA256.fullmatch(str(item.get("sha256", "")))):
            raise ValueError("Registry recovery file inventory is malformed")
        paths.add(item["path"])
        total += item["sizeBytes"]
    if (document["files"] != sorted(document["files"], key=lambda item: item["path"])
            or total != document["expandedBytes"]
            or sum(1 for item in document["files"] if item["role"] == "pointer") != 1
            or sum(1 for item in document["files"] if item["role"] == "state")
                != document["registryRevision"] + 1):
        raise ValueError("Registry recovery file inventory continuity changed")
    package_tool.parse_time(document.get("createdAt"), "recovery createdAt")


def _write_archive(path: Path, manifest: dict[str, Any], anchor: bytes,
                   files: list[tuple[str, str, Path]]) -> None:
    if path.is_symlink():
        raise ValueError("Registry recovery output must not be a link")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(8)}.tmp")
    try:
        with zipfile.ZipFile(temporary, "w", allowZip64=True) as archive:
            archive.writestr(_zip_info("manifest.json"), package_tool.json_bytes(manifest))
            archive.writestr(_zip_info("anchor.json"), anchor)
            for _role, relative, source in files:
                archive.writestr(_zip_info(f"registry/{relative}"), source.read_bytes())
        descriptor = os.open(temporary, os.O_RDWR)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        if path.exists():
            if (not path.is_file()
                    or package_tool.sha256_file(path)
                    != package_tool.sha256_file(temporary)):
                raise ValueError("Registry recovery output already differs")
        else:
            os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _extract_verified(args: argparse.Namespace, recovery: Path,
                      destination: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    if recovery.is_symlink() or not recovery.is_file():
        raise ValueError("Registry recovery point is unavailable or is a link")
    if recovery.stat().st_size > MAX_RECOVERY_BYTES:
        raise ValueError("Registry recovery point exceeds maximum bytes")
    try:
        archive_context = zipfile.ZipFile(recovery, "r")
    except (OSError, zipfile.BadZipFile) as error:
        raise ValueError("Registry recovery container is invalid") from error
    with archive_context as archive:
        infos = archive.infolist()
        names = [item.filename for item in infos]
        if (not 3 <= len(infos) <= MAX_ENTRIES + 2
                or len(names) != len(set(names))
                or any(item.is_dir() or item.flag_bits & 0x1 for item in infos)
                or any(item.file_size > MAX_RECOVERY_BYTES for item in infos)
                or "manifest.json" not in names or "anchor.json" not in names):
            raise ValueError("Registry recovery entry inventory is unsafe")
        try:
            manifest_raw = archive.read("manifest.json")
            anchor_raw = archive.read("anchor.json")
        except (KeyError, OSError, zipfile.BadZipFile) as error:
            raise ValueError("Registry recovery metadata is unreadable") from error
        try:
            manifest = json.loads(manifest_raw)
            anchor = json.loads(anchor_raw)
        except (UnicodeError, json.JSONDecodeError) as error:
            raise ValueError("Registry recovery metadata is invalid JSON") from error
        validate_manifest(manifest)
        provenance_tool.validate_anchor(anchor)
        if (manifest_raw != package_tool.json_bytes(manifest)
                or package_tool.sha256_bytes(anchor_raw) != manifest["anchor"]["sha256"]
                or anchor.get("anchorId") != manifest["anchor"]["anchorId"]
                or anchor.get("registryRevision") != manifest["registryRevision"]
                or anchor.get("registryStateSha256")
                    != manifest["registryStateSha256"]):
            raise ValueError("Registry recovery metadata binding changed")
        expected_names = {"manifest.json", "anchor.json"} | {
            "registry/" + item["path"] for item in manifest["files"]
        }
        if set(names) != expected_names:
            raise ValueError("Registry recovery contains unexpected or missing entries")
        destination.mkdir(parents=True, exist_ok=False)
        anchor_path = destination / "anchor.json"
        anchor_path.write_bytes(anchor_raw)
        registry = destination / "registry"
        total = 0
        for item in manifest["files"]:
            name = "registry/" + item["path"]
            try:
                content = archive.read(name)
            except (KeyError, OSError, zipfile.BadZipFile) as error:
                raise ValueError("Registry recovery content is unreadable") from error
            total += len(content)
            if (len(content) != item["sizeBytes"]
                    or package_tool.sha256_bytes(content) != item["sha256"]
                    or total > MAX_RECOVERY_BYTES):
                raise ValueError("Registry recovery content digest changed")
            target = registry_tool.safe_member(registry, item["path"],
                                               "Registry recovery extraction")
            target.parent.mkdir(parents=True, exist_ok=True)
            registry_tool.exclusive_bytes(target, content)
    pointer, state = registry_tool.verified_current(registry, _trust_args(args, registry))
    if (pointer["registryId"] != manifest["registryId"]
            or pointer["revision"] != manifest["registryRevision"]
            or pointer["stateSha256"] != manifest["registryStateSha256"]
            or package_tool.sha256_file(registry / "registry.json")
                != manifest["registryPointerSha256"]
            or state["trustPolicy"] != manifest["registryTrustPolicy"]
            or manifest["anchorPolicy"] != {
                "policyId": args.expected_anchor_policy_id,
                "policySha256": str(args.expected_anchor_policy_sha256).lower(),
            }):
        raise ValueError("Registry recovery reconstructed state changed")
    _verify_anchor(args, registry, anchor_path)
    return manifest, {"pointer": pointer, "state": state, "registry": registry,
                      "anchor": anchor_path}


def _report(args: argparse.Namespace, document: dict[str, Any]) -> None:
    validate_report(document)
    if args.report:
        package_tool.write_json(Path(args.report).resolve(), document)


def _operation_report(operation: str, manifest: dict[str, Any], recovery: Path,
                      **values: Any) -> dict[str, Any]:
    document = {
        "schemaVersion": 1, "product": REPORT_PRODUCT, "passed": True,
        "operation": operation, "recoveryPointId": manifest["recoveryPointId"],
        "registryId": manifest["registryId"],
        "registryRevision": manifest["registryRevision"],
        "registryStateSha256": manifest["registryStateSha256"],
        "recoveryPoint": str(recovery),
        "recoveryPointSha256": package_tool.sha256_file(recovery),
        "fileCount": manifest["fileCount"],
        "expandedBytes": manifest["expandedBytes"],
        "completedAt": registry_tool.utc_time(None),
    }
    document.update(values)
    return document


def validate_report(document: Any) -> None:
    base = {
        "schemaVersion", "product", "passed", "operation", "recoveryPointId",
        "registryId", "registryRevision", "registryStateSha256",
        "recoveryPoint", "recoveryPointSha256", "fileCount", "expandedBytes",
        "completedAt",
    }
    restore = {"restoreId", "operator", "destination", "sourceUnavailableConfirmed"}
    expected = base | restore if isinstance(document, dict) \
        and document.get("operation") == "restore" else base
    if (not isinstance(document, dict) or set(document) != expected
            or document.get("schemaVersion") != 1
            or document.get("product") != REPORT_PRODUCT
            or document.get("passed") is not True
            or document.get("operation") not in {"create", "verify", "restore"}
            or any(not package_tool.IDENTIFIER.fullmatch(str(document.get(name, "")))
                   for name in ("recoveryPointId", "registryId"))
            or type(document.get("registryRevision")) is not int
            or document["registryRevision"] < 0
            or any(not package_tool.SHA256.fullmatch(str(document.get(name, "")))
                   for name in ("registryStateSha256", "recoveryPointSha256"))
            or not isinstance(document.get("recoveryPoint"), str)
            or not document["recoveryPoint"]
            or type(document.get("fileCount")) is not int
            or document["fileCount"] < 2
            or type(document.get("expandedBytes")) is not int
            or document["expandedBytes"] < 1):
        raise ValueError("Registry recovery report is malformed")
    if document["operation"] == "restore" and (
            any(not package_tool.IDENTIFIER.fullmatch(str(document.get(name, "")))
                for name in ("restoreId", "operator"))
            or not isinstance(document.get("destination"), str)
            or not document["destination"]
            or document.get("sourceUnavailableConfirmed") is not True):
        raise ValueError("Registry recovery restore report is malformed")
    package_tool.parse_time(document.get("completedAt"), "recovery completedAt")


def create_command(args: argparse.Namespace) -> int:
    try:
        root = registry_tool.registry_root(args.registry)
        output = Path(args.output).resolve()
        anchor_path = package_tool.resolved_path(args.anchor, "Registry external anchor")
        _outside(output, root, "Registry recovery point")
        _outside(anchor_path, root, "Registry recovery anchor")
        if (not output.name.endswith(EXTENSION)
                or not package_tool.IDENTIFIER.fullmatch(str(args.recovery_point_id))
                or not package_tool.IDENTIFIER.fullmatch(str(args.operator))):
            raise ValueError("Registry recovery identity or output extension is invalid")
        with registry_tool.RegistryLease(root, "recovery-point-create", args.operator) \
                as lease:
            lease.assert_current()
            pointer, state = registry_tool.verified_current(root, _trust_args(args, root))
            _verify_anchor(args, root, anchor_path)
            anchor_raw = anchor_path.read_bytes()
            anchor = json.loads(anchor_raw)
            if (anchor["registryId"] != state["registryId"]
                    or anchor["registryRevision"] != pointer["revision"]
                    or anchor["registryStateSha256"] != pointer["stateSha256"]):
                raise ValueError(
                    "Registry recovery requires an anchor at the exact current revision"
                )
            files = _registry_files(root, pointer, state)
            inventory = [{
                "role": role, "path": relative,
                "sizeBytes": path.stat().st_size,
                "sha256": package_tool.sha256_file(path),
            } for role, relative, path in files]
            manifest = {
                "schemaVersion": 1, "product": MANIFEST_PRODUCT,
                "recoveryPointId": args.recovery_point_id,
                "registryId": state["registryId"],
                "registryRevision": pointer["revision"],
                "registryStateSha256": pointer["stateSha256"],
                "registryPointerSha256": package_tool.sha256_file(
                    registry_tool.pointer_path(root)
                ),
                "registryTrustPolicy": state["trustPolicy"],
                "anchor": {
                    "anchorId": anchor["anchorId"],
                    "sha256": package_tool.sha256_bytes(anchor_raw),
                    "registryRevision": anchor["registryRevision"],
                    "registryStateSha256": anchor["registryStateSha256"],
                },
                "anchorPolicy": {
                    "policyId": args.expected_anchor_policy_id,
                    "policySha256": str(args.expected_anchor_policy_sha256).lower(),
                },
                "fileCount": len(inventory),
                "expandedBytes": sum(item["sizeBytes"] for item in inventory),
                "files": inventory,
                "createdAt": registry_tool.utc_time(args.created_at),
                "operator": args.operator,
            }
            validate_manifest(manifest)
            lease.assert_current()
            _write_archive(output, manifest, anchor_raw, files)
        with tempfile.TemporaryDirectory(prefix="pdr-registry-recovery-create-") as temp:
            _extract_verified(args, output, Path(temp) / "verified")
        report = _operation_report("create", manifest, output)
        _report(args, report)
        print("PDR_TEAM_CONTRACT_REGISTRY_RECOVERY_CREATE_PASS "
              f"revision={manifest['registryRevision']} files={manifest['fileCount']}")
        return 0
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError,
            zipfile.BadZipFile) as error:
        print(f"PDR_TEAM_CONTRACT_REGISTRY_RECOVERY_ERROR: {error}", file=sys.stderr)
        return 2


def verify_command(args: argparse.Namespace) -> int:
    try:
        recovery = package_tool.resolved_path(args.recovery_point,
                                              "Registry recovery point")
        if args.expected_recovery_point_sha256:
            expected = str(args.expected_recovery_point_sha256).lower()
            if (not package_tool.SHA256.fullmatch(expected)
                    or package_tool.sha256_file(recovery) != expected):
                raise ValueError("Registry recovery point digest is not pinned")
        with tempfile.TemporaryDirectory(prefix="pdr-registry-recovery-verify-") as temp:
            manifest, _ = _extract_verified(args, recovery, Path(temp) / "verified")
        report = _operation_report("verify", manifest, recovery)
        _report(args, report)
        print("PDR_TEAM_CONTRACT_REGISTRY_RECOVERY_VERIFY_PASS "
              f"revision={manifest['registryRevision']} files={manifest['fileCount']}")
        return 0
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError,
            zipfile.BadZipFile) as error:
        print(f"PDR_TEAM_CONTRACT_REGISTRY_RECOVERY_ERROR: {error}", file=sys.stderr)
        return 2


def _append_audit(path: Path, document: dict[str, Any]) -> None:
    if registry_tool.linklike(path):
        raise ValueError("Registry restore operation audit must not be a link")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(document, ensure_ascii=False,
                                separators=(",", ":")) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def restore_command(args: argparse.Namespace) -> int:
    staging: Path | None = None
    published_destination: Path | None = None
    committed = False
    try:
        if not args.confirm_source_unavailable:
            raise ValueError(
                "Registry restore requires --confirm-source-unavailable"
            )
        if (not package_tool.IDENTIFIER.fullmatch(str(args.restore_id))
                or not package_tool.IDENTIFIER.fullmatch(str(args.operator))):
            raise ValueError("Registry restore identity is invalid")
        recovery = package_tool.resolved_path(args.recovery_point,
                                              "Registry recovery point")
        expected = str(args.expected_recovery_point_sha256).lower()
        if (not package_tool.SHA256.fullmatch(expected)
                or package_tool.sha256_file(recovery) != expected):
            raise ValueError("Registry restore recovery-point digest changed")
        destination = Path(args.destination).resolve()
        audit = Path(args.operation_audit).resolve()
        if destination.exists() or destination.is_symlink():
            raise ValueError("Registry restore destination must not exist")
        try:
            audit.relative_to(destination)
        except ValueError:
            pass
        else:
            raise ValueError("Registry restore operation audit must be external")
        if args.report:
            _outside(Path(args.report).resolve(), destination,
                     "Registry restore report")
        destination.parent.mkdir(parents=True, exist_ok=True)
        staging = destination.with_name(
            f".{destination.name}.{args.restore_id}.{secrets.token_hex(8)}.new"
        )
        manifest, extracted = _extract_verified(args, recovery, staging)
        registry = extracted["registry"]
        if registry.parent != staging:
            raise ValueError("Registry restore staging layout changed")
        # Publish only the verified Registry subtree; anchor remains external evidence.
        published = staging / "registry"
        os.replace(published, destination)
        published_destination = destination
        shutil.rmtree(staging)
        staging = None
        pointer, state = registry_tool.verified_current(
            destination, _trust_args(args, destination)
        )
        if (pointer["revision"] != manifest["registryRevision"]
                or pointer["stateSha256"] != manifest["registryStateSha256"]
                or state["registryId"] != manifest["registryId"]):
            raise ValueError("Registry restore final verification changed")
        report = _operation_report(
            "restore", manifest, recovery, restoreId=args.restore_id,
            operator=args.operator, destination=str(destination),
            sourceUnavailableConfirmed=True,
        )
        validate_report(report)
        _append_audit(audit, report)
        committed = True
        published_destination = None
        _report(args, report)
        print("PDR_TEAM_CONTRACT_REGISTRY_RECOVERY_RESTORE_PASS "
              f"revision={manifest['registryRevision']} destination={destination}")
        return 0
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError,
            zipfile.BadZipFile) as error:
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)
        if published_destination is not None:
            shutil.rmtree(published_destination, ignore_errors=True)
        marker = "COMMITTED_ERROR" if committed else "ERROR"
        print(f"PDR_TEAM_CONTRACT_REGISTRY_RECOVERY_{marker}: {error}", file=sys.stderr)
        return 3 if committed else 2


def _common_trust(command: argparse.ArgumentParser) -> None:
    command.add_argument("--trust-policy", required=True)
    command.add_argument("--expected-trust-policy-id", required=True)
    command.add_argument("--expected-trust-policy-sha256", required=True)
    command.add_argument("--anchor-policy", required=True)
    command.add_argument("--expected-anchor-policy-id", required=True)
    command.add_argument("--expected-anchor-policy-sha256", required=True)
    command.add_argument("--verification-time")
    command.add_argument("--maximum-files", type=int,
                         default=package_tool.MAX_FILES_DEFAULT)
    command.add_argument("--maximum-expanded-bytes", type=int,
                         default=package_tool.MAX_EXPANDED_BYTES_DEFAULT)
    command.add_argument("--report")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create")
    create.add_argument("--registry", required=True)
    create.add_argument("--recovery-point-id", required=True)
    create.add_argument("--anchor", required=True)
    create.add_argument("--operator", required=True)
    create.add_argument("--created-at")
    create.add_argument("--output", required=True)
    _common_trust(create)
    create.set_defaults(handler=create_command)
    verify = commands.add_parser("verify")
    verify.add_argument("--recovery-point", required=True)
    verify.add_argument("--expected-recovery-point-sha256")
    _common_trust(verify)
    verify.set_defaults(handler=verify_command)
    restore = commands.add_parser("restore")
    restore.add_argument("--recovery-point", required=True)
    restore.add_argument("--expected-recovery-point-sha256", required=True)
    restore.add_argument("--destination", required=True)
    restore.add_argument("--restore-id", required=True)
    restore.add_argument("--operator", required=True)
    restore.add_argument("--operation-audit", required=True)
    restore.add_argument("--confirm-source-unavailable", action="store_true")
    _common_trust(restore)
    restore.set_defaults(handler=restore_command)
    return result


def main() -> int:
    args = parser().parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
