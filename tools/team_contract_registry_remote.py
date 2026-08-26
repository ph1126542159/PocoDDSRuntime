#!/usr/bin/env python3
"""Expose the immutable team-contract Registry through a scoped remote protocol."""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import shutil
import ssl
import sys
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import team_contract_impact as impact_tool
import team_contract_package as package_tool
import team_contract_registry as registry_tool
import team_contract_registry_access_policy as access_policy_tool
import team_contract_registry_audit_archive as audit_archive_tool
import process_file_lease as process_lease


ACCESS_POLICY_PRODUCT = access_policy_tool.POLICY_PRODUCT
COMMAND_PRODUCT = "PocoDDSRuntimeTeamContractRegistryRemoteCommand"
RESPONSE_PRODUCT = "PocoDDSRuntimeTeamContractRegistryRemoteResponse"
STATUS_PRODUCT = "PocoDDSRuntimeTeamContractRegistryRemoteRequestStatus"
RECOVERY_PRODUCT = "PocoDDSRuntimeTeamContractRegistryRemoteRecovery"
RECOVERY_RESPONSE_PRODUCT = "PocoDDSRuntimeTeamContractRegistryRemoteRecoveryResponse"
REMOTE_DRAIN_COMMAND_PRODUCT = \
    "PocoDDSRuntimeTeamContractRegistryRemoteDrainCommand"
REMOTE_DRAIN_RESPONSE_PRODUCT = \
    "PocoDDSRuntimeTeamContractRegistryRemoteDrainResponse"
AUDIT_RECORD_PRODUCT = "PocoDDSRuntimeTeamContractRegistryRemoteAuditRecord"
AUDIT_HEAD_PRODUCT = "PocoDDSRuntimeTeamContractRegistryRemoteAuditHead"
AUDIT_ACTIVATION_PRODUCT = "PocoDDSRuntimeTeamContractRegistryRemoteAuditActivation"
AUDIT_VERIFICATION_PRODUCT = \
    "PocoDDSRuntimeTeamContractRegistryRemoteAuditVerification"
AUDIT_CHECKPOINT_PRODUCT = \
    "PocoDDSRuntimeTeamContractRegistryRemoteAuditCheckpoint"
AUDIT_POLICY_PRODUCT = "PocoDDSRuntimeTeamContractRegistryRemoteAuditPolicy"
LEASE_STATUS_PRODUCT = "PocoDDSRuntimeTeamContractRegistryRemoteLeaseStatus"
ROLES = access_policy_tool.ROLES
MUTATIONS = {"publish", "promote", "rollback"}
OPERATIONS = MUTATIONS | {"verify", "resolve"}
ARTIFACT_NAMES = {
    "package", "lock", "impactGate", "runnerAttestation", "gateAuthorization"
}
REQUEST_STATES = {"pending", "completed", "aborted", "uncertain"}
AUDIT_EVENT_TYPES = {
    "request-started", "request-completed", "request-recovered", "policy-reloaded",
    "handoff-draining", "handoff-completed", "handoff-resumed",
}


def canonical_sha(document: dict[str, Any]) -> str:
    return package_tool.sha256_bytes(package_tool.canonical_bytes(document))


def load_access_policy(path: str | Path, expected_id: str,
                       expected_sha: str) -> tuple[dict[str, Any], str]:
    policy, actual_sha, _, _ = access_policy_tool.load_policy_bytes(path)
    if (not package_tool.SHA256.fullmatch(str(expected_sha).lower())
            or actual_sha != str(expected_sha).lower()
            or policy.get("policyId") != expected_id):
        raise ValueError("Registry remote access policy identity is not pinned")
    return policy, actual_sha


def validate_access_policy(policy: dict[str, Any]) -> None:
    access_policy_tool.validate_policy(policy)


def authenticate(policy: dict[str, Any], header: str | None,
                 at: Any) -> dict[str, Any]:
    if not header or not header.startswith("Bearer "):
        raise PermissionError("missing remote Registry credential")
    token = header[7:]
    if len(token) < 32 or len(token) > 512 or any(ord(char) < 33 for char in token):
        raise PermissionError("invalid remote Registry credential")
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    if digest in policy["revokedTokenSha256"]:
        raise PermissionError("revoked remote Registry credential")
    matches = [principal for principal in policy["principals"]
               if hmac.compare_digest(principal["tokenSha256"], digest)]
    if len(matches) != 1:
        raise PermissionError("untrusted remote Registry credential")
    principal = matches[0]
    if (at < package_tool.parse_time(principal["notBefore"], "principal notBefore")
            or at >= package_tool.parse_time(principal["notAfter"], "principal notAfter")):
        raise PermissionError("remote Registry credential is outside its validity window")
    return principal


def validate_command(command: Any) -> None:
    fields = {
        "schemaVersion", "product", "operation", "registryId", "expectedRevision",
        "parameters", "artifacts",
    }
    if (not isinstance(command, dict) or set(command) != fields
            or command.get("schemaVersion") != 1 or command.get("product") != COMMAND_PRODUCT
            or command.get("operation") not in OPERATIONS
            or not package_tool.IDENTIFIER.fullmatch(str(command.get("registryId", "")))
            or (command.get("expectedRevision") is not None
                and (type(command["expectedRevision"]) is not int
                     or command["expectedRevision"] < 0))
            or not isinstance(command.get("parameters"), dict)
            or not isinstance(command.get("artifacts"), dict)
            or len(command["artifacts"]) > len(ARTIFACT_NAMES)
            or any(name not in ARTIFACT_NAMES for name in command["artifacts"])):
        raise ValueError("remote Registry command is malformed")
    operation = command["operation"]
    parameter_fields = {
        "publish": set(),
        "promote": {"channel", "expectedGeneration"},
        "rollback": {"channel", "expectedGeneration", "toGeneration", "reason"},
        "verify": set(),
        "resolve": {"channel"},
    }[operation]
    artifact_fields = {
        "publish": {"package"},
        "promote": {"lock"},
        "rollback": set(),
        "verify": set(),
        "resolve": set(),
    }[operation]
    if set(command["parameters"]) != parameter_fields:
        raise ValueError("remote Registry command parameters do not match its operation")
    if operation == "promote":
        extras = {"impactGate", "runnerAttestation", "gateAuthorization"}
        if set(command["artifacts"]) not in ({"lock"}, {"lock"} | extras):
            raise ValueError("remote Registry promotion evidence is incomplete")
    elif set(command["artifacts"]) != artifact_fields:
        raise ValueError("remote Registry command artifacts do not match its operation")
    parameters = command["parameters"]
    if "channel" in parameters and not package_tool.IDENTIFIER.fullmatch(
            str(parameters["channel"])):
        raise ValueError("remote Registry channel is invalid")
    for name in ("expectedGeneration", "toGeneration"):
        if name in parameters and (type(parameters[name]) is not int or parameters[name] < 0):
            raise ValueError(f"remote Registry {name} is invalid")
    if "reason" in parameters and (not isinstance(parameters["reason"], str)
                                    or not 1 <= len(parameters["reason"]) <= 512):
        raise ValueError("remote Registry rollback reason is invalid")
    if operation in MUTATIONS and command["expectedRevision"] is None:
        raise ValueError("remote Registry mutation requires expectedRevision")
    for artifact in command["artifacts"].values():
        if (not isinstance(artifact, dict) or set(artifact) != {"sha256", "dataBase64"}
                or not package_tool.SHA256.fullmatch(str(artifact.get("sha256", "")))
                or not isinstance(artifact.get("dataBase64"), str)
                or not artifact["dataBase64"]):
            raise ValueError("remote Registry artifact envelope is malformed")


def validate_remote_drain_command(document: Any) -> None:
    fields = {
        "schemaVersion", "product", "registryId", "operation", "handoffId",
        "expectedGeneration", "expectedRevision", "expectedStateSha256",
        "reason", "issuedAt", "expiresAt",
    }
    if (not isinstance(document, dict) or set(document) != fields
            or document.get("schemaVersion") != 1
            or document.get("product") != REMOTE_DRAIN_COMMAND_PRODUCT
            or not package_tool.IDENTIFIER.fullmatch(
                str(document.get("registryId", "")))
            or document.get("operation") not in {"start", "finalize", "resume"}
            or not package_tool.IDENTIFIER.fullmatch(
                str(document.get("handoffId", "")))
            or type(document.get("expectedGeneration")) is not int
            or document["expectedGeneration"] < 0
            or type(document.get("expectedRevision")) is not int
            or document["expectedRevision"] < 0
            or not package_tool.SHA256.fullmatch(
                str(document.get("expectedStateSha256", "")))):
        raise ValueError("remote Registry drain command is malformed")
    operation = document["operation"]
    if operation in {"start", "resume"}:
        if (not isinstance(document.get("reason"), str)
                or not 1 <= len(document["reason"]) <= 512
                or document.get("issuedAt") is not None
                or document.get("expiresAt") is not None):
            raise ValueError("remote Registry drain reason or time fields are malformed")
    else:
        if (document.get("reason") is not None
                or not isinstance(document.get("issuedAt"), str)
                or not isinstance(document.get("expiresAt"), str)):
            raise ValueError("remote Registry drain finalize fields are malformed")
        issued = package_tool.parse_time(document["issuedAt"], "handoff issuedAt")
        expires = package_tool.parse_time(document["expiresAt"], "handoff expiresAt")
        if issued >= expires or (expires - issued).total_seconds() > 60 * 60:
            raise ValueError("remote Registry handoff lifetime is malformed")


def required_role(operation: str) -> str:
    return {
        "publish": "publisher", "promote": "promoter", "rollback": "rollback",
        "verify": "reader", "resolve": "reader",
    }[operation]


def authorize(principal: dict[str, Any], command: dict[str, Any]) -> None:
    operation = command["operation"]
    if required_role(operation) not in principal["roles"]:
        raise PermissionError("remote Registry role does not permit this operation")
    channel = command["parameters"].get("channel")
    if channel is not None and operation in {"promote", "rollback"} \
            and channel not in principal["channels"]:
        raise PermissionError("remote Registry principal does not own this channel")


def decode_artifacts(command: dict[str, Any], directory: Path,
                     maximum_bytes: int) -> dict[str, Path]:
    result: dict[str, Path] = {}
    total = 0
    for name, envelope in command["artifacts"].items():
        try:
            content = base64.b64decode(envelope["dataBase64"], validate=True)
        except (ValueError, TypeError) as error:
            raise ValueError(f"remote Registry {name} artifact is not valid base64") from error
        total += len(content)
        if total > maximum_bytes:
            raise ValueError("remote Registry expanded artifact capacity exceeded")
        if package_tool.sha256_bytes(content) != envelope["sha256"]:
            raise ValueError(f"remote Registry {name} artifact SHA-256 changed")
        path = directory / f"{name}.bin"
        path.write_bytes(content)
        result[name] = path
    return result


class ControlLease(process_lease.ProcessFileLease):
    def __init__(self, root: Path) -> None:
        super().__init__(
            root / ".command.lock",
            root / ".command.epoch.json",
            "team-contract-registry-command-processor",
            {"operation": "remote-control-transaction"},
        )

    def acquire(self) -> "ControlLease":
        try:
            super().acquire()
            return self
        except process_lease.LeaseBusyError as error:
            raise RuntimeError("remote Registry command processor is already active") from error
        except ValueError as error:
            raise RuntimeError(
                "remote Registry command lease fencing state is invalid"
            ) from error

    def assert_current(self) -> None:
        try:
            super().assert_current()
        except ValueError as error:
            raise RuntimeError(
                "remote Registry command processor was fenced or its epoch is invalid"
            ) from error


def request_record_path(control: Path, request_id: str) -> Path:
    digest = hashlib.sha256(request_id.encode("utf-8")).hexdigest()
    return control / "requests" / digest[:2] / f"{digest}.json"


def recovery_record_path(control: Path, recovery_id: str) -> Path:
    digest = hashlib.sha256(recovery_id.encode("utf-8")).hexdigest()
    return control / "recoveries" / digest[:2] / f"{digest}.json"


def audit_head_path(control: Path) -> Path:
    return registry_tool.safe_member(control, "audit/head.json", "remote audit head")


def audit_record_path(control: Path, sequence: int, digest: str) -> Path:
    return registry_tool.safe_member(
        control,
        f"audit/records/{sequence:020d}-{digest}.json",
        "remote audit record",
    )


def audit_activation_path(control: Path) -> Path:
    return registry_tool.safe_member(
        control, "audit/activation.json", "remote audit activation"
    )


def validate_audit_head(head: Any, registry_id: str | None = None) -> None:
    if (not isinstance(head, dict) or set(head) != {
            "schemaVersion", "product", "registryId", "sequence",
            "lastRecordSha256", "updatedAt",
        } or head.get("schemaVersion") != 1
            or head.get("product") != AUDIT_HEAD_PRODUCT
            or not package_tool.IDENTIFIER.fullmatch(str(head.get("registryId", "")))
            or (registry_id is not None and head["registryId"] != registry_id)
            or type(head.get("sequence")) is not int or head["sequence"] < 0
            or (head.get("lastRecordSha256") is not None
                and not package_tool.SHA256.fullmatch(
                    str(head["lastRecordSha256"])))):
        raise ValueError("remote Registry audit head is malformed")
    if (head["sequence"] == 0) != (head["lastRecordSha256"] is None):
        raise ValueError("remote Registry audit head sequence is inconsistent")
    package_tool.parse_time(head.get("updatedAt"), "remote audit head updatedAt")


def validate_audit_record(record: Any, registry_id: str | None = None) -> None:
    fields = {
        "schemaVersion", "product", "registryId", "sequence",
        "previousRecordSha256", "eventType", "requestId", "requestSha256",
        "principalId", "operation", "startedRevision", "finalRevision",
        "finalStateSha256", "outcome", "responseSha256", "recoveryId",
        "reason", "occurredAt",
    }
    nullable_ids = (record.get("requestId"), record.get("principalId"),
                    record.get("operation"), record.get("recoveryId")) \
        if isinstance(record, dict) else (None,)
    nullable_hashes = (record.get("previousRecordSha256"),
                       record.get("requestSha256"),
                       record.get("finalStateSha256"),
                       record.get("responseSha256")) \
        if isinstance(record, dict) else (None,)
    if (not isinstance(record, dict) or set(record) != fields
            or record.get("schemaVersion") != 1
            or record.get("product") != AUDIT_RECORD_PRODUCT
            or not package_tool.IDENTIFIER.fullmatch(str(record.get("registryId", "")))
            or (registry_id is not None and record["registryId"] != registry_id)
            or type(record.get("sequence")) is not int or record["sequence"] < 1
            or record.get("eventType") not in AUDIT_EVENT_TYPES
            or any(value is not None and not package_tool.IDENTIFIER.fullmatch(str(value))
                   for value in nullable_ids)
            or any(value is not None and not package_tool.SHA256.fullmatch(str(value))
                   for value in nullable_hashes)
            or any(value is not None and (type(value) is not int or value < 0)
                   for value in (record.get("startedRevision"),
                                 record.get("finalRevision")))
            or record.get("outcome") not in REQUEST_STATES
            or (record.get("reason") is not None
                and (not isinstance(record["reason"], str)
                     or not 1 <= len(record["reason"]) <= 512))):
        raise ValueError("remote Registry audit record is malformed")
    package_tool.parse_time(record.get("occurredAt"), "remote audit record occurredAt")


def ensure_audit_head(control: Path, registry_id: str) -> dict[str, Any]:
    path = audit_head_path(control)
    if path.is_file():
        head = json.loads(path.read_bytes())
        validate_audit_head(head, registry_id)
        return head
    if audit_activation_path(control).is_file():
        raise ValueError("remote Registry audit head is missing after audit activation")
    records_root = control / "audit" / "records"
    if records_root.is_dir() and any(records_root.glob("*.json")):
        raise ValueError("remote Registry audit head is missing for existing records")
    requests_root = control / "requests"
    if requests_root.is_dir():
        for request_path in requests_root.rglob("*.json"):
            try:
                request = json.loads(request_path.read_bytes())
            except (OSError, UnicodeError, json.JSONDecodeError) as error:
                raise ValueError("remote Registry request record is invalid JSON") from error
            if isinstance(request, dict) and request.get("lastAuditRecordSha256"):
                raise ValueError("remote Registry audit head is missing after audit activation")
    head = {
        "schemaVersion": 1,
        "product": AUDIT_HEAD_PRODUCT,
        "registryId": registry_id,
        "sequence": 0,
        "lastRecordSha256": None,
        "updatedAt": registry_tool.utc_time(None),
    }
    registry_tool.exclusive_bytes(path, package_tool.json_bytes(head))
    return head


def verify_audit_chain(control: Path, registry_id: str,
                       allow_unlinked_request_id: str | None = None,
                       archive_directory: str | Path | None = None) -> dict[str, Any]:
    head = ensure_audit_head(control, registry_id)
    archived = audit_archive_tool.load_registered_archives(
        control, archive_directory, registry_id, validate_audit_record
    )
    records_root = registry_tool.safe_member(
        control, "audit/records", "remote audit records"
    )
    paths = sorted(records_root.glob("*.json")) if records_root.is_dir() else []
    previous: str | None = archived["baseRecordSha256"]
    expected_sequence = archived["baseSequence"] + 1
    record_digests: set[str] = set(archived["recordsByDigest"])
    records_by_digest: dict[str, dict[str, Any]] = dict(
        archived["recordsByDigest"]
    )
    for path in paths:
        if path.is_symlink() or not path.is_file():
            raise ValueError("remote Registry audit record must be a regular file")
        content = path.read_bytes()
        digest = package_tool.sha256_bytes(content)
        try:
            record = json.loads(content)
        except (UnicodeError, json.JSONDecodeError) as error:
            raise ValueError("remote Registry audit record is invalid JSON") from error
        validate_audit_record(record, registry_id)
        sequence = record["sequence"]
        if path.name != f"{sequence:020d}-{digest}.json":
            raise ValueError("remote Registry audit record filename or sequence changed")
        if sequence <= archived["baseSequence"]:
            archived_record = archived["recordsBySequence"].get(sequence)
            if (archived_record is None or archived_record[0] != digest
                    or archived_record[2] != content):
                raise ValueError("online audit prefix differs from registered archive")
            continue
        if (sequence != expected_sequence
                or record["previousRecordSha256"] != previous):
            raise ValueError("remote Registry audit chain linkage changed")
        previous = digest
        expected_sequence += 1
        record_digests.add(digest)
        records_by_digest[digest] = record
    if (head["sequence"] != expected_sequence - 1
            or head["lastRecordSha256"] != previous):
        raise ValueError("remote Registry audit head does not match immutable records")
    requests_root = registry_tool.safe_member(
        control, "requests", "remote request records"
    )
    activation = audit_activation_path(control)
    strict_request_links = activation.is_file()
    if strict_request_links:
        activation_document = json.loads(activation.read_bytes())
        if (not isinstance(activation_document, dict)
                or set(activation_document) != {
                    "schemaVersion", "product", "registryId", "activatedAt",
                } or activation_document.get("schemaVersion") != 1
                or activation_document.get("product") != AUDIT_ACTIVATION_PRODUCT
                or activation_document.get("registryId") != registry_id):
            raise ValueError("remote Registry audit activation marker is malformed")
        package_tool.parse_time(
            activation_document.get("activatedAt"), "remote audit activatedAt"
        )
    if requests_root.is_dir():
        for request_path in requests_root.rglob("*.json"):
            if request_path.is_symlink():
                raise ValueError("remote Registry request record must not be a link")
            try:
                request = json.loads(request_path.read_bytes())
            except (UnicodeError, json.JSONDecodeError) as error:
                raise ValueError("remote Registry request record is invalid JSON") from error
            if not isinstance(request, dict):
                raise ValueError("remote Registry request record is malformed")
            if (strict_request_links and request.get("lastAuditRecordSha256") is None
                    and request.get("requestId") != allow_unlinked_request_id):
                raise ValueError(
                    "remote Registry request is missing its immutable audit link"
                )
            for field in ("lastAuditRecordSha256", "completionAuditRecordSha256"):
                digest = request.get(field)
                if digest is not None and digest not in record_digests:
                    raise ValueError(
                        "remote Registry request points outside its immutable audit chain"
                    )
                if (digest is not None
                        and records_by_digest[digest]["requestId"] != request.get("requestId")):
                    raise ValueError(
                        "remote Registry request audit identity linkage changed"
                    )
            if strict_request_links and request.get("requestId") \
                    != allow_unlinked_request_id:
                last_digest = request.get("lastAuditRecordSha256")
                last = records_by_digest.get(last_digest)
                status = request.get("status")
                expected_event = {
                    "pending": "request-started",
                    "completed": "request-completed",
                    "aborted": "request-recovered",
                    "uncertain": "request-recovered",
                }.get(status)
                if (last is None or last.get("eventType") != expected_event
                        or last.get("outcome") != status):
                    raise ValueError(
                        "remote Registry request status diverges from its audit transition"
                    )
                if (status == "completed"
                        and request.get("completionAuditRecordSha256") != last_digest):
                    raise ValueError(
                        "remote Registry completed request lost its completion audit link"
                    )
    return {
        "schemaVersion": 1,
        "product": AUDIT_VERIFICATION_PRODUCT,
        "passed": True,
        "registryId": registry_id,
        "sequence": head["sequence"],
        "lastRecordSha256": head["lastRecordSha256"],
        "headSha256": package_tool.sha256_bytes(package_tool.json_bytes(head)),
        "verifiedAt": registry_tool.utc_time(None),
    }


def append_audit_record(control: Path, registry_id: str, event_type: str,
                        archive_directory: str | Path | None = None,
                        **values: Any) -> tuple[dict[str, Any], str]:
    verification = verify_audit_chain(
        control, registry_id, values.get("request_id"), archive_directory
    )
    sequence = verification["sequence"] + 1
    record = {
        "schemaVersion": 1,
        "product": AUDIT_RECORD_PRODUCT,
        "registryId": registry_id,
        "sequence": sequence,
        "previousRecordSha256": verification["lastRecordSha256"],
        "eventType": event_type,
        "requestId": values.get("request_id"),
        "requestSha256": values.get("request_sha"),
        "principalId": values.get("principal_id"),
        "operation": values.get("operation"),
        "startedRevision": values.get("started_revision"),
        "finalRevision": values.get("final_revision"),
        "finalStateSha256": values.get("final_state_sha"),
        "outcome": values.get("outcome"),
        "responseSha256": values.get("response_sha"),
        "recoveryId": values.get("recovery_id"),
        "reason": values.get("reason"),
        "occurredAt": registry_tool.utc_time(None),
    }
    validate_audit_record(record, registry_id)
    content = package_tool.json_bytes(record)
    digest = package_tool.sha256_bytes(content)
    registry_tool.exclusive_bytes(audit_record_path(control, sequence, digest), content)
    head = {
        "schemaVersion": 1,
        "product": AUDIT_HEAD_PRODUCT,
        "registryId": registry_id,
        "sequence": sequence,
        "lastRecordSha256": digest,
        "updatedAt": record["occurredAt"],
    }
    package_tool.write_json(audit_head_path(control), head)
    return record, digest


def activate_audit(control: Path, registry_id: str,
                   archive_directory: str | Path | None = None) -> None:
    path = audit_activation_path(control)
    if path.is_file():
        verify_audit_chain(control, registry_id, archive_directory=archive_directory)
        return
    marker = {
        "schemaVersion": 1,
        "product": AUDIT_ACTIVATION_PRODUCT,
        "registryId": registry_id,
        "activatedAt": registry_tool.utc_time(None),
    }
    registry_tool.exclusive_bytes(path, package_tool.json_bytes(marker))
    verify_audit_chain(control, registry_id, archive_directory=archive_directory)


def configured_audit_archive_directory(settings: argparse.Namespace) -> str | None:
    value = getattr(settings, "audit_archive_directory", None)
    return str(Path(value).resolve()) if value else None


def configured_handoff_evidence_directory(settings: argparse.Namespace) -> Path:
    value = getattr(settings, "handoff_evidence_directory", None)
    if not value:
        raise ValueError("remote Registry handoff control is not configured")
    return Path(value).resolve()


def same_or_child(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def validate_audit_policy(policy: Any) -> None:
    fields = {"schemaVersion", "product", "policyId", "auditors", "revokedKeys"}
    if (not isinstance(policy, dict) or set(policy) != fields
            or policy.get("schemaVersion") != 1
            or policy.get("product") != AUDIT_POLICY_PRODUCT
            or not package_tool.IDENTIFIER.fullmatch(str(policy.get("policyId", "")))
            or not isinstance(policy.get("auditors"), list) or not policy["auditors"]
            or len(policy["auditors"]) > 64
            or not isinstance(policy.get("revokedKeys"), list)
            or len(policy["revokedKeys"]) > 64):
        raise ValueError("remote Registry audit policy is malformed")
    auditor_fields = {
        "auditorId", "keyId", "algorithm", "publicKey", "publicKeySha256",
        "registryIds", "notBefore", "notAfter",
    }
    identities: set[tuple[str, str]] = set()
    for auditor in policy["auditors"]:
        identity = (str(auditor.get("auditorId", "")),
                    str(auditor.get("keyId", ""))) \
            if isinstance(auditor, dict) else ("", "")
        if (not isinstance(auditor, dict) or set(auditor) != auditor_fields
                or any(not package_tool.IDENTIFIER.fullmatch(value) for value in identity)
                or identity in identities or auditor.get("algorithm") != "Ed25519"
                or not isinstance(auditor.get("publicKey"), str)
                or Path(auditor["publicKey"]).is_absolute()
                or len(Path(auditor["publicKey"]).parts) != 2
                or Path(auditor["publicKey"]).parts[0] != "keys"
                or not package_tool.SHA256.fullmatch(
                    str(auditor.get("publicKeySha256", "")))
                or not isinstance(auditor.get("registryIds"), list)
                or not auditor["registryIds"] or len(auditor["registryIds"]) > 128
                or len(auditor["registryIds"]) != len(set(auditor["registryIds"]))
                or any(not package_tool.IDENTIFIER.fullmatch(str(value))
                       for value in auditor["registryIds"])):
            raise ValueError("remote Registry audit policy auditor is malformed")
        before = package_tool.parse_time(auditor["notBefore"], "auditor notBefore")
        after = package_tool.parse_time(auditor["notAfter"], "auditor notAfter")
        if before >= after:
            raise ValueError("remote Registry audit policy validity is reversed")
        identities.add(identity)
    revoked_fields = {"keyId", "revokedAt", "reason"}
    revoked_ids: set[str] = set()
    for revoked in policy["revokedKeys"]:
        if (not isinstance(revoked, dict) or set(revoked) != revoked_fields
                or not package_tool.IDENTIFIER.fullmatch(str(revoked.get("keyId", "")))
                or revoked["keyId"] in revoked_ids
                or not isinstance(revoked.get("reason"), str)
                or not 1 <= len(revoked["reason"]) <= 512):
            raise ValueError("remote Registry audit policy revocation is malformed")
        package_tool.parse_time(revoked["revokedAt"], "audit key revokedAt")
        revoked_ids.add(revoked["keyId"])


def audit_checkpoint_payload(checkpoint: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in checkpoint.items() if key != "signature"}


def audit_checkpoint_create_command(args: argparse.Namespace) -> int:
    try:
        control = Path(args.control_directory).resolve()
        output = Path(args.output).resolve()
        if same_or_child(output, control):
            raise ValueError("remote audit checkpoint must be stored outside control state")
        archive_directory = getattr(args, "audit_archive_directory", None)
        verification = verify_audit_chain(
            control, args.registry_id, archive_directory=archive_directory
        )
        if verification["sequence"] < 1:
            raise ValueError("remote Registry audit chain has no record to checkpoint")
        key_value = os.environ.get(args.private_key_environment)
        if not key_value:
            raise ValueError("remote audit checkpoint private key environment is unset")
        key_path = Path(key_value).resolve()
        if same_or_child(key_path, control):
            raise ValueError("remote audit checkpoint private key must be externally stored")
        passphrase = None
        if args.private_key_passphrase_environment:
            value = os.environ.get(args.private_key_passphrase_environment)
            if value is None:
                raise ValueError("remote audit checkpoint passphrase environment is unset")
            passphrase = value.encode("utf-8")
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
            from cryptography.hazmat.primitives.serialization import load_pem_private_key
        except ImportError as error:
            raise ValueError("remote audit checkpoint requires cryptography") from error
        key = load_pem_private_key(key_path.read_bytes(), password=passphrase)
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError("remote audit checkpoint private key is not Ed25519")
        checkpoint = {
            "schemaVersion": 1,
            "product": AUDIT_CHECKPOINT_PRODUCT,
            "checkpointId": args.checkpoint_id,
            "auditorId": args.auditor_id,
            "registryId": args.registry_id,
            "auditSequence": verification["sequence"],
            "auditRecordSha256": verification["lastRecordSha256"],
            "auditHeadSha256": verification["headSha256"],
            "issuedAt": registry_tool.utc_time(args.issued_at),
            "keyId": args.key_id,
        }
        if any(not package_tool.IDENTIFIER.fullmatch(str(checkpoint[name]))
               for name in ("checkpointId", "auditorId", "registryId", "keyId")):
            raise ValueError("remote audit checkpoint identity is invalid")
        checkpoint["signature"] = base64.b64encode(
            key.sign(package_tool.canonical_bytes(checkpoint))
        ).decode("ascii")
        registry_tool.exclusive_bytes(output, package_tool.json_bytes(checkpoint))
        print(
            "PDR_TEAM_CONTRACT_REGISTRY_REMOTE_AUDIT_CHECKPOINT_PASS "
            f"sequence={checkpoint['auditSequence']} output={output}"
        )
        return 0
    except (OSError, UnicodeError, ValueError) as error:
        print(f"PDR_TEAM_CONTRACT_REGISTRY_REMOTE_ERROR: {error}", file=sys.stderr)
        return 2


def audit_checkpoint_verify_command(args: argparse.Namespace) -> int:
    try:
        control = Path(args.control_directory).resolve()
        checkpoint_path = package_tool.resolved_path(
            args.checkpoint, "remote audit checkpoint"
        )
        if same_or_child(checkpoint_path, control):
            raise ValueError("remote audit checkpoint must be externally stored")
        checkpoint = json.loads(checkpoint_path.read_bytes())
        fields = {
            "schemaVersion", "product", "checkpointId", "auditorId", "registryId",
            "auditSequence", "auditRecordSha256", "auditHeadSha256", "issuedAt",
            "keyId", "signature",
        }
        if (not isinstance(checkpoint, dict) or set(checkpoint) != fields
                or checkpoint.get("schemaVersion") != 1
                or checkpoint.get("product") != AUDIT_CHECKPOINT_PRODUCT
                or checkpoint.get("registryId") != args.registry_id
                or any(not package_tool.IDENTIFIER.fullmatch(str(checkpoint.get(name, "")))
                       for name in ("checkpointId", "auditorId", "registryId", "keyId"))
                or type(checkpoint.get("auditSequence")) is not int
                or checkpoint["auditSequence"] < 1
                or any(not package_tool.SHA256.fullmatch(str(checkpoint.get(name, "")))
                       for name in ("auditRecordSha256", "auditHeadSha256"))):
            raise ValueError("remote audit checkpoint is malformed")
        issued_at = package_tool.parse_time(checkpoint["issuedAt"], "checkpoint issuedAt")
        verification_at = package_tool.verification_time(args.verification_time)
        if issued_at > verification_at:
            raise ValueError("remote audit checkpoint was issued in the future")
        policy_path = package_tool.resolved_path(args.audit_policy, "remote audit policy")
        policy, policy_sha = impact_tool.load_json(policy_path, "remote audit policy")
        if (args.expected_audit_policy_id != policy.get("policyId")
                or not package_tool.SHA256.fullmatch(
                    str(args.expected_audit_policy_sha256).lower())
                or policy_sha != str(args.expected_audit_policy_sha256).lower()):
            raise ValueError("remote audit policy identity is not pinned")
        validate_audit_policy(policy)
        matches = [item for item in policy["auditors"]
                   if item["auditorId"] == checkpoint["auditorId"]
                   and item["keyId"] == checkpoint["keyId"]
                   and checkpoint["registryId"] in item["registryIds"]]
        if len(matches) != 1:
            raise ValueError("remote audit checkpoint signer is not trusted")
        auditor = matches[0]
        if (issued_at < package_tool.parse_time(auditor["notBefore"], "auditor notBefore")
                or issued_at >= package_tool.parse_time(
                    auditor["notAfter"], "auditor notAfter")):
            raise ValueError("remote audit checkpoint is outside signer validity")
        for revoked in policy["revokedKeys"]:
            if (revoked["keyId"] == checkpoint["keyId"]
                    and verification_at >= package_tool.parse_time(
                        revoked["revokedAt"], "audit key revokedAt")):
                raise ValueError("remote audit checkpoint key was revoked")
        public_path = registry_tool.safe_member(
            policy_path.parent, auditor["publicKey"], "remote audit public key"
        )
        public_bytes = public_path.read_bytes()
        if package_tool.sha256_bytes(public_bytes) != auditor["publicKeySha256"]:
            raise ValueError("remote audit public key digest changed")
        try:
            signature = base64.b64decode(checkpoint["signature"], validate=True)
        except (ValueError, TypeError) as error:
            raise ValueError("remote audit checkpoint signature encoding is invalid") from error
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
            from cryptography.hazmat.primitives.serialization import load_pem_public_key
            public_key = load_pem_public_key(public_bytes)
            if not isinstance(public_key, Ed25519PublicKey):
                raise ValueError("remote audit checkpoint public key is not Ed25519")
            public_key.verify(
                signature,
                package_tool.canonical_bytes(audit_checkpoint_payload(checkpoint)),
            )
        except ImportError as error:
            raise ValueError("remote audit checkpoint requires cryptography") from error
        except Exception as error:
            if isinstance(error, ValueError):
                raise
            raise ValueError("remote audit checkpoint signature verification failed") from error
        archive_directory = getattr(args, "audit_archive_directory", None)
        verification = verify_audit_chain(
            control, args.registry_id, archive_directory=archive_directory
        )
        if verification["sequence"] < checkpoint["auditSequence"]:
            raise ValueError("remote audit state was rolled back before its checkpoint")
        archived = audit_archive_tool.load_registered_archives(
            control, archive_directory, args.registry_id, validate_audit_record
        )
        archived_record = archived["recordsBySequence"].get(
            checkpoint["auditSequence"]
        )
        if archived_record is not None:
            record_content = archived_record[2]
        else:
            candidates = list((control / "audit" / "records").glob(
                f"{checkpoint['auditSequence']:020d}-*.json"
            ))
            if len(candidates) != 1:
                raise ValueError("remote audit checkpoint record is unavailable")
            record_content = candidates[0].read_bytes()
        if package_tool.sha256_bytes(record_content) != checkpoint["auditRecordSha256"]:
            raise ValueError("remote audit chain diverges from its checkpoint")
        record = json.loads(record_content)
        anchored_head = {
            "schemaVersion": 1, "product": AUDIT_HEAD_PRODUCT,
            "registryId": args.registry_id, "sequence": checkpoint["auditSequence"],
            "lastRecordSha256": checkpoint["auditRecordSha256"],
            "updatedAt": record["occurredAt"],
        }
        if package_tool.sha256_bytes(package_tool.json_bytes(anchored_head)) \
                != checkpoint["auditHeadSha256"]:
            raise ValueError("remote audit checkpoint head digest changed")
        report = {
            "schemaVersion": 1,
            "product": "PocoDDSRuntimeTeamContractRegistryRemoteAuditCheckpointVerification",
            "passed": True,
            "registryId": args.registry_id,
            "checkpointId": checkpoint["checkpointId"],
            "auditSequence": checkpoint["auditSequence"],
            "currentSequence": verification["sequence"],
            "checkpointSha256": package_tool.sha256_bytes(checkpoint_path.read_bytes()),
            "auditPolicyId": policy["policyId"],
            "auditPolicySha256": policy_sha,
            "verifiedAt": verification_at.isoformat(),
        }
        if args.report:
            package_tool.write_json(Path(args.report).resolve(), report)
        print(
            "PDR_TEAM_CONTRACT_REGISTRY_REMOTE_AUDIT_CHECKPOINT_VERIFY_PASS "
            f"sequence={checkpoint['auditSequence']} current={verification['sequence']}"
        )
        return 0
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        print(f"PDR_TEAM_CONTRACT_REGISTRY_REMOTE_ERROR: {error}", file=sys.stderr)
        return 2


def current_identity(root: Path) -> tuple[int | None, str | None, str | None]:
    try:
        pointer, state, _ = registry_tool.read_current(root)
        return pointer["revision"], pointer["stateSha256"], state["registryId"]
    except (OSError, UnicodeError, ValueError):
        return None, None, None


class CapacityError(RuntimeError):
    pass


class PolicyReloadError(RuntimeError):
    pass


def count_regular_files(root: Path) -> tuple[int, int]:
    count = 0
    size = 0
    if not root.is_dir():
        return count, size
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError("remote Registry control state must not contain links")
        if path.is_file():
            count += 1
            size += path.stat().st_size
    return count, size


def capacity_report(control: Path, policy: dict[str, Any]) -> dict[str, Any]:
    requests, request_bytes = count_regular_files(control / "requests")
    recoveries, recovery_bytes = count_regular_files(control / "recoveries")
    audit_records, audit_bytes = count_regular_files(control / "audit" / "records")
    _, total_bytes = count_regular_files(control)
    limits = access_policy_tool.control_limits(policy)
    import team_contract_registry_handoff as handoff_tool
    drain = handoff_tool.read_state(control, policy["registryId"])
    admission_open = drain is None or drain[0]["mode"] == "accepting"
    accepting_requests = admission_open and (
        requests + 1 <= limits["maxActiveRequestRecords"]
        and audit_records + 2 <= limits["maxAuditRecords"]
        and total_bytes + policy["maxResponseBytes"] + 32768
            <= limits["maxControlBytes"]
    )
    accepting_recoveries = (
        recoveries + 1 <= limits["maxRecoveryRecords"]
        and audit_records + 2 <= limits["maxAuditRecords"]
        and total_bytes + 64 * 1024 <= limits["maxControlBytes"]
    )
    return {
        "schemaVersion": 1,
        "product": "PocoDDSRuntimeTeamContractRegistryRemoteCapacity",
        "passed": True,
        "registryId": policy["registryId"],
        "policyId": policy["policyId"],
        "policyRevision": policy.get("policyRevision", 0),
        "acceptingMutations": accepting_requests,
        "acceptingRecoveries": accepting_recoveries,
        "usage": {
            "activeRequestRecords": requests,
            "recoveryRecords": recoveries,
            "auditRecords": audit_records,
            "requestBytes": request_bytes,
            "recoveryBytes": recovery_bytes,
            "auditBytes": audit_bytes,
            "controlBytes": total_bytes,
        },
        "limits": limits,
        "measuredAt": registry_tool.utc_time(None),
    }


def lease_status_report(settings: argparse.Namespace,
                        policy: dict[str, Any]) -> dict[str, Any]:
    control = Path(settings.control_directory).resolve()
    root = registry_tool.registry_root(settings.registry)
    command = process_lease.inspect_lease(
        control / ".command.lock",
        control / ".command.epoch.json",
        "team-contract-registry-command-processor",
    )
    writer = registry_tool.lease_status(root)
    healthy = command["healthy"] and writer["healthy"]
    return {
        "schemaVersion": 1,
        "product": LEASE_STATUS_PRODUCT,
        "passed": healthy,
        "registryId": policy["registryId"],
        "acceptingCommands": healthy and not command["active"] and not writer["active"],
        "commandProcessor": command,
        "registryWriter": writer,
        "observedAt": registry_tool.utc_time(None),
    }


def remote_drain_status(settings: argparse.Namespace,
                        policy: dict[str, Any]) -> dict[str, Any]:
    import team_contract_registry_handoff as handoff_tool
    control = Path(settings.control_directory).resolve()
    with ControlLease(control) as lease:
        lease.assert_current()
        loaded = handoff_tool.read_state(control, policy["registryId"])
        if loaded is None:
            raise FileNotFoundError("remote Registry drain state is unavailable")
        state = loaded[0]
        pending, pending_sha = handoff_tool.pending_requests(control)
        return {
            "schemaVersion": 1, "product": handoff_tool.STATUS_PRODUCT,
            "passed": True, "registryId": state["registryId"],
            "nodeId": state["nodeId"], "handoffId": state["handoffId"],
            "mode": state["mode"], "generation": state["generation"],
            "registryRevision": state["registryRevision"],
            "registryStateSha256": state["registryStateSha256"],
            "pendingRequestCount": len(pending),
            "pendingRequestSetSha256": pending_sha,
            "observedFencingToken": state["observedFencingToken"],
            "handoffEvidenceSha256": state["handoffEvidenceSha256"],
            "observedAt": registry_tool.utc_time(None),
        }


def _remote_handoff_evidence_path(settings: argparse.Namespace,
                                  handoff_id: str, generation: int) -> Path:
    directory = configured_handoff_evidence_directory(settings)
    return directory / f"{handoff_id}-generation-{generation}.json"


def _load_remote_handoff_evidence(path: Path, expected_sha: str) \
        -> dict[str, Any]:
    import team_contract_registry_handoff as handoff_tool
    if path.is_symlink() or not path.is_file():
        raise ValueError("remote Registry handoff evidence is unavailable")
    content = path.read_bytes()
    if package_tool.sha256_bytes(content) != expected_sha:
        raise ValueError("remote Registry handoff evidence digest changed")
    try:
        document = json.loads(content)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("remote Registry handoff evidence is invalid JSON") from error
    handoff_tool.validate_evidence(document)
    return document


def execute_remote_drain(settings: argparse.Namespace, policy: dict[str, Any],
                         principal: dict[str, Any], document: dict[str, Any]) \
        -> dict[str, Any]:
    import team_contract_registry_handoff as handoff_tool
    operation = document["operation"]
    control = Path(settings.control_directory).resolve()
    existing = handoff_tool.read_state(control, policy["registryId"])
    replayed = False
    evidence: dict[str, Any] | None = None
    evidence_sha: str | None = None
    evidence_path = _remote_handoff_evidence_path(
        settings, document["handoffId"], document["expectedGeneration"]
    )
    if operation == "start" and existing is not None:
        state = existing[0]
        if (state["mode"] == "draining"
                and state["handoffId"] == document["handoffId"]
                and state["generation"] == document["expectedGeneration"] + 1):
            if (state["nodeId"] != settings.node_id
                    or state["registryRevision"] != document["expectedRevision"]
                    or state["registryStateSha256"]
                        != document["expectedStateSha256"]
                    or state["reason"] != document["reason"]):
                raise ValueError(
                    "remote Registry drain retry does not match persisted start"
                )
            replayed = True
    if operation == "finalize" and existing is not None:
        state = existing[0]
        if (state["mode"] == "drained"
                and state["handoffId"] == document["handoffId"]
                and state["generation"] == document["expectedGeneration"]):
            if (state["nodeId"] != settings.node_id
                    or state["registryRevision"] != document["expectedRevision"]
                    or state["registryStateSha256"]
                        != document["expectedStateSha256"]
                    or state["handoffEvidenceSha256"] is None):
                raise ValueError(
                    "remote Registry drain retry does not match persisted finalize"
                )
            evidence_sha = state["handoffEvidenceSha256"]
            evidence = _load_remote_handoff_evidence(evidence_path, evidence_sha)
            if (evidence["issuedAt"] != registry_tool.utc_time(document["issuedAt"])
                    or evidence["expiresAt"]
                        != registry_tool.utc_time(document["expiresAt"])):
                raise ValueError(
                    "remote Registry drain retry does not match persisted finalize"
                )
            replayed = True
    if operation == "resume" and existing is not None:
        state = existing[0]
        if (state["mode"] == "accepting"
                and state["handoffId"] == document["handoffId"]
                and state["generation"] == document["expectedGeneration"] + 1):
            if (state["nodeId"] != settings.node_id
                    or state["registryRevision"] != document["expectedRevision"]
                    or state["registryStateSha256"]
                        != document["expectedStateSha256"]
                    or state["reason"] != document["reason"]):
                raise ValueError(
                    "remote Registry drain retry does not match persisted resume"
                )
            replayed = True
    if not replayed:
        common = {
            "registry": settings.registry,
            "control_directory": settings.control_directory,
            "audit_archive_directory": configured_audit_archive_directory(settings),
            "registry_id": policy["registryId"],
            "node_id": settings.node_id,
            "handoff_id": document["handoffId"],
            "expected_generation": document["expectedGeneration"],
            "expected_revision": document["expectedRevision"],
            "expected_state_sha256": document["expectedStateSha256"],
            "operator": principal["principalId"], "report": None,
            "quiet": True, "raise_errors": True,
        }
        if operation == "start":
            handoff_tool.start_command(argparse.Namespace(
                **common, reason=document["reason"]
            ))
        elif operation == "finalize":
            required = (
                settings.handoff_key_id,
                settings.handoff_private_key_environment,
            )
            if not all(required):
                raise ValueError("remote Registry handoff signer is not configured")
            handoff_tool.finalize_command(argparse.Namespace(
                **common,
                leader_verification_time=settings.handoff_leader_verification_time,
                issued_at=document["issuedAt"], expires_at=document["expiresAt"],
                key_id=settings.handoff_key_id,
                private_key_environment=settings.handoff_private_key_environment,
                private_key_passphrase_environment=
                    settings.handoff_private_key_passphrase_environment,
                output=str(evidence_path),
            ))
            loaded = handoff_tool.read_state(control, policy["registryId"])
            if loaded is None or loaded[0]["handoffEvidenceSha256"] is None:
                raise ValueError("remote Registry handoff did not commit evidence")
            evidence_sha = loaded[0]["handoffEvidenceSha256"]
            evidence = _load_remote_handoff_evidence(evidence_path, evidence_sha)
        else:
            handoff_tool.resume_command(argparse.Namespace(
                **common, reason=document["reason"]
            ))
    loaded = handoff_tool.read_state(control, policy["registryId"])
    if loaded is None:
        raise ValueError("remote Registry drain state disappeared")
    result_state = loaded[0]
    expected_mode = {
        "start": "draining", "finalize": "drained", "resume": "accepting"
    }[operation]
    expected_generation = document["expectedGeneration"] + (
        1 if operation in {"start", "resume"} else 0
    )
    if (result_state["mode"] != expected_mode
            or result_state["nodeId"] != settings.node_id
            or result_state["handoffId"] != document["handoffId"]
            or result_state["generation"] != expected_generation
            or result_state["registryRevision"] != document["expectedRevision"]
            or result_state["registryStateSha256"]
                != document["expectedStateSha256"]):
        raise ValueError("remote Registry drain result changed concurrently")
    return {
        "schemaVersion": 1, "product": REMOTE_DRAIN_RESPONSE_PRODUCT,
        "passed": True, "registryId": policy["registryId"],
        "operation": operation, "handoffId": document["handoffId"],
        "replayed": replayed, "state": result_state,
        "evidence": evidence, "evidenceSha256": evidence_sha,
    }


def require_capacity(control: Path, policy: dict[str, Any], *,
                     request_records: int = 0, recovery_records: int = 0,
                     audit_records: int = 0, control_bytes: int = 0) -> None:
    report = capacity_report(control, policy)
    usage = report["usage"]
    limits = report["limits"]
    checks = (
        (usage["activeRequestRecords"] + request_records,
         limits["maxActiveRequestRecords"], "active request records"),
        (usage["recoveryRecords"] + recovery_records,
         limits["maxRecoveryRecords"], "recovery records"),
        (usage["auditRecords"] + audit_records,
         limits["maxAuditRecords"], "audit records"),
        (usage["controlBytes"] + control_bytes,
         limits["maxControlBytes"], "control bytes"),
    )
    for projected, limit, label in checks:
        if projected > limit:
            raise CapacityError(
                f"remote Registry {label} capacity would be exceeded; "
                "operator retention action is required"
            )


def maybe_reload_access_policy(server: Any) -> dict[str, Any]:
    with server.policy_lock:
        try:
            candidate, candidate_sha, _, _ = access_policy_tool.load_policy_bytes(
                server.settings.access_policy
            )
            if candidate_sha == server.access_policy_sha256:
                return server.access_policy
            if server.access_policy_trust is None:
                raise ValueError(
                    "access policy changed but signed hot reload is not configured"
                )
            current = server.access_policy
            signer = access_policy_tool.verify_signed_policy(
                candidate, server.access_policy_trust,
                server.access_policy_trust_path,
                package_tool.verification_time(server.settings.verification_time),
            )
            if (candidate["policyId"] != current["policyId"]
                    or candidate["registryId"] != current["registryId"]
                    or candidate["policyRevision"]
                        != current.get("policyRevision", 0) + 1
                    or candidate["previousPolicySha256"]
                        != server.access_policy_sha256):
                raise ValueError("hot-reload access policy is not the exact successor")
            control = Path(server.settings.control_directory).resolve()
            with ControlLease(control) as lease:
                lease.assert_current()
                require_capacity(
                    control, current, audit_records=1, control_bytes=4096
                )
                revision, state_sha, registry_id = current_identity(
                    registry_tool.registry_root(server.settings.registry)
                )
                append_audit_record(
                    control, registry_id or current["registryId"], "policy-reloaded",
                    archive_directory=configured_audit_archive_directory(
                        server.settings
                    ),
                    request_id=None, request_sha=candidate_sha,
                    principal_id="policy-signer." + signer["keyId"],
                    operation="access-policy-reload", started_revision=revision,
                    final_revision=revision, final_state_sha=state_sha,
                    outcome="completed", response_sha=candidate_sha,
                    recovery_id=None,
                    reason=f"policyRevision={candidate['policyRevision']}",
                )
            server.access_policy = candidate
            server.access_policy_sha256 = candidate_sha
            return candidate
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
            raise PolicyReloadError(
                f"remote Registry access-policy reload failed closed: {error}"
            ) from error


def load_request_record(control: Path, request_id: str) -> tuple[Path, dict[str, Any]]:
    path = request_record_path(control, request_id)
    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError("remote Registry request record is unavailable")
    try:
        record = json.loads(path.read_bytes())
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("remote Registry request record is invalid JSON") from error
    required = {
        "schemaVersion", "requestId", "requestSha256", "principalId",
        "operation", "startedRevision", "status",
    }
    if (not isinstance(record, dict) or not required.issubset(record)
            or record.get("schemaVersion") != 1
            or record.get("requestId") != request_id
            or not package_tool.SHA256.fullmatch(str(record.get("requestSha256", "")))
            or not package_tool.IDENTIFIER.fullmatch(str(record.get("principalId", "")))
            or record.get("operation") not in OPERATIONS
            or (record.get("startedRevision") is not None
                and (type(record["startedRevision"]) is not int
                     or record["startedRevision"] < 0))
            or record.get("status") not in REQUEST_STATES):
        raise ValueError("remote Registry request record is malformed")
    return path, record


def request_status_document(record: dict[str, Any], registry_id: str) -> dict[str, Any]:
    response = record.get("response") if isinstance(record.get("response"), dict) else {}
    recovery = record.get("recovery") if isinstance(record.get("recovery"), dict) else None
    return {
        "schemaVersion": 1,
        "product": STATUS_PRODUCT,
        "registryId": registry_id,
        "requestId": record["requestId"],
        "requestSha256": record["requestSha256"],
        "principalId": record["principalId"],
        "operation": record["operation"],
        "startedRevision": record["startedRevision"],
        "status": record["status"],
        "finalRevision": response.get("revision"),
        "finalStateSha256": response.get("stateSha256"),
        "responseSha256": record.get("responseSha256"),
        "lastAuditRecordSha256": record.get("lastAuditRecordSha256"),
        "recovery": recovery,
    }


def ensure_request_started_audit(control: Path, registry_id: str,
                                 path: Path, record: dict[str, Any],
                                 archive_directory: str | Path | None = None) -> None:
    if record.get("lastAuditRecordSha256") is not None:
        return
    _, digest = append_audit_record(
        control, registry_id, "request-started",
        archive_directory=archive_directory,
        request_id=record["requestId"], request_sha=record["requestSha256"],
        principal_id=record["principalId"], operation=record["operation"],
        started_revision=record["startedRevision"],
        final_revision=None, final_state_sha=None, outcome="pending",
        response_sha=None, recovery_id=None, reason=None,
    )
    record["lastAuditRecordSha256"] = digest
    package_tool.write_json(path, record)


def bootstrap_request_audit(control: Path, registry_id: str,
                            archive_directory: str | Path | None = None) -> None:
    ensure_audit_head(control, registry_id)
    requests = registry_tool.safe_member(control, "requests", "remote request records")
    if not requests.is_dir():
        return
    for path in sorted(requests.rglob("*.json")):
        if path.is_symlink():
            raise ValueError("remote Registry request record must not be a link")
        raw = json.loads(path.read_bytes())
        request_id = raw.get("requestId") if isinstance(raw, dict) else None
        if not package_tool.IDENTIFIER.fullmatch(str(request_id or "")):
            raise ValueError("remote Registry request record identity is malformed")
        canonical_path, record = load_request_record(control, request_id)
        if canonical_path != path.resolve():
            raise ValueError("remote Registry request record path changed")
        ensure_request_started_audit(
            control, registry_id, canonical_path, record, archive_directory
        )
        if record["status"] == "completed" and not record.get("completionAuditRecordSha256"):
            response = record.get("response", {})
            _, digest = append_audit_record(
                control, registry_id, "request-completed",
                archive_directory=archive_directory,
                request_id=record["requestId"], request_sha=record["requestSha256"],
                principal_id=record["principalId"], operation=record["operation"],
                started_revision=record["startedRevision"],
                final_revision=response.get("revision"),
                final_state_sha=response.get("stateSha256"), outcome="completed",
                response_sha=record.get("responseSha256"), recovery_id=None,
                reason=None,
            )
            record["completionAuditRecordSha256"] = digest
            record["lastAuditRecordSha256"] = digest
            package_tool.write_json(canonical_path, record)


def validate_recovery(document: Any) -> None:
    fields = {
        "schemaVersion", "product", "registryId", "targetRequestId",
        "targetRequestSha256", "expectedStartedRevision",
        "expectedCurrentRevision", "disposition", "reason",
    }
    if (not isinstance(document, dict) or set(document) != fields
            or document.get("schemaVersion") != 1
            or document.get("product") != RECOVERY_PRODUCT
            or not package_tool.IDENTIFIER.fullmatch(str(document.get("registryId", "")))
            or not package_tool.IDENTIFIER.fullmatch(
                str(document.get("targetRequestId", "")))
            or not package_tool.SHA256.fullmatch(
                str(document.get("targetRequestSha256", "")))
            or any(type(document.get(name)) is not int or document[name] < 0
                   for name in ("expectedStartedRevision", "expectedCurrentRevision"))
            or document.get("disposition") not in {"aborted", "uncertain"}
            or not isinstance(document.get("reason"), str)
            or not 1 <= len(document["reason"]) <= 512):
        raise ValueError("remote Registry recovery request is malformed")


def execute_recovery(settings: argparse.Namespace, policy: dict[str, Any],
                     principal: dict[str, Any],
                     recovery_id: str, document: dict[str, Any]) \
        -> tuple[int, dict[str, Any]]:
    control = Path(settings.control_directory).resolve()
    root = registry_tool.registry_root(settings.registry)
    recovery_sha = canonical_sha(document)
    with ControlLease(control) as lease:
        lease.assert_current()
        record_path = recovery_record_path(control, recovery_id)
        if record_path.is_file():
            prior = json.loads(record_path.read_bytes())
            if prior.get("recoverySha256") != recovery_sha:
                raise ValueError("Recovery-Key was reused for different content")
            if prior.get("status") == "completed":
                return prior["httpStatus"], prior["response"]
        else:
            require_capacity(
                control, policy, recovery_records=1, audit_records=2,
                control_bytes=64 * 1024,
            )
            prior = {
                "schemaVersion": 1, "recoveryId": recovery_id,
                "recoverySha256": recovery_sha, "principalId": principal["principalId"],
                "targetRequestId": document["targetRequestId"], "status": "pending",
            }
            registry_tool.exclusive_bytes(record_path, package_tool.json_bytes(prior))
        target_path, target = load_request_record(control, document["targetRequestId"])
        verify_audit_chain(
            control, document["registryId"],
            target["requestId"] if target["status"] == "pending"
            and target.get("lastAuditRecordSha256") is None else None,
            configured_audit_archive_directory(settings),
        )
        if (target["requestSha256"] != document["targetRequestSha256"]
                or target["startedRevision"] != document["expectedStartedRevision"]):
            raise ValueError("remote Registry recovery target identity changed")
        if target["status"] != "pending":
            existing = target.get("recovery")
            if isinstance(existing, dict) and existing.get("recoveryId") == recovery_id:
                response = existing.get("response")
                if isinstance(response, dict):
                    prior.update({"status": "completed", "httpStatus": 200,
                                  "response": response,
                                  "responseSha256": canonical_sha(response)})
                    package_tool.write_json(record_path, prior)
                    return 200, response
            raise ValueError("remote Registry recovery target is no longer pending")
        ensure_request_started_audit(
            control, document["registryId"], target_path, target,
            configured_audit_archive_directory(settings),
        )
        revision, state_sha, registry_id = current_identity(root)
        if registry_id != document["registryId"] \
                or revision != document["expectedCurrentRevision"]:
            raise ValueError("remote Registry recovery observed revision changed")
        if document["disposition"] == "aborted" and revision != target["startedRevision"]:
            raise ValueError("advanced Registry revision cannot be declared aborted")
        if document["disposition"] == "uncertain" and revision == target["startedRevision"]:
            raise ValueError("unchanged Registry revision must be explicitly aborted")
        response = {
            "schemaVersion": 1,
            "product": RECOVERY_RESPONSE_PRODUCT,
            "passed": True,
            "registryId": registry_id,
            "recoveryId": recovery_id,
            "recoverySha256": recovery_sha,
            "targetRequestId": target["requestId"],
            "targetRequestSha256": target["requestSha256"],
            "startedRevision": target["startedRevision"],
            "observedRevision": revision,
            "observedStateSha256": state_sha,
            "disposition": document["disposition"],
            "operatorId": principal["principalId"],
            "reason": document["reason"],
        }
        response_sha = canonical_sha(response)
        lease.assert_current()
        _, audit_sha = append_audit_record(
            control, registry_id, "request-recovered",
            archive_directory=configured_audit_archive_directory(settings),
            request_id=target["requestId"], request_sha=target["requestSha256"],
            principal_id=principal["principalId"], operation=target["operation"],
            started_revision=target["startedRevision"], final_revision=revision,
            final_state_sha=state_sha, outcome=document["disposition"],
            response_sha=response_sha, recovery_id=recovery_id,
            reason=document["reason"],
        )
        target["status"] = document["disposition"]
        target["lastAuditRecordSha256"] = audit_sha
        target["recovery"] = {
            "recoveryId": recovery_id,
            "recoverySha256": recovery_sha,
            "response": response,
        }
        package_tool.write_json(target_path, target)
        prior.update({
            "status": "completed", "httpStatus": 200, "response": response,
            "responseSha256": response_sha, "auditRecordSha256": audit_sha,
        })
        package_tool.write_json(record_path, prior)
        return 200, response


def common_namespace(settings: argparse.Namespace, report: Path) -> dict[str, Any]:
    return {
        "registry": settings.registry,
        "trust_policy": settings.trust_policy,
        "expected_trust_policy_id": settings.expected_trust_policy_id,
        "expected_trust_policy_sha256": settings.expected_trust_policy_sha256,
        "verification_time": settings.verification_time,
        "maximum_files": settings.maximum_files,
        "maximum_expanded_bytes": settings.maximum_expanded_bytes,
        "report": str(report),
    }


def response_files(output: Path, maximum_bytes: int) -> list[dict[str, str]]:
    files: list[dict[str, str]] = []
    total = 0
    for path in sorted(item for item in output.rglob("*") if item.is_file()):
        if path.is_symlink():
            raise ValueError("remote Registry resolution contains a link")
        relative = path.relative_to(output).as_posix()
        package_tool.safe_archive_path(relative)
        content = path.read_bytes()
        total += len(content)
        if total > maximum_bytes:
            raise ValueError("remote Registry resolution exceeds response capacity")
        files.append({
            "path": relative,
            "sha256": package_tool.sha256_bytes(content),
            "dataBase64": base64.b64encode(content).decode("ascii"),
        })
    return files


REMOTE_REPORT_FIELDS = {
    "schemaVersion", "product", "operation", "passed", "registryId",
    "registryRevision", "registryStateSha256", "trustPolicyId",
    "trustPolicySha256", "packageId", "version", "owner", "packageSha256",
    "lockSha256", "channel", "generation", "action", "sourceChannel",
    "sourceGeneration", "rollbackFromGeneration", "rollbackToGeneration",
    "impactGateSha256", "gateAuthorizationSha256", "reason", "packages",
    "revisionCount", "packageCount", "lockCount", "channelCount",
}


def sanitize_report(value: Any) -> Any:
    """Return only protocol fields that cannot encode server filesystem locations."""
    if isinstance(value, dict):
        return {
            key: sanitize_report(item)
            for key, item in value.items()
            if key in REMOTE_REPORT_FIELDS
        }
    if isinstance(value, list):
        return [sanitize_report(item) for item in value]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        if (Path(value).is_absolute() or value.startswith(("\\\\", "//"))
                or ":\\" in value or ":/" in value):
            raise ValueError("remote Registry report attempted to expose a server path")
        return value
    raise ValueError("remote Registry report contains an unsupported value")


def execute_command(settings: argparse.Namespace, policy: dict[str, Any],
                    principal: dict[str, Any], command: dict[str, Any],
                    request_id: str, request_sha: str) -> tuple[int, dict[str, Any]]:
    root = registry_tool.registry_root(settings.registry)
    with tempfile.TemporaryDirectory(prefix="pdr-remote-registry-") as directory:
        temporary = Path(directory)
        artifacts = decode_artifacts(command, temporary, policy["maxRequestBytes"])
        operation = command["operation"]
        if operation == "publish":
            package = package_tool.verify_package(
                artifacts["package"], settings.maximum_files,
                settings.maximum_expanded_bytes,
            )
            package_id = package["manifest"]["packageId"]
            if package_id not in principal["packageIds"]:
                raise PermissionError("remote publisher does not own this package ID")
        report_path = temporary / "operation-report.json"
        values = common_namespace(settings, report_path)
        values.update({
            "actor": principal["principalId"], "occurred_at": None,
            "expected_revision": command["expectedRevision"],
        })
        files: list[dict[str, str]] = []
        if operation == "publish":
            values["package"] = str(artifacts["package"])
            code = registry_tool.publish_command(argparse.Namespace(**values))
        elif operation == "promote":
            params = command["parameters"]
            values.update({
                "channel": params["channel"], "lock": str(artifacts["lock"]),
                "expected_generation": params["expectedGeneration"],
                "impact_gate": str(artifacts["impactGate"])
                    if "impactGate" in artifacts else None,
                "runner_attestation": str(artifacts["runnerAttestation"])
                    if "runnerAttestation" in artifacts else None,
                "runner_trust_policy": settings.runner_trust_policy,
                "expected_runner_trust_policy_id": settings.expected_runner_trust_policy_id,
                "expected_runner_trust_policy_sha256":
                    settings.expected_runner_trust_policy_sha256,
                "gate_authorization": str(artifacts["gateAuthorization"])
                    if "gateAuthorization" in artifacts else None,
                "gate_authorization_policy": settings.gate_authorization_policy,
                "expected_gate_authorization_policy_id":
                    settings.expected_gate_authorization_policy_id,
                "expected_gate_authorization_policy_sha256":
                    settings.expected_gate_authorization_policy_sha256,
            })
            code = registry_tool.promote_command(argparse.Namespace(**values))
        elif operation == "rollback":
            params = command["parameters"]
            values.update({
                "channel": params["channel"],
                "expected_generation": params["expectedGeneration"],
                "to_generation": params["toGeneration"], "reason": params["reason"],
            })
            code = registry_tool.rollback_command(argparse.Namespace(**values))
        elif operation == "verify":
            values.pop("actor")
            values.pop("occurred_at")
            values.pop("expected_revision")
            code = registry_tool.verify_command(argparse.Namespace(**values))
        else:
            values.pop("actor")
            values.pop("occurred_at")
            values.pop("expected_revision")
            output = temporary / "resolved"
            values.update({
                "channel": command["parameters"]["channel"], "output": str(output),
                "package_report": str(temporary / "package-report.json"),
            })
            code = registry_tool.resolve_command(argparse.Namespace(**values))
            if code == 0:
                files = response_files(output, policy["maxResponseBytes"])
        revision, state_sha, registry_id = current_identity(root)
        report = sanitize_report(json.loads(report_path.read_text(encoding="utf-8"))) \
            if report_path.is_file() else None
        passed = code == 0
        response = {
            "schemaVersion": 1,
            "product": RESPONSE_PRODUCT,
            "requestId": request_id,
            "requestSha256": request_sha,
            "operation": operation,
            "passed": passed,
            "registryId": registry_id or command["registryId"],
            "revision": revision,
            "stateSha256": state_sha,
            "report": report,
            "files": files,
            "error": None if passed else "Registry command was rejected",
        }
        return (200 if passed else 409), response


class RegistryRemoteServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False


class RemoteHandler(BaseHTTPRequestHandler):
    server_version = "PDRTeamContractRegistry/1"

    def log_message(self, format_value: str, *values: Any) -> None:
        if not self.server.settings.quiet:
            sys.stderr.write("PDR_REGISTRY_REMOTE " + format_value % values + "\n")

    def send_json(self, status: int, document: dict[str, Any]) -> None:
        content = package_tool.json_bytes(document)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(content)

    def problem(self, status: int, message: str) -> None:
        self.send_json(status, {
            "schemaVersion": 1,
            "product": "PocoDDSRuntimeTeamContractRegistryRemoteProblem",
            "status": status,
            "error": message[:1024],
        })

    def authenticated_principal(self) -> dict[str, Any]:
        policy = maybe_reload_access_policy(self.server)
        self.active_access_policy = policy
        return authenticate(
            policy, self.headers.get("Authorization"),
            package_tool.verification_time(self.server.settings.verification_time),
        )

    def do_GET(self) -> None:
        settings = self.server.settings
        try:
            principal = self.authenticated_principal()
            if not ({"auditor", "operator"} & set(principal["roles"])):
                raise PermissionError(
                    "remote Registry auditor or operator role is required"
                )
            control = Path(settings.control_directory).resolve()
            policy = self.active_access_policy
            registry_id = policy["registryId"]
            if self.path == "/v1/drain":
                report = remote_drain_status(settings, policy)
                self.send_json(200, report)
                return
            if self.path == "/v1/leases":
                report = lease_status_report(settings, policy)
                self.send_json(200, report)
                return
            if self.path == "/v1/capacity":
                with ControlLease(control) as lease:
                    lease.assert_current()
                    report = capacity_report(control, policy)
                self.send_json(200, report)
                return
            if self.path == "/v1/audit":
                with ControlLease(control) as lease:
                    lease.assert_current()
                    report = verify_audit_chain(
                        control, registry_id,
                        archive_directory=configured_audit_archive_directory(settings),
                    )
                self.send_json(200, report)
                return
            if self.path == "/v1/audit-archives":
                with ControlLease(control) as lease:
                    lease.assert_current()
                    archive_directory = configured_audit_archive_directory(settings)
                    verify_audit_chain(
                        control, registry_id, archive_directory=archive_directory
                    )
                    report = audit_archive_tool.status_document(
                        control, archive_directory, registry_id, validate_audit_record
                    )
                self.send_json(200, report)
                return
            prefix = "/v1/requests/"
            if self.path.startswith(prefix):
                request_id = urllib.parse.unquote(self.path[len(prefix):])
                if not package_tool.IDENTIFIER.fullmatch(request_id):
                    raise ValueError("remote Registry request identity is invalid")
                with ControlLease(control) as lease:
                    lease.assert_current()
                    path, record = load_request_record(control, request_id)
                    verify_audit_chain(
                        control, registry_id,
                        request_id if record["status"] == "pending"
                        and record.get("lastAuditRecordSha256") is None else None,
                        configured_audit_archive_directory(settings),
                    )
                    if record.get("lastAuditRecordSha256") is None:
                        require_capacity(
                            control, policy, audit_records=1, control_bytes=4096
                        )
                    ensure_request_started_audit(
                        control, registry_id, path, record,
                        configured_audit_archive_directory(settings),
                    )
                    status = request_status_document(record, registry_id)
                self.send_json(200, status)
                return
            self.problem(404, "remote Registry endpoint not found")
        except PermissionError as error:
            self.problem(403, str(error))
        except FileNotFoundError as error:
            self.problem(404, str(error))
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
            self.problem(400, str(error))
        except CapacityError as error:
            self.problem(507, str(error))
        except RuntimeError as error:
            self.problem(503, str(error))

    def do_POST(self) -> None:
        if self.path not in {"/v1/commands", "/v1/recoveries", "/v1/drain"}:
            self.problem(404, "remote Registry endpoint not found")
            return
        settings = self.server.settings
        try:
            principal = self.authenticated_principal()
            policy = self.active_access_policy
            content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip()
            if content_type != "application/json":
                raise ValueError("remote Registry requires application/json")
            try:
                length = int(self.headers.get("Content-Length", ""))
            except ValueError as error:
                raise ValueError("remote Registry Content-Length is invalid") from error
            if not 1 <= length <= policy["maxRequestBytes"]:
                raise ValueError("remote Registry request size is outside policy")
            raw = self.rfile.read(length)
            document = json.loads(raw)
            if self.path == "/v1/drain":
                if "operator" not in principal["roles"]:
                    raise PermissionError("remote Registry operator role is required")
                validate_remote_drain_command(document)
                if document["registryId"] != policy["registryId"]:
                    raise PermissionError(
                        "remote Registry identity is outside access policy"
                    )
                try:
                    response = execute_remote_drain(
                        settings, policy, principal, document
                    )
                except ValueError as error:
                    self.problem(409, str(error))
                    return
                self.send_json(200, response)
                return
            if self.path == "/v1/recoveries":
                if "operator" not in principal["roles"]:
                    raise PermissionError("remote Registry operator role is required")
                recovery_id = self.headers.get("Recovery-Key", "")
                if not package_tool.IDENTIFIER.fullmatch(recovery_id):
                    raise ValueError("valid Recovery-Key is required")
                validate_recovery(document)
                if document["registryId"] != policy["registryId"]:
                    raise PermissionError(
                        "remote Registry identity is outside access policy"
                    )
                http_status, response = execute_recovery(
                    settings, policy, principal, recovery_id, document
                )
                self.send_json(http_status, response)
                return
            request_id = self.headers.get("Idempotency-Key", "")
            if not package_tool.IDENTIFIER.fullmatch(request_id):
                raise ValueError("valid Idempotency-Key is required")
            command = document
            validate_command(command)
            if command["registryId"] != policy["registryId"]:
                raise PermissionError("remote Registry identity is outside access policy")
            authorize(principal, command)
            registry_root = registry_tool.registry_root(settings.registry)
            if (command["operation"] in MUTATIONS
                    and registry_tool.read_standby_marker(
                        registry_root, command["registryId"]
                    ) is not None):
                self.problem(409, "remote Registry standby is read-only")
                return
            control = Path(settings.control_directory).resolve()
            try:
                import team_contract_registry_handoff as handoff_tool
                handoff_tool.require_command_admission(
                    control, command["registryId"]
                )
            except ValueError as error:
                self.problem(409, str(error))
                return
            if command["operation"] in MUTATIONS:
                try:
                    registry_tool.require_primary(registry_root)
                except ValueError as error:
                    self.problem(
                        409, f"remote Registry write authority rejected: {error}"
                    )
                    return
            request_sha = canonical_sha(command)
            with ControlLease(control) as lease:
                lease.assert_current()
                record_path = request_record_path(control, request_id)
                if record_path.is_file():
                    _, record = load_request_record(control, request_id)
                    verify_audit_chain(
                        control, command["registryId"],
                        request_id if record["status"] == "pending"
                        and record.get("lastAuditRecordSha256") is None else None,
                        configured_audit_archive_directory(settings),
                    )
                    if record.get("requestSha256") != request_sha:
                        self.problem(409, "Idempotency-Key was reused for different content")
                        return
                    if record.get("status") == "completed":
                        self.send_json(record["httpStatus"], record["response"])
                        return
                    if record.get("status") in {"aborted", "uncertain"}:
                        self.problem(
                            409,
                            "request is terminal after operator recovery; use a new Idempotency-Key",
                        )
                        return
                    if record.get("lastAuditRecordSha256") is None:
                        require_capacity(
                            control, policy, audit_records=1, control_bytes=4096
                        )
                    ensure_request_started_audit(
                        control, command["registryId"], record_path, record,
                        configured_audit_archive_directory(settings),
                    )
                    revision, _, _ = current_identity(
                        registry_tool.registry_root(settings.registry)
                    )
                    if (command["operation"] in MUTATIONS
                            and revision != record.get("startedRevision")):
                        self.problem(
                            409,
                            "pending command crossed a Registry revision; operator recovery required",
                        )
                        return
                    require_capacity(
                        control, policy, audit_records=1,
                        control_bytes=policy["maxResponseBytes"] + 32768,
                    )
                else:
                    require_capacity(
                        control, policy, request_records=1, audit_records=2,
                        control_bytes=policy["maxResponseBytes"] + 32768,
                    )
                    revision, _, _ = current_identity(
                        registry_tool.registry_root(settings.registry)
                    )
                    record = {
                        "schemaVersion": 1,
                        "requestId": request_id,
                        "requestSha256": request_sha,
                        "principalId": principal["principalId"],
                        "operation": command["operation"],
                        "startedRevision": revision,
                        "status": "pending",
                    }
                    registry_tool.exclusive_bytes(record_path, package_tool.json_bytes(record))
                    ensure_request_started_audit(
                        control, command["registryId"], record_path, record,
                        configured_audit_archive_directory(settings),
                    )
                http_status, response = execute_command(
                    settings, policy, principal, command,
                    request_id, request_sha,
                )
                lease.assert_current()
                response_sha = canonical_sha(response)
                _, audit_sha = append_audit_record(
                    control, command["registryId"], "request-completed",
                    archive_directory=configured_audit_archive_directory(settings),
                    request_id=request_id, request_sha=request_sha,
                    principal_id=principal["principalId"],
                    operation=command["operation"],
                    started_revision=record["startedRevision"],
                    final_revision=response.get("revision"),
                    final_state_sha=response.get("stateSha256"),
                    outcome="completed", response_sha=response_sha,
                    recovery_id=None, reason=response.get("error"),
                )
                record.update({
                    "status": "completed", "httpStatus": http_status, "response": response,
                    "responseSha256": response_sha,
                    "completionAuditRecordSha256": audit_sha,
                    "lastAuditRecordSha256": audit_sha,
                })
                package_tool.write_json(record_path, record)
                self.send_json(http_status, response)
        except PermissionError as error:
            self.problem(403, str(error))
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
            self.problem(400, str(error))
        except CapacityError as error:
            self.problem(507, str(error))
        except RuntimeError as error:
            self.problem(503, str(error))


def serve_command(args: argparse.Namespace) -> int:
    try:
        root = registry_tool.registry_root(args.registry)
        pointer, state, _ = registry_tool.read_current(root)
        policy, policy_sha = load_access_policy(
            args.access_policy, args.expected_access_policy_id,
            args.expected_access_policy_sha256,
        )
        if policy["registryId"] != state["registryId"]:
            raise ValueError("remote access policy Registry ID does not match Registry state")
        control = Path(args.control_directory).resolve() if args.control_directory \
            else root / ".remote-control"
        args.control_directory = str(control)
        standby = registry_tool.read_standby_marker(root, state["registryId"])
        if standby is not None and same_or_child(control, root):
            raise ValueError(
                "standby remote control directory must be outside the Registry root"
            )
        handoff_values = (
            args.node_id, args.handoff_evidence_directory,
            args.handoff_key_id, args.handoff_private_key_environment,
        )
        if any(handoff_values) and not all(handoff_values):
            raise ValueError(
                "remote drain control requires node id, evidence directory and signer"
            )
        if all(handoff_values):
            if (not package_tool.IDENTIFIER.fullmatch(args.node_id)
                    or not package_tool.IDENTIFIER.fullmatch(args.handoff_key_id)):
                raise ValueError("remote Registry handoff identity is malformed")
            evidence_directory = Path(args.handoff_evidence_directory).resolve()
            if (registry_tool.linklike(Path(args.handoff_evidence_directory))
                    or same_or_child(evidence_directory, root)
                    or same_or_child(evidence_directory, control)):
                raise ValueError(
                    "handoff evidence directory must be external to Registry and control"
                )
            evidence_directory.mkdir(parents=True, exist_ok=True)
            if registry_tool.linklike(evidence_directory):
                raise ValueError("handoff evidence directory must not be a link")
            args.handoff_evidence_directory = str(evidence_directory)
            import team_contract_registry_leader as leader_tool
            leader_tool._private_key(argparse.Namespace(
                private_key_environment=args.handoff_private_key_environment,
                private_key_passphrase_environment=
                    args.handoff_private_key_passphrase_environment,
            ))
        archive_directory = configured_audit_archive_directory(args)
        if archive_directory:
            audit_archive_tool.safe_archive_directory(archive_directory, control)
        with ControlLease(control) as lease:
            lease.assert_current()
            bootstrap_request_audit(control, state["registryId"], archive_directory)
            activate_audit(control, state["registryId"], archive_directory)
        parsed_host = args.bind.lower()
        loopback = parsed_host in {"127.0.0.1", "::1", "localhost"}
        if bool(args.tls_certificate) != bool(args.tls_private_key):
            raise ValueError("remote Registry TLS requires both certificate and private key")
        if not args.tls_certificate and not (loopback and args.allow_insecure_loopback):
            raise ValueError("remote Registry requires TLS outside explicit loopback testing")
        trust_values = (
            args.access_policy_trust_policy,
            args.expected_access_policy_trust_policy_id,
            args.expected_access_policy_trust_policy_sha256,
        )
        if any(trust_values) and not all(trust_values):
            raise ValueError(
                "access-policy hot reload requires a fully pinned signer trust policy"
            )
        access_trust = None
        access_trust_path = None
        if all(trust_values):
            access_trust, _, access_trust_path = access_policy_tool.load_trust_policy(
                *trust_values
            )
        if policy["schemaVersion"] == 2:
            if access_trust is None or access_trust_path is None:
                raise ValueError("signed access policy requires signer trust configuration")
            access_policy_tool.verify_signed_policy(
                policy, access_trust, access_trust_path,
                package_tool.verification_time(args.verification_time),
            )
        server = RegistryRemoteServer((args.bind, args.port), RemoteHandler)
        server.settings = args
        server.access_policy = policy
        server.access_policy_sha256 = policy_sha
        server.access_policy_trust = access_trust
        server.access_policy_trust_path = access_trust_path
        server.policy_lock = threading.RLock()
        if args.tls_certificate:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            context.load_cert_chain(args.tls_certificate, args.tls_private_key)
            server.socket = context.wrap_socket(server.socket, server_side=True)
        print(
            f"PDR_TEAM_CONTRACT_REGISTRY_REMOTE_LISTEN registry={state['registryId']} "
            f"revision={pointer['revision']} port={server.server_address[1]}",
            flush=True,
        )
        server.serve_forever(poll_interval=0.2)
        return 0
    except KeyboardInterrupt:
        return 0
    except (OSError, UnicodeError, ValueError, RuntimeError) as error:
        print(f"PDR_TEAM_CONTRACT_REGISTRY_REMOTE_ERROR: {error}", file=sys.stderr)
        return 2


def artifact(path_value: str) -> dict[str, str]:
    path = package_tool.resolved_path(path_value, "remote Registry client artifact")
    content = path.read_bytes()
    return {
        "sha256": package_tool.sha256_bytes(content),
        "dataBase64": base64.b64encode(content).decode("ascii"),
    }


def remote_url(args: argparse.Namespace, endpoint: str = "/v1/commands") -> str:
    parsed = urllib.parse.urlsplit(args.url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("remote Registry URL must be absolute HTTP(S)")
    loopback = parsed.hostname.lower() in {"127.0.0.1", "::1", "localhost"}
    if parsed.scheme != "https" and not (loopback and args.allow_insecure_loopback):
        raise ValueError("remote Registry client requires HTTPS outside loopback testing")
    if parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise ValueError("remote Registry URL must not contain credentials, query or fragment")
    return args.url.rstrip("/") + endpoint


def client_token(args: argparse.Namespace) -> str:
    token = os.environ.get(args.token_environment)
    if not token:
        raise ValueError("remote Registry token environment is unset")
    return token


def client_ssl_context(args: argparse.Namespace) -> ssl.SSLContext | None:
    if urllib.parse.urlsplit(args.url).scheme == "https":
        return ssl.create_default_context(cafile=args.ca_file)
    return None


def read_http_json(request: urllib.request.Request, args: argparse.Namespace) \
        -> dict[str, Any]:
    try:
        with urllib.request.urlopen(
                request, timeout=args.timeout, context=client_ssl_context(args)) as stream:
            response = json.loads(stream.read())
    except urllib.error.HTTPError as error:
        try:
            message = json.loads(error.read()).get("error", str(error))
        except (UnicodeError, json.JSONDecodeError):
            message = str(error)
        raise ValueError(f"remote Registry rejected request: {message}") from error
    if not isinstance(response, dict):
        raise ValueError("remote Registry response is not an object")
    return response


def client_command(args: argparse.Namespace) -> int:
    try:
        token = client_token(args)
        operation = args.command
        parameters: dict[str, Any] = {}
        artifacts: dict[str, Any] = {}
        if operation == "publish":
            artifacts["package"] = artifact(args.package)
        elif operation == "promote":
            parameters = {
                "channel": args.channel, "expectedGeneration": args.expected_generation,
            }
            artifacts["lock"] = artifact(args.lock)
            supplied = [args.impact_gate, args.runner_attestation, args.gate_authorization]
            if any(supplied) and not all(supplied):
                raise ValueError("remote promotion requires the complete Gate evidence set")
            if all(supplied):
                artifacts.update({
                    "impactGate": artifact(args.impact_gate),
                    "runnerAttestation": artifact(args.runner_attestation),
                    "gateAuthorization": artifact(args.gate_authorization),
                })
        elif operation == "rollback":
            parameters = {
                "channel": args.channel, "expectedGeneration": args.expected_generation,
                "toGeneration": args.to_generation, "reason": args.reason,
            }
        elif operation == "resolve":
            parameters = {"channel": args.channel}
        command = {
            "schemaVersion": 1,
            "product": COMMAND_PRODUCT,
            "operation": operation,
            "registryId": args.registry_id,
            "expectedRevision": args.expected_revision,
            "parameters": parameters,
            "artifacts": artifacts,
        }
        validate_command(command)
        content = package_tool.json_bytes(command)
        request = urllib.request.Request(
            remote_url(args), data=content, method="POST",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Idempotency-Key": args.request_id,
            },
        )
        response = read_http_json(request, args)
        if (not isinstance(response, dict) or response.get("product") != RESPONSE_PRODUCT
                or response.get("requestId") != args.request_id
                or response.get("requestSha256") != canonical_sha(command)
                or response.get("operation") != operation or response.get("passed") is not True):
            raise ValueError("remote Registry response is malformed, stale or rejected")
        if operation == "resolve":
            output = Path(args.output).absolute()
            if output.exists():
                raise ValueError(f"remote Registry resolution output already exists: {output}")
            output.parent.mkdir(parents=True, exist_ok=True)
            staging = Path(tempfile.mkdtemp(prefix=output.name + ".", dir=output.parent))
            try:
                for item in response["files"]:
                    if not isinstance(item, dict) or set(item) != {"path", "sha256", "dataBase64"}:
                        raise ValueError("remote Registry resolution file is malformed")
                    relative = package_tool.safe_archive_path(item["path"])
                    content = base64.b64decode(item["dataBase64"], validate=True)
                    if package_tool.sha256_bytes(content) != item["sha256"]:
                        raise ValueError("remote Registry resolution file digest changed")
                    destination = staging.joinpath(*relative.parts)
                    registry_tool.exclusive_bytes(destination, content)
                staging.replace(output)
            except Exception:
                shutil.rmtree(staging, ignore_errors=True)
                raise
        if args.report:
            package_tool.write_json(Path(args.report).resolve(), response)
        print(
            f"PDR_TEAM_CONTRACT_REGISTRY_REMOTE_{operation.upper()}_PASS "
            f"request={args.request_id} revision={response['revision']}"
        )
        return 0
    except (OSError, UnicodeError, ValueError) as error:
        print(f"PDR_TEAM_CONTRACT_REGISTRY_REMOTE_ERROR: {error}", file=sys.stderr)
        return 2


def status_client_command(args: argparse.Namespace) -> int:
    try:
        token = client_token(args)
        endpoint = "/v1/requests/" + urllib.parse.quote(args.request_id, safe="")
        request = urllib.request.Request(
            remote_url(args, endpoint), method="GET",
            headers={"Authorization": f"Bearer {token}"},
        )
        response = read_http_json(request, args)
        if (response.get("product") != STATUS_PRODUCT
                or response.get("registryId") != args.registry_id
                or response.get("requestId") != args.request_id
                or response.get("status") not in REQUEST_STATES):
            raise ValueError("remote Registry request status is malformed or stale")
        if args.report:
            package_tool.write_json(Path(args.report).resolve(), response)
        print(
            "PDR_TEAM_CONTRACT_REGISTRY_REMOTE_STATUS_PASS "
            f"request={args.request_id} status={response['status']}"
        )
        return 0
    except (OSError, UnicodeError, ValueError) as error:
        print(f"PDR_TEAM_CONTRACT_REGISTRY_REMOTE_ERROR: {error}", file=sys.stderr)
        return 2


def audit_client_command(args: argparse.Namespace) -> int:
    try:
        token = client_token(args)
        request = urllib.request.Request(
            remote_url(args, "/v1/audit"), method="GET",
            headers={"Authorization": f"Bearer {token}"},
        )
        response = read_http_json(request, args)
        if (response.get("product") != AUDIT_VERIFICATION_PRODUCT
                or response.get("passed") is not True
                or response.get("registryId") != args.registry_id
                or type(response.get("sequence")) is not int):
            raise ValueError("remote Registry audit verification is malformed or stale")
        if args.report:
            package_tool.write_json(Path(args.report).resolve(), response)
        print(
            "PDR_TEAM_CONTRACT_REGISTRY_REMOTE_AUDIT_VERIFY_PASS "
            f"sequence={response['sequence']} head={response['lastRecordSha256']}"
        )
        return 0
    except (OSError, UnicodeError, ValueError) as error:
        print(f"PDR_TEAM_CONTRACT_REGISTRY_REMOTE_ERROR: {error}", file=sys.stderr)
        return 2


def audit_archive_status_client_command(args: argparse.Namespace) -> int:
    try:
        token = client_token(args)
        request = urllib.request.Request(
            remote_url(args, "/v1/audit-archives"), method="GET",
            headers={"Authorization": f"Bearer {token}"},
        )
        response = read_http_json(request, args)
        if (response.get("product") != audit_archive_tool.ARCHIVE_STATUS_PRODUCT
                or response.get("passed") is not True
                or response.get("registryId") != args.registry_id
                or type(response.get("archiveCount")) is not int
                or type(response.get("archivedThroughSequence")) is not int):
            raise ValueError("remote Registry audit archive status is malformed or stale")
        if args.report:
            package_tool.write_json(Path(args.report).resolve(), response)
        print(
            "PDR_TEAM_CONTRACT_REGISTRY_REMOTE_AUDIT_ARCHIVE_STATUS_PASS "
            f"archives={response['archiveCount']} "
            f"through={response['archivedThroughSequence']}"
        )
        return 0
    except (OSError, UnicodeError, ValueError) as error:
        print(f"PDR_TEAM_CONTRACT_REGISTRY_REMOTE_ERROR: {error}", file=sys.stderr)
        return 2


def recovery_client_command(args: argparse.Namespace) -> int:
    try:
        token = client_token(args)
        document = {
            "schemaVersion": 1,
            "product": RECOVERY_PRODUCT,
            "registryId": args.registry_id,
            "targetRequestId": args.target_request_id,
            "targetRequestSha256": args.target_request_sha256,
            "expectedStartedRevision": args.expected_started_revision,
            "expectedCurrentRevision": args.expected_current_revision,
            "disposition": args.disposition,
            "reason": args.reason,
        }
        validate_recovery(document)
        request = urllib.request.Request(
            remote_url(args, "/v1/recoveries"),
            data=package_tool.json_bytes(document), method="POST",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Recovery-Key": args.recovery_id,
            },
        )
        response = read_http_json(request, args)
        if (response.get("product") != RECOVERY_RESPONSE_PRODUCT
                or response.get("passed") is not True
                or response.get("registryId") != args.registry_id
                or response.get("recoveryId") != args.recovery_id
                or response.get("recoverySha256") != canonical_sha(document)
                or response.get("targetRequestId") != args.target_request_id
                or response.get("disposition") != args.disposition):
            raise ValueError("remote Registry recovery response is malformed or stale")
        if args.report:
            package_tool.write_json(Path(args.report).resolve(), response)
        print(
            "PDR_TEAM_CONTRACT_REGISTRY_REMOTE_RECOVER_PASS "
            f"request={args.target_request_id} disposition={args.disposition}"
        )
        return 0
    except (OSError, UnicodeError, ValueError) as error:
        print(f"PDR_TEAM_CONTRACT_REGISTRY_REMOTE_ERROR: {error}", file=sys.stderr)
        return 2


def capacity_client_command(args: argparse.Namespace) -> int:
    try:
        token = client_token(args)
        request = urllib.request.Request(
            remote_url(args, "/v1/capacity"), method="GET",
            headers={"Authorization": f"Bearer {token}"},
        )
        response = read_http_json(request, args)
        if (response.get("product")
                != "PocoDDSRuntimeTeamContractRegistryRemoteCapacity"
                or response.get("passed") is not True
                or response.get("registryId") != args.registry_id
                or not isinstance(response.get("usage"), dict)
                or not isinstance(response.get("limits"), dict)
                or type(response.get("acceptingMutations")) is not bool
                or type(response.get("acceptingRecoveries")) is not bool):
            raise ValueError("remote Registry capacity response is malformed or stale")
        if args.report:
            package_tool.write_json(Path(args.report).resolve(), response)
        print(
            "PDR_TEAM_CONTRACT_REGISTRY_REMOTE_CAPACITY_PASS "
            f"accepting={str(response['acceptingMutations']).lower()} "
            f"requests={response['usage']['activeRequestRecords']} "
            f"audit={response['usage']['auditRecords']}"
        )
        return 0
    except (OSError, UnicodeError, ValueError) as error:
        print(f"PDR_TEAM_CONTRACT_REGISTRY_REMOTE_ERROR: {error}", file=sys.stderr)
        return 2


def remote_drain_client_command(args: argparse.Namespace) -> int:
    try:
        operation = args.remote_drain_operation
        token = client_token(args)
        document = {
            "schemaVersion": 1, "product": REMOTE_DRAIN_COMMAND_PRODUCT,
            "registryId": args.registry_id, "operation": operation,
            "handoffId": args.handoff_id,
            "expectedGeneration": args.expected_generation,
            "expectedRevision": args.expected_revision,
            "expectedStateSha256": str(args.expected_state_sha256).lower(),
            "reason": args.reason if operation in {"start", "resume"} else None,
            "issuedAt": args.issued_at if operation == "finalize" else None,
            "expiresAt": args.expires_at if operation == "finalize" else None,
        }
        validate_remote_drain_command(document)
        request = urllib.request.Request(
            remote_url(args, "/v1/drain"), data=package_tool.json_bytes(document),
            method="POST", headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )
        response = read_http_json(request, args)
        if (response.get("product") != REMOTE_DRAIN_RESPONSE_PRODUCT
                or response.get("passed") is not True
                or response.get("registryId") != args.registry_id
                or response.get("operation") != operation
                or response.get("handoffId") != args.handoff_id
                or type(response.get("replayed")) is not bool
                or not isinstance(response.get("state"), dict)):
            raise ValueError("remote Registry drain response is malformed or stale")
        import team_contract_registry_handoff as handoff_tool
        handoff_tool.validate_state(response["state"], args.registry_id)
        state = response["state"]
        expected_mode = {
            "start": "draining", "finalize": "drained", "resume": "accepting"
        }[operation]
        expected_generation = args.expected_generation + (
            1 if operation in {"start", "resume"} else 0
        )
        if (state["mode"] != expected_mode
                or state["handoffId"] != args.handoff_id
                or state["generation"] != expected_generation
                or state["registryRevision"] != args.expected_revision
                or state["registryStateSha256"]
                    != str(args.expected_state_sha256).lower()
                or (operation in {"start", "resume"}
                    and state["reason"] != args.reason)):
            raise ValueError("remote Registry drain response is not request-bound")
        evidence = response.get("evidence")
        evidence_sha = response.get("evidenceSha256")
        if operation == "finalize":
            if (not isinstance(evidence, dict)
                    or not package_tool.SHA256.fullmatch(str(evidence_sha or ""))):
                raise ValueError("remote Registry finalize response lacks evidence")
            handoff_tool.validate_evidence(evidence)
            if (evidence["handoffId"] != args.handoff_id
                    or evidence["registryId"] != args.registry_id
                    or evidence["nodeId"] != state["nodeId"]
                    or evidence["drainGeneration"] != args.expected_generation
                    or evidence["registryRevision"] != args.expected_revision
                    or evidence["registryStateSha256"]
                        != str(args.expected_state_sha256).lower()
                    or evidence["observedFencingToken"]
                        != state["observedFencingToken"]
                    or evidence["observedGrantSha256"]
                        != state["observedGrantSha256"]
                    or evidence["pendingRequestCount"]
                        != state["pendingRequestCount"]
                    or evidence["pendingRequestSetSha256"]
                        != state["pendingRequestSetSha256"]
                    or evidence["issuedAt"] != registry_tool.utc_time(args.issued_at)
                    or evidence["expiresAt"]
                        != registry_tool.utc_time(args.expires_at)
                    or state["handoffEvidenceSha256"] != evidence_sha):
                raise ValueError(
                    "remote Registry handoff evidence is not request-bound"
                )
            content = package_tool.json_bytes(evidence)
            if package_tool.sha256_bytes(content) != evidence_sha:
                raise ValueError("remote Registry handoff evidence digest changed")
            registry_tool.exclusive_bytes(
                Path(args.evidence_output).resolve(), content
            )
        elif (evidence is not None or evidence_sha is not None
              or state["handoffEvidenceSha256"] is not None):
            raise ValueError("remote Registry non-finalize response contains evidence")
        if args.report:
            package_tool.write_json(Path(args.report).resolve(), response)
        print("PDR_TEAM_CONTRACT_REGISTRY_REMOTE_DRAIN_PASS "
              f"operation={operation} mode={response['state']['mode']} "
              f"generation={response['state']['generation']} "
              f"replayed={str(response['replayed']).lower()}")
        return 0
    except (OSError, UnicodeError, ValueError) as error:
        print(f"PDR_TEAM_CONTRACT_REGISTRY_REMOTE_ERROR: {error}", file=sys.stderr)
        return 2


def remote_drain_status_client_command(args: argparse.Namespace) -> int:
    try:
        token = client_token(args)
        request = urllib.request.Request(
            remote_url(args, "/v1/drain"), method="GET",
            headers={"Authorization": f"Bearer {token}"},
        )
        response = read_http_json(request, args)
        import team_contract_registry_handoff as handoff_tool
        if (response.get("product") != handoff_tool.STATUS_PRODUCT
                or response.get("passed") is not True
                or response.get("registryId") != args.registry_id
                or response.get("mode") not in handoff_tool.MODES
                or type(response.get("generation")) is not int
                or type(response.get("pendingRequestCount")) is not int):
            raise ValueError("remote Registry drain status is malformed or stale")
        if args.report:
            package_tool.write_json(Path(args.report).resolve(), response)
        print("PDR_TEAM_CONTRACT_REGISTRY_REMOTE_DRAIN_STATUS_PASS "
              f"mode={response['mode']} generation={response['generation']} "
              f"pending={response['pendingRequestCount']}")
        return 0
    except (OSError, UnicodeError, ValueError) as error:
        print(f"PDR_TEAM_CONTRACT_REGISTRY_REMOTE_ERROR: {error}", file=sys.stderr)
        return 2


def lease_status_client_command(args: argparse.Namespace) -> int:
    try:
        token = client_token(args)
        request = urllib.request.Request(
            remote_url(args, "/v1/leases"), method="GET",
            headers={"Authorization": f"Bearer {token}"},
        )
        response = read_http_json(request, args)
        command = response.get("commandProcessor")
        writer = response.get("registryWriter")
        if (response.get("product") != LEASE_STATUS_PRODUCT
                or response.get("registryId") != args.registry_id
                or type(response.get("passed")) is not bool
                or type(response.get("acceptingCommands")) is not bool
                or not isinstance(command, dict) or not isinstance(writer, dict)
                or command.get("product") != process_lease.STATUS_PRODUCT
                or writer.get("product") != process_lease.STATUS_PRODUCT
                or type(command.get("active")) is not bool
                or type(writer.get("active")) is not bool):
            raise ValueError("remote Registry lease status is malformed or stale")
        if args.report:
            package_tool.write_json(Path(args.report).resolve(), response)
        marker = "PASS" if response["passed"] else "ERROR"
        stream = sys.stdout if response["passed"] else sys.stderr
        print(
            f"PDR_TEAM_CONTRACT_REGISTRY_REMOTE_LEASE_{marker} "
            f"accepting={str(response['acceptingCommands']).lower()} "
            f"commandEpoch={command['epoch']} writerEpoch={writer['epoch']}",
            file=stream,
        )
        return 0 if response["passed"] else 2
    except (OSError, UnicodeError, ValueError) as error:
        print(f"PDR_TEAM_CONTRACT_REGISTRY_REMOTE_ERROR: {error}", file=sys.stderr)
        return 2


def add_client_arguments(command: argparse.ArgumentParser, mutation: bool = False) -> None:
    command.add_argument("--url", required=True)
    command.add_argument("--registry-id", required=True)
    command.add_argument("--request-id", required=True)
    command.add_argument("--token-environment", required=True)
    command.add_argument("--expected-revision", type=int, required=mutation)
    command.add_argument("--allow-insecure-loopback", action="store_true")
    command.add_argument("--ca-file")
    command.add_argument("--timeout", type=float, default=30.0)
    command.add_argument("--report")
    command.set_defaults(handler=client_command)


def add_query_arguments(command: argparse.ArgumentParser) -> None:
    command.add_argument("--url", required=True)
    command.add_argument("--registry-id", required=True)
    command.add_argument("--token-environment", required=True)
    command.add_argument("--allow-insecure-loopback", action="store_true")
    command.add_argument("--ca-file")
    command.add_argument("--timeout", type=float, default=30.0)
    command.add_argument("--report")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="serve one immutable Registry with scoped RBAC")
    serve.add_argument("--registry", required=True)
    serve.add_argument("--bind", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=9443)
    serve.add_argument("--tls-certificate")
    serve.add_argument("--tls-private-key")
    serve.add_argument("--allow-insecure-loopback", action="store_true")
    serve.add_argument("--control-directory")
    serve.add_argument("--audit-archive-directory")
    serve.add_argument("--access-policy", required=True)
    serve.add_argument("--expected-access-policy-id", required=True)
    serve.add_argument("--expected-access-policy-sha256", required=True)
    serve.add_argument("--access-policy-trust-policy")
    serve.add_argument("--expected-access-policy-trust-policy-id")
    serve.add_argument("--expected-access-policy-trust-policy-sha256")
    serve.add_argument("--trust-policy", required=True)
    serve.add_argument("--expected-trust-policy-id", required=True)
    serve.add_argument("--expected-trust-policy-sha256", required=True)
    serve.add_argument("--runner-trust-policy")
    serve.add_argument("--expected-runner-trust-policy-id")
    serve.add_argument("--expected-runner-trust-policy-sha256")
    serve.add_argument("--gate-authorization-policy")
    serve.add_argument("--expected-gate-authorization-policy-id")
    serve.add_argument("--expected-gate-authorization-policy-sha256")
    serve.add_argument("--verification-time")
    serve.add_argument("--maximum-files", type=int, default=package_tool.MAX_FILES_DEFAULT)
    serve.add_argument("--maximum-expanded-bytes", type=int,
                       default=package_tool.MAX_EXPANDED_BYTES_DEFAULT)
    serve.add_argument("--node-id")
    serve.add_argument("--handoff-evidence-directory")
    serve.add_argument("--handoff-key-id")
    serve.add_argument("--handoff-private-key-environment")
    serve.add_argument("--handoff-private-key-passphrase-environment")
    serve.add_argument("--handoff-leader-verification-time")
    serve.add_argument("--quiet", action="store_true")
    serve.set_defaults(handler=serve_command)
    publish = commands.add_parser("publish", help="upload one signed package without server paths")
    publish.add_argument("--package", required=True)
    add_client_arguments(publish, mutation=True)
    promote = commands.add_parser("promote", help="upload and promote a lock with evidence")
    promote.add_argument("--channel", required=True)
    promote.add_argument("--lock", required=True)
    promote.add_argument("--expected-generation", type=int, required=True)
    promote.add_argument("--impact-gate")
    promote.add_argument("--runner-attestation")
    promote.add_argument("--gate-authorization")
    add_client_arguments(promote, mutation=True)
    rollback = commands.add_parser("rollback", help="remotely create a rollback generation")
    rollback.add_argument("--channel", required=True)
    rollback.add_argument("--expected-generation", type=int, required=True)
    rollback.add_argument("--to-generation", type=int, required=True)
    rollback.add_argument("--reason", required=True)
    add_client_arguments(rollback, mutation=True)
    verify = commands.add_parser("verify", help="remotely verify Registry state and blobs")
    add_client_arguments(verify)
    resolve = commands.add_parser("resolve", help="download a channel resolution without paths")
    resolve.add_argument("--channel", required=True)
    resolve.add_argument("--output", required=True)
    add_client_arguments(resolve)
    status = commands.add_parser("status", help="query a durable request disposition")
    status.add_argument("--request-id", required=True)
    add_query_arguments(status)
    status.set_defaults(handler=status_client_command)
    audit = commands.add_parser(
        "audit-verify", help="verify the remote immutable request audit chain"
    )
    add_query_arguments(audit)
    audit.set_defaults(handler=audit_client_command)
    archive_status = commands.add_parser(
        "audit-archive-status", help="show registered audit archive continuity"
    )
    add_query_arguments(archive_status)
    archive_status.set_defaults(handler=audit_archive_status_client_command)
    capacity = commands.add_parser(
        "capacity", help="show bounded remote control-state usage and limits"
    )
    add_query_arguments(capacity)
    capacity.set_defaults(handler=capacity_client_command)
    def add_remote_drain_arguments(command: argparse.ArgumentParser) -> None:
        command.add_argument("--handoff-id", required=True)
        command.add_argument("--expected-generation", type=int, required=True)
        command.add_argument("--expected-revision", type=int, required=True)
        command.add_argument("--expected-state-sha256", required=True)
        add_query_arguments(command)

    drain_start = commands.add_parser(
        "drain-start", help="remotely close command admission as an operator"
    )
    add_remote_drain_arguments(drain_start)
    drain_start.add_argument("--reason", required=True)
    drain_start.set_defaults(
        handler=remote_drain_client_command, remote_drain_operation="start",
        issued_at=None, expires_at=None, evidence_output=None,
    )
    drain_finalize = commands.add_parser(
        "drain-finalize", help="remotely sign zero-inflight handoff evidence"
    )
    add_remote_drain_arguments(drain_finalize)
    drain_finalize.add_argument("--issued-at", required=True)
    drain_finalize.add_argument("--expires-at", required=True)
    drain_finalize.add_argument("--evidence-output", required=True)
    drain_finalize.set_defaults(
        handler=remote_drain_client_command, remote_drain_operation="finalize",
        reason=None,
    )
    drain_resume = commands.add_parser(
        "drain-resume", help="remotely reopen an authorized old leader"
    )
    add_remote_drain_arguments(drain_resume)
    drain_resume.add_argument("--reason", required=True)
    drain_resume.set_defaults(
        handler=remote_drain_client_command, remote_drain_operation="resume",
        issued_at=None, expires_at=None, evidence_output=None,
    )
    drain_status = commands.add_parser(
        "drain-status", help="inspect remote persistent drain state"
    )
    add_query_arguments(drain_status)
    drain_status.set_defaults(handler=remote_drain_status_client_command)
    leases = commands.add_parser(
        "lease-status", help="inspect remote command and Registry writer leases"
    )
    add_query_arguments(leases)
    leases.set_defaults(handler=lease_status_client_command)
    recover = commands.add_parser(
        "recover", help="explicitly terminate one interrupted remote request"
    )
    recover.add_argument("--recovery-id", required=True)
    recover.add_argument("--target-request-id", required=True)
    recover.add_argument("--target-request-sha256", required=True)
    recover.add_argument("--expected-started-revision", type=int, required=True)
    recover.add_argument("--expected-current-revision", type=int, required=True)
    recover.add_argument("--disposition", choices=("aborted", "uncertain"), required=True)
    recover.add_argument("--reason", required=True)
    add_query_arguments(recover)
    recover.set_defaults(handler=recovery_client_command)
    checkpoint = commands.add_parser(
        "audit-checkpoint", help="sign an externally stored remote audit checkpoint"
    )
    checkpoint.add_argument("--control-directory", required=True)
    checkpoint.add_argument("--audit-archive-directory")
    checkpoint.add_argument("--registry-id", required=True)
    checkpoint.add_argument("--checkpoint-id", required=True)
    checkpoint.add_argument("--auditor-id", required=True)
    checkpoint.add_argument("--key-id", required=True)
    checkpoint.add_argument("--private-key-environment", required=True)
    checkpoint.add_argument("--private-key-passphrase-environment")
    checkpoint.add_argument("--issued-at")
    checkpoint.add_argument("--output", required=True)
    checkpoint.set_defaults(handler=audit_checkpoint_create_command)
    checkpoint_verify = commands.add_parser(
        "audit-checkpoint-verify",
        help="verify external checkpoint signature and audit-chain continuity",
    )
    checkpoint_verify.add_argument("--control-directory", required=True)
    checkpoint_verify.add_argument("--audit-archive-directory")
    checkpoint_verify.add_argument("--registry-id", required=True)
    checkpoint_verify.add_argument("--checkpoint", required=True)
    checkpoint_verify.add_argument("--audit-policy", required=True)
    checkpoint_verify.add_argument("--expected-audit-policy-id", required=True)
    checkpoint_verify.add_argument("--expected-audit-policy-sha256", required=True)
    checkpoint_verify.add_argument("--verification-time")
    checkpoint_verify.add_argument("--report")
    checkpoint_verify.set_defaults(handler=audit_checkpoint_verify_command)
    return result


def main() -> int:
    args = parser().parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
