#!/usr/bin/env python3
"""Initialize, fast-forward and inspect an externally anchored read-only Registry standby."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import sys
from pathlib import Path
from typing import Any

import process_file_lease as process_lease
import team_contract_package as package_tool
import team_contract_registry as registry_tool
import team_contract_registry_recovery as recovery_tool


STATUS_PRODUCT = "PocoDDSRuntimeTeamContractRegistryStandbyStatus"
REPORT_PRODUCT = "PocoDDSRuntimeTeamContractRegistryStandbyReport"


def _trust_args(args: argparse.Namespace, registry: Path) -> argparse.Namespace:
    return argparse.Namespace(
        registry=str(registry), trust_policy=args.trust_policy,
        expected_trust_policy_id=args.expected_trust_policy_id,
        expected_trust_policy_sha256=args.expected_trust_policy_sha256,
        anchor_policy=args.anchor_policy,
        expected_anchor_policy_id=args.expected_anchor_policy_id,
        expected_anchor_policy_sha256=args.expected_anchor_policy_sha256,
        verification_time=args.verification_time,
        maximum_files=args.maximum_files,
        maximum_expanded_bytes=args.maximum_expanded_bytes,
        report=None,
    )


def _outside(path: Path, root: Path, label: str) -> None:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return
    raise ValueError(f"{label} must be outside the standby Registry")


def _recovery(args: argparse.Namespace) -> tuple[Path, str]:
    path = package_tool.resolved_path(args.recovery_point,
                                      "Registry standby recovery point")
    expected = str(args.expected_recovery_point_sha256).lower()
    if (not package_tool.SHA256.fullmatch(expected)
            or package_tool.sha256_file(path) != expected):
        raise ValueError("Registry standby recovery-point digest changed")
    return path, expected


def _marker(standby_id: str, manifest: dict[str, Any], recovery_sha: str,
            generation: int, previous_sha: str | None,
            updated_at: str | None) -> dict[str, Any]:
    document = {
        "schemaVersion": 1, "product": registry_tool.STANDBY_PRODUCT,
        "standbyId": standby_id, "registryId": manifest["registryId"],
        "sourceRecoveryPointSha256": recovery_sha,
        "appliedRevision": manifest["registryRevision"],
        "appliedStateSha256": manifest["registryStateSha256"],
        "syncGeneration": generation,
        "previousMarkerSha256": previous_sha,
        "updatedAt": registry_tool.utc_time(updated_at),
    }
    registry_tool.validate_standby_marker(document, manifest["registryId"])
    return document


def status_document(root: Path, args: argparse.Namespace) -> dict[str, Any]:
    pointer, state = registry_tool.verified_current(root, _trust_args(args, root))
    loaded = registry_tool.read_standby_marker(root, state["registryId"])
    if loaded is None:
        raise ValueError("team contract Registry is not a managed standby")
    marker, marker_sha = loaded
    if (marker["appliedRevision"] != pointer["revision"]
            or marker["appliedStateSha256"] != pointer["stateSha256"]):
        raise ValueError("Registry standby marker diverges from current state")
    return {
        "schemaVersion": 1, "product": STATUS_PRODUCT, "passed": True,
        "mode": "standby-read-only", "standbyId": marker["standbyId"],
        "registryId": state["registryId"], "revision": pointer["revision"],
        "stateSha256": pointer["stateSha256"],
        "syncGeneration": marker["syncGeneration"],
        "sourceRecoveryPointSha256": marker["sourceRecoveryPointSha256"],
        "markerSha256": marker_sha, "writable": False,
        "verifiedAt": registry_tool.utc_time(None),
    }


def validate_status(document: Any) -> None:
    fields = {
        "schemaVersion", "product", "passed", "mode", "standbyId",
        "registryId", "revision", "stateSha256", "syncGeneration",
        "sourceRecoveryPointSha256", "markerSha256", "writable", "verifiedAt",
    }
    if (not isinstance(document, dict) or set(document) != fields
            or document.get("schemaVersion") != 1
            or document.get("product") != STATUS_PRODUCT
            or document.get("passed") is not True
            or document.get("mode") != "standby-read-only"
            or document.get("writable") is not False
            or any(not package_tool.IDENTIFIER.fullmatch(str(document.get(name, "")))
                   for name in ("standbyId", "registryId"))
            or type(document.get("revision")) is not int or document["revision"] < 0
            or type(document.get("syncGeneration")) is not int
            or document["syncGeneration"] < 1
            or any(not package_tool.SHA256.fullmatch(str(document.get(name, "")))
                   for name in ("stateSha256", "sourceRecoveryPointSha256",
                                "markerSha256"))):
        raise ValueError("Registry standby status is malformed")
    package_tool.parse_time(document.get("verifiedAt"), "standby verifiedAt")


def _append_audit(path: Path, document: dict[str, Any]) -> None:
    if registry_tool.linklike(path):
        raise ValueError("Registry standby operation audit must not be a link")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(document, ensure_ascii=False,
                                separators=(",", ":")) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def _report(args: argparse.Namespace, operation: str, status: dict[str, Any],
            **values: Any) -> dict[str, Any]:
    document = {
        "schemaVersion": 1, "product": REPORT_PRODUCT, "passed": True,
        "operation": operation, "standbyId": status["standbyId"],
        "registryId": status["registryId"], "revision": status["revision"],
        "stateSha256": status["stateSha256"],
        "syncGeneration": status["syncGeneration"],
        "sourceRecoveryPointSha256": status["sourceRecoveryPointSha256"],
        "completedAt": registry_tool.utc_time(None),
    }
    document.update(values)
    validate_report(document)
    return document


def validate_report(document: Any) -> None:
    base = {
        "schemaVersion", "product", "passed", "operation", "standbyId",
        "registryId", "revision", "stateSha256", "syncGeneration",
        "sourceRecoveryPointSha256", "completedAt", "operator", "destination",
        "previousStandby",
    }
    sync = {"previousRevision", "previousStateSha256", "syncId"}
    expected = base | sync if isinstance(document, dict) \
        and document.get("operation") == "sync" else base
    if (not isinstance(document, dict) or set(document) != expected
            or document.get("schemaVersion") != 1
            or document.get("product") != REPORT_PRODUCT
            or document.get("passed") is not True
            or document.get("operation") not in {"init", "sync"}
            or any(not package_tool.IDENTIFIER.fullmatch(str(document.get(name, "")))
                   for name in ("standbyId", "registryId", "operator"))
            or type(document.get("revision")) is not int or document["revision"] < 0
            or type(document.get("syncGeneration")) is not int
            or document["syncGeneration"] < 1
            or any(not package_tool.SHA256.fullmatch(str(document.get(name, "")))
                   for name in ("stateSha256", "sourceRecoveryPointSha256"))
            or not isinstance(document.get("destination"), str)
            or not document["destination"]
            or (document.get("previousStandby") is not None
                and not isinstance(document["previousStandby"], str))):
        raise ValueError("Registry standby report is malformed")
    if document["operation"] == "sync" and (
            not package_tool.IDENTIFIER.fullmatch(str(document.get("syncId", "")))
            or type(document.get("previousRevision")) is not int
            or document["previousRevision"] < 0
            or not package_tool.SHA256.fullmatch(
                str(document.get("previousStateSha256", "")))
            or not document.get("previousStandby")):
        raise ValueError("Registry standby sync report is malformed")
    package_tool.parse_time(document.get("completedAt"), "standby completedAt")


def _write_report(args: argparse.Namespace, document: dict[str, Any]) -> None:
    if args.report:
        package_tool.write_json(Path(args.report).resolve(), document)


def init_command(args: argparse.Namespace) -> int:
    staging: Path | None = None
    published: Path | None = None
    committed = False
    try:
        if (not package_tool.IDENTIFIER.fullmatch(str(args.standby_id))
                or not package_tool.IDENTIFIER.fullmatch(str(args.operator))):
            raise ValueError("Registry standby identity is invalid")
        destination = Path(args.destination).resolve()
        if destination.exists() or destination.is_symlink():
            raise ValueError("Registry standby destination must not exist")
        recovery, recovery_sha = _recovery(args)
        audit = Path(args.operation_audit).resolve()
        _outside(audit, destination, "Registry standby operation audit")
        if args.report:
            _outside(Path(args.report).resolve(), destination,
                     "Registry standby report")
        destination.parent.mkdir(parents=True, exist_ok=True)
        staging = destination.with_name(
            f".{destination.name}.{args.standby_id}.{secrets.token_hex(8)}.new"
        )
        manifest, extracted = recovery_tool._extract_verified(
            _trust_args(args, destination), recovery, staging
        )
        registry = extracted["registry"]
        marker = _marker(
            args.standby_id, manifest, recovery_sha, 1, None, args.updated_at
        )
        registry_tool.exclusive_bytes(
            registry_tool.standby_marker_path(registry),
            package_tool.json_bytes(marker),
        )
        status = status_document(registry, args)
        validate_status(status)
        os.replace(registry, destination)
        published = destination
        shutil.rmtree(staging)
        staging = None
        status = status_document(destination, args)
        validate_status(status)
        report = _report(
            args, "init", status, operator=args.operator,
            destination=str(destination), previousStandby=None,
        )
        _append_audit(audit, report)
        committed = True
        published = None
        _write_report(args, report)
        print("PDR_TEAM_CONTRACT_REGISTRY_STANDBY_INIT_PASS "
              f"revision={status['revision']} generation=1")
        return 0
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)
        if published is not None:
            shutil.rmtree(published, ignore_errors=True)
        marker = "COMMITTED_ERROR" if committed else "ERROR"
        print(f"PDR_TEAM_CONTRACT_REGISTRY_STANDBY_{marker}: {error}",
              file=sys.stderr)
        return 3 if committed else 2


def sync_command(args: argparse.Namespace) -> int:
    staging: Path | None = None
    backup: Path | None = None
    new_published = False
    committed = False
    try:
        if not args.confirm_standby_stopped:
            raise ValueError("Registry standby sync requires --confirm-standby-stopped")
        if any(not package_tool.IDENTIFIER.fullmatch(str(value)) for value in (
                args.standby_id, args.sync_id, args.operator)):
            raise ValueError("Registry standby sync identity is invalid")
        if (args.expected_revision < 0 or args.expected_sync_generation < 1
                or not package_tool.SHA256.fullmatch(
                    str(args.expected_state_sha256).lower())):
            raise ValueError("Registry standby sync baseline is invalid")
        destination = registry_tool.registry_root(args.destination)
        previous_output = Path(args.previous_output).resolve()
        if (previous_output.exists() or previous_output.is_symlink()
                or previous_output.parent != destination.parent
                or previous_output == destination):
            raise ValueError(
                "Registry standby previous output must be an absent sibling path"
            )
        audit = Path(args.operation_audit).resolve()
        _outside(audit, destination, "Registry standby operation audit")
        recovery, recovery_sha = _recovery(args)
        lease = process_lease.ProcessFileLease(
            destination.parent / f".{destination.name}.standby-sync.lock",
            destination.parent / f".{destination.name}.standby-sync.epoch.json",
            "team-contract-registry-standby-sync",
            {"standbyId": args.standby_id, "operator": args.operator},
        )
        with lease:
            lease.assert_current()
            current = status_document(destination, args)
            validate_status(current)
            if (current["standbyId"] != args.standby_id
                    or current["revision"] != args.expected_revision
                    or current["stateSha256"]
                        != str(args.expected_state_sha256).lower()
                    or current["syncGeneration"] != args.expected_sync_generation):
                raise ValueError("Registry standby sync baseline changed")
            current_marker = registry_tool.read_standby_marker(
                destination, current["registryId"]
            )
            if current_marker is None:
                raise ValueError("Registry standby marker disappeared")
            staging = destination.with_name(
                f".{destination.name}.{args.sync_id}.{secrets.token_hex(8)}.new"
            )
            manifest, extracted = recovery_tool._extract_verified(
                _trust_args(args, destination), recovery, staging
            )
            candidate = extracted["registry"]
            if (manifest["registryId"] != current["registryId"]
                    or manifest["registryRevision"] <= current["revision"]):
                raise ValueError("Registry standby sync is not a newer same-identity state")
            predecessor = registry_tool.state_path(
                candidate, current["revision"], current["stateSha256"]
            )
            if (not predecessor.is_file()
                    or package_tool.sha256_file(predecessor)
                    != current["stateSha256"]):
                raise ValueError("Registry standby candidate does not fast-forward current state")
            marker = _marker(
                args.standby_id, manifest, recovery_sha,
                current["syncGeneration"] + 1, current_marker[1], args.updated_at,
            )
            registry_tool.exclusive_bytes(
                registry_tool.standby_marker_path(candidate),
                package_tool.json_bytes(marker),
            )
            candidate_status = status_document(candidate, args)
            validate_status(candidate_status)
            lease.assert_current()
            backup = destination.with_name(
                f".{destination.name}.{args.sync_id}.{secrets.token_hex(8)}.previous"
            )
            os.replace(destination, backup)
            os.replace(candidate, destination)
            new_published = True
            final = status_document(destination, args)
            validate_status(final)
            if final["markerSha256"] != package_tool.sha256_bytes(
                    package_tool.json_bytes(marker)):
                raise ValueError("Registry standby final marker changed")
            os.replace(backup, previous_output)
            backup = None
            shutil.rmtree(staging)
            staging = None
            report = _report(
                args, "sync", final, operator=args.operator,
                destination=str(destination), previousStandby=str(previous_output),
                previousRevision=current["revision"],
                previousStateSha256=current["stateSha256"], syncId=args.sync_id,
            )
            _append_audit(audit, report)
            committed = True
            _write_report(args, report)
        print("PDR_TEAM_CONTRACT_REGISTRY_STANDBY_SYNC_PASS "
              f"revision={final['revision']} generation={final['syncGeneration']}")
        return 0
    except (OSError, UnicodeError, ValueError, RuntimeError,
            json.JSONDecodeError) as error:
        if new_published and backup is not None:
            failed = destination.with_name(
                f".{destination.name}.failed.{secrets.token_hex(8)}"
            )
            try:
                os.replace(destination, failed)
                os.replace(backup, destination)
                shutil.rmtree(failed, ignore_errors=True)
                backup = None
            except OSError:
                pass
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)
        if backup is not None and not destination.exists():
            try:
                os.replace(backup, destination)
            except OSError:
                pass
        marker = "COMMITTED_ERROR" if committed else "ERROR"
        print(f"PDR_TEAM_CONTRACT_REGISTRY_STANDBY_{marker}: {error}",
              file=sys.stderr)
        return 3 if committed else 2


def status_command(args: argparse.Namespace) -> int:
    try:
        root = registry_tool.registry_root(args.registry)
        status = status_document(root, args)
        validate_status(status)
        if args.report:
            package_tool.write_json(Path(args.report).resolve(), status)
        print("PDR_TEAM_CONTRACT_REGISTRY_STANDBY_STATUS_PASS "
              f"revision={status['revision']} generation={status['syncGeneration']}")
        return 0
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        print(f"PDR_TEAM_CONTRACT_REGISTRY_STANDBY_ERROR: {error}", file=sys.stderr)
        return 2


def _trust(command: argparse.ArgumentParser) -> None:
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
    init = commands.add_parser("init")
    init.add_argument("--recovery-point", required=True)
    init.add_argument("--expected-recovery-point-sha256", required=True)
    init.add_argument("--destination", required=True)
    init.add_argument("--standby-id", required=True)
    init.add_argument("--operator", required=True)
    init.add_argument("--operation-audit", required=True)
    init.add_argument("--updated-at")
    _trust(init)
    init.set_defaults(handler=init_command)
    sync = commands.add_parser("sync")
    sync.add_argument("--recovery-point", required=True)
    sync.add_argument("--expected-recovery-point-sha256", required=True)
    sync.add_argument("--destination", required=True)
    sync.add_argument("--standby-id", required=True)
    sync.add_argument("--sync-id", required=True)
    sync.add_argument("--operator", required=True)
    sync.add_argument("--operation-audit", required=True)
    sync.add_argument("--previous-output", required=True)
    sync.add_argument("--expected-revision", type=int, required=True)
    sync.add_argument("--expected-state-sha256", required=True)
    sync.add_argument("--expected-sync-generation", type=int, required=True)
    sync.add_argument("--confirm-standby-stopped", action="store_true")
    sync.add_argument("--updated-at")
    _trust(sync)
    sync.set_defaults(handler=sync_command)
    status = commands.add_parser("status")
    status.add_argument("--registry", required=True)
    _trust(status)
    status.set_defaults(handler=status_command)
    return result


def main() -> int:
    args = parser().parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
