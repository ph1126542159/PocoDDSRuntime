#!/usr/bin/env python3
"""Drain a remote Registry and emit signed, portable leader-handoff evidence."""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from pathlib import Path
from typing import Any

import team_contract_package as package_tool
import team_contract_registry as registry_tool
import team_contract_registry_leader as leader_tool
import team_contract_registry_remote as remote_tool


STATE_PRODUCT = "PocoDDSRuntimeTeamContractRegistryDrainState"
EVIDENCE_PRODUCT = "PocoDDSRuntimeTeamContractRegistryHandoffEvidence"
TRUST_PRODUCT = "PocoDDSRuntimeTeamContractRegistryHandoffTrustPolicy"
STATUS_PRODUCT = "PocoDDSRuntimeTeamContractRegistryDrainStatus"
MODES = {"accepting", "draining", "drained"}
EMPTY_PENDING_SHA256 = package_tool.sha256_bytes(package_tool.canonical_bytes([]))
MAX_EVIDENCE_SECONDS = 60 * 60


def state_path(control: Path) -> Path:
    return registry_tool.safe_member(control, "drain-state.json", "Registry drain state")


def validate_state(document: Any, registry_id: str | None = None) -> None:
    fields = {
        "schemaVersion", "product", "registryId", "nodeId", "handoffId",
        "mode", "generation", "registryRevision", "registryStateSha256",
        "pendingRequestCount", "pendingRequestSetSha256", "observedFencingToken",
        "observedGrantSha256", "handoffEvidenceSha256", "auditRecordSha256",
        "reason", "updatedAt",
    }
    if (not isinstance(document, dict) or set(document) != fields
            or document.get("schemaVersion") != 1
            or document.get("product") != STATE_PRODUCT
            or any(not package_tool.IDENTIFIER.fullmatch(str(document.get(name, "")))
                   for name in ("registryId", "nodeId", "handoffId"))
            or (registry_id is not None and document["registryId"] != registry_id)
            or document.get("mode") not in MODES
            or type(document.get("generation")) is not int
            or document["generation"] < 1
            or type(document.get("registryRevision")) is not int
            or document["registryRevision"] < 0
            or not package_tool.SHA256.fullmatch(
                str(document.get("registryStateSha256", "")))
            or type(document.get("pendingRequestCount")) is not int
            or document["pendingRequestCount"] < 0
            or not package_tool.SHA256.fullmatch(
                str(document.get("pendingRequestSetSha256", "")))
            or (document.get("observedFencingToken") is not None
                and (type(document["observedFencingToken"]) is not int
                     or document["observedFencingToken"] < 1))
            or any(document.get(name) is not None
                   and not package_tool.SHA256.fullmatch(str(document[name]))
                   for name in ("observedGrantSha256", "handoffEvidenceSha256",
                                "auditRecordSha256"))
            or not isinstance(document.get("reason"), str)
            or not 1 <= len(document["reason"]) <= 512):
        raise ValueError("Registry drain state is malformed")
    package_tool.parse_time(document.get("updatedAt"), "drain state updatedAt")
    if document["mode"] == "drained":
        if (document["pendingRequestCount"] != 0
                or document["pendingRequestSetSha256"] != EMPTY_PENDING_SHA256
                or document["observedFencingToken"] is None
                or document["observedGrantSha256"] is None
                or document["handoffEvidenceSha256"] is None
                or document["auditRecordSha256"] is None):
            raise ValueError("completed Registry drain lacks handoff evidence")
    elif document["mode"] == "accepting" and (
            document["observedFencingToken"] is not None
            or document["observedGrantSha256"] is not None
            or document["handoffEvidenceSha256"] is not None):
        raise ValueError("accepting Registry drain state retains fence evidence")


def read_state(control: Path, registry_id: str | None = None) \
        -> tuple[dict[str, Any], str] | None:
    path = state_path(control)
    if not path.exists():
        return None
    if registry_tool.linklike(path) or not path.is_file():
        raise ValueError("Registry drain state must be a regular file")
    content = path.read_bytes()
    try:
        document = json.loads(content)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("Registry drain state is invalid JSON") from error
    validate_state(document, registry_id)
    return document, package_tool.sha256_bytes(content)


def require_command_admission(control: Path, registry_id: str) -> None:
    loaded = read_state(control, registry_id)
    if loaded is not None and loaded[0]["mode"] != "accepting":
        raise ValueError(
            f"remote Registry is {loaded[0]['mode']}; command admission is closed"
        )


def pending_requests(control: Path) -> tuple[list[str], str]:
    result: list[str] = []
    root = registry_tool.safe_member(control, "requests", "remote request records")
    if root.is_dir():
        for path in sorted(root.rglob("*.json")):
            if registry_tool.linklike(path) or not path.is_file():
                raise ValueError("remote Registry request record must be a regular file")
            try:
                candidate = json.loads(path.read_bytes())
            except (UnicodeError, json.JSONDecodeError) as error:
                raise ValueError("remote Registry request record is invalid JSON") from error
            request_id = candidate.get("requestId") if isinstance(candidate, dict) else None
            if not package_tool.IDENTIFIER.fullmatch(str(request_id or "")):
                raise ValueError("remote Registry request identity is malformed")
            expected_path, record = remote_tool.load_request_record(control, request_id)
            if expected_path != path.resolve():
                raise ValueError("remote Registry request record path changed")
            if record["status"] == "pending":
                result.append(request_id)
    result.sort()
    return result, package_tool.sha256_bytes(package_tool.canonical_bytes(result))


def _control(value: str | Path) -> Path:
    supplied = Path(value)
    if registry_tool.linklike(supplied):
        raise ValueError("Registry remote control directory must not be a link")
    control = supplied.resolve()
    control.mkdir(parents=True, exist_ok=True)
    if registry_tool.linklike(control) or not control.is_dir():
        raise ValueError("Registry remote control directory is unavailable")
    return control


def _outside(path: Path, root: Path, label: str) -> None:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return
    raise ValueError(f"{label} must be outside {root}")


def _archive(args: argparse.Namespace) -> Path | None:
    if not args.audit_archive_directory:
        return None
    return Path(args.audit_archive_directory).resolve()


def _ensure_audit(control: Path, registry_id: str, archive: Path | None) -> None:
    remote_tool.bootstrap_request_audit(control, registry_id, archive)
    remote_tool.activate_audit(control, registry_id, archive)
    remote_tool.verify_audit_chain(control, registry_id, archive_directory=archive)


def _write_state(control: Path, document: dict[str, Any]) -> None:
    validate_state(document)
    package_tool.write_json(state_path(control), document)


def _identity(args: argparse.Namespace) \
        -> tuple[Path, dict[str, Any], dict[str, Any]]:
    root = registry_tool.registry_root(args.registry)
    pointer, state, _ = registry_tool.read_current(root)
    if (state["registryId"] != args.registry_id
            or pointer["revision"] != args.expected_revision
            or pointer["stateSha256"] != str(args.expected_state_sha256).lower()):
        raise ValueError("Registry handoff baseline changed")
    return root, pointer, state


def start_command(args: argparse.Namespace) -> int:
    try:
        if any(not package_tool.IDENTIFIER.fullmatch(str(value)) for value in (
                args.registry_id, args.node_id, args.handoff_id, args.operator)):
            raise ValueError("Registry drain identity is malformed")
        if (args.expected_generation < 0
                or not isinstance(args.reason, str)
                or not 1 <= len(args.reason) <= 512):
            raise ValueError("Registry drain baseline or reason is malformed")
        _, pointer, state = _identity(args)
        control = _control(args.control_directory)
        archive = _archive(args)
        with remote_tool.ControlLease(control) as lease:
            lease.assert_current()
            _ensure_audit(control, state["registryId"], archive)
            loaded = read_state(control, state["registryId"])
            if loaded is None:
                if args.expected_generation != 0:
                    raise ValueError("Registry drain generation changed")
                generation = 1
            else:
                current = loaded[0]
                if current["generation"] != args.expected_generation:
                    raise ValueError("Registry drain generation changed")
                if (current["mode"] == "draining"
                        and current["handoffId"] == args.handoff_id
                        and current["nodeId"] == args.node_id
                        and current["registryRevision"] == pointer["revision"]
                        and current["registryStateSha256"] == pointer["stateSha256"]):
                    if not getattr(args, "quiet", False):
                        print("PDR_TEAM_CONTRACT_REGISTRY_DRAIN_START_PASS "
                              "existing=true "
                              f"generation={current['generation']}")
                    return 0
                if current["mode"] != "accepting":
                    raise ValueError("Registry is already draining or drained")
                generation = current["generation"] + 1
            pending, pending_sha = pending_requests(control)
            request_sha = package_tool.sha256_bytes(package_tool.canonical_bytes({
                "handoffId": args.handoff_id, "generation": generation,
                "revision": pointer["revision"], "stateSha256": pointer["stateSha256"],
                "reason": args.reason,
            }))
            _, audit_sha = remote_tool.append_audit_record(
                control, state["registryId"], "handoff-draining",
                archive_directory=archive, request_id=args.handoff_id,
                request_sha=request_sha, principal_id=args.operator,
                operation="registry-handoff", started_revision=pointer["revision"],
                final_revision=pointer["revision"],
                final_state_sha=pointer["stateSha256"], outcome="pending",
                response_sha=None, recovery_id=None, reason=args.reason,
            )
            document = {
                "schemaVersion": 1, "product": STATE_PRODUCT,
                "registryId": state["registryId"], "nodeId": args.node_id,
                "handoffId": args.handoff_id, "mode": "draining",
                "generation": generation, "registryRevision": pointer["revision"],
                "registryStateSha256": pointer["stateSha256"],
                "pendingRequestCount": len(pending),
                "pendingRequestSetSha256": pending_sha,
                "observedFencingToken": None, "observedGrantSha256": None,
                "handoffEvidenceSha256": None, "auditRecordSha256": audit_sha,
                "reason": args.reason, "updatedAt": registry_tool.utc_time(None),
            }
            _write_state(control, document)
        if args.report:
            package_tool.write_json(Path(args.report).resolve(), document)
        if not getattr(args, "quiet", False):
            print("PDR_TEAM_CONTRACT_REGISTRY_DRAIN_START_PASS "
                  f"generation={generation} pending={len(pending)}")
        return 0
    except (OSError, UnicodeError, ValueError, RuntimeError,
            json.JSONDecodeError) as error:
        if getattr(args, "raise_errors", False):
            raise
        print(f"PDR_TEAM_CONTRACT_REGISTRY_DRAIN_ERROR: {error}", file=sys.stderr)
        return 2


def validate_trust_policy(document: Any) -> None:
    fields = {"schemaVersion", "product", "policyId", "allowedSigners", "revokedKeys"}
    if (not isinstance(document, dict) or set(document) != fields
            or document.get("schemaVersion") != 1
            or document.get("product") != TRUST_PRODUCT
            or not package_tool.IDENTIFIER.fullmatch(str(document.get("policyId", "")))
            or not isinstance(document.get("allowedSigners"), list)
            or not document["allowedSigners"] or len(document["allowedSigners"]) > 64
            or not isinstance(document.get("revokedKeys"), list)
            or len(document["revokedKeys"]) > 64):
        raise ValueError("Registry handoff trust policy is malformed")
    fields_signer = {
        "keyId", "algorithm", "publicKey", "publicKeySha256", "registryIds",
        "nodeIds", "notBefore", "notAfter",
    }
    seen: set[str] = set()
    for signer in document["allowedSigners"]:
        if (not isinstance(signer, dict) or set(signer) != fields_signer
                or not package_tool.IDENTIFIER.fullmatch(str(signer.get("keyId", "")))
                or signer["keyId"] in seen or signer.get("algorithm") != "Ed25519"
                or not isinstance(signer.get("publicKey"), str)
                or Path(signer["publicKey"]).is_absolute()
                or len(Path(signer["publicKey"]).parts) != 2
                or Path(signer["publicKey"]).parts[0] != "keys"
                or not package_tool.SHA256.fullmatch(
                    str(signer.get("publicKeySha256", "")))
                or any(not isinstance(signer.get(name), list) or not signer[name]
                       or len(signer[name]) > 128
                       or len(signer[name]) != len(set(signer[name]))
                       or any(not package_tool.IDENTIFIER.fullmatch(str(item))
                              for item in signer[name])
                       for name in ("registryIds", "nodeIds"))):
            raise ValueError("Registry handoff trusted signer is malformed")
        before = package_tool.parse_time(signer["notBefore"], "handoff signer notBefore")
        after = package_tool.parse_time(signer["notAfter"], "handoff signer notAfter")
        if before >= after:
            raise ValueError("Registry handoff signer validity is reversed")
        seen.add(signer["keyId"])
    revoked: set[str] = set()
    for item in document["revokedKeys"]:
        if (not isinstance(item, dict)
                or set(item) != {"keyId", "revokedAt", "reason"}
                or not package_tool.IDENTIFIER.fullmatch(str(item.get("keyId", "")))
                or item["keyId"] in revoked
                or not isinstance(item.get("reason"), str)
                or not 1 <= len(item["reason"]) <= 512):
            raise ValueError("Registry handoff revoked signer is malformed")
        package_tool.parse_time(item["revokedAt"], "handoff signer revokedAt")
        revoked.add(item["keyId"])


def load_trust_policy(path: str | Path, expected_id: str,
                      expected_sha: str) -> tuple[dict[str, Any], str, Path]:
    trust_path = package_tool.resolved_path(path, "Registry handoff trust policy")
    content = trust_path.read_bytes()
    try:
        document = json.loads(content)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("Registry handoff trust policy is invalid JSON") from error
    actual = package_tool.sha256_bytes(content)
    if (document.get("policyId") != expected_id
            or actual != str(expected_sha).lower()):
        raise ValueError("Registry handoff trust policy identity is not pinned")
    validate_trust_policy(document)
    return document, actual, trust_path


def validate_evidence(document: Any) -> None:
    fields = {
        "schemaVersion", "product", "handoffId", "registryId", "nodeId",
        "drainGeneration", "registryRevision", "registryStateSha256",
        "observedFencingToken", "observedGrantSha256", "pendingRequestCount",
        "pendingRequestSetSha256", "auditSequence", "auditHeadSha256",
        "issuedAt", "expiresAt", "signer",
    }
    if (not isinstance(document, dict) or set(document) != fields
            or document.get("schemaVersion") != 1
            or document.get("product") != EVIDENCE_PRODUCT
            or any(not package_tool.IDENTIFIER.fullmatch(str(document.get(name, "")))
                   for name in ("handoffId", "registryId", "nodeId"))
            or any(type(document.get(name)) is not int or document[name] < minimum
                   for name, minimum in (("drainGeneration", 1),
                                         ("registryRevision", 0),
                                         ("observedFencingToken", 1),
                                         ("auditSequence", 0)))
            or document.get("pendingRequestCount") != 0
            or document.get("pendingRequestSetSha256") != EMPTY_PENDING_SHA256
            or any(not package_tool.SHA256.fullmatch(str(document.get(name, "")))
                   for name in ("registryStateSha256", "observedGrantSha256",
                                "auditHeadSha256"))):
        raise ValueError("Registry handoff evidence is malformed")
    signer = document.get("signer")
    if (not isinstance(signer, dict)
            or set(signer) != {"keyId", "algorithm", "signature"}
            or not package_tool.IDENTIFIER.fullmatch(str(signer.get("keyId", "")))
            or signer.get("algorithm") != "Ed25519"
            or not isinstance(signer.get("signature"), str)):
        raise ValueError("Registry handoff evidence signer is malformed")
    try:
        signature = base64.b64decode(signer["signature"], validate=True)
    except (ValueError, TypeError) as error:
        raise ValueError("Registry handoff signature encoding is invalid") from error
    if len(signature) != 64:
        raise ValueError("Registry handoff signature length is invalid")
    issued = package_tool.parse_time(document["issuedAt"], "handoff issuedAt")
    expires = package_tool.parse_time(document["expiresAt"], "handoff expiresAt")
    if issued >= expires or (expires - issued).total_seconds() > MAX_EVIDENCE_SECONDS:
        raise ValueError("Registry handoff evidence validity is malformed")


def evidence_payload(document: dict[str, Any]) -> dict[str, Any]:
    payload = dict(document)
    signer = dict(payload["signer"])
    signer.pop("signature", None)
    payload["signer"] = signer
    return payload


def verify_evidence(document: dict[str, Any], trust: dict[str, Any],
                    trust_path: Path, at: Any) -> dict[str, str]:
    validate_evidence(document)
    when = package_tool.verification_time(at)
    issued = package_tool.parse_time(document["issuedAt"], "handoff issuedAt")
    expires = package_tool.parse_time(document["expiresAt"], "handoff expiresAt")
    if not issued <= when < expires:
        raise ValueError("Registry handoff evidence is not currently active")
    key_id = document["signer"]["keyId"]
    matches = [item for item in trust["allowedSigners"]
               if item["keyId"] == key_id
               and document["registryId"] in item["registryIds"]
               and document["nodeId"] in item["nodeIds"]]
    if len(matches) != 1:
        raise ValueError("Registry handoff signer is not trusted for this node")
    signer = matches[0]
    if (issued < package_tool.parse_time(signer["notBefore"], "signer notBefore")
            or issued >= package_tool.parse_time(signer["notAfter"], "signer notAfter")):
        raise ValueError("Registry handoff evidence is outside signer validity")
    for revoked in trust["revokedKeys"]:
        if (revoked["keyId"] == key_id
                and when >= package_tool.parse_time(revoked["revokedAt"], "revokedAt")):
            raise ValueError("Registry handoff signer is revoked")
    public_path = registry_tool.safe_member(
        trust_path.parent, signer["publicKey"], "Registry handoff public key"
    )
    public_bytes = public_path.read_bytes()
    if package_tool.sha256_bytes(public_bytes) != signer["publicKeySha256"]:
        raise ValueError("Registry handoff public key digest changed")
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        from cryptography.hazmat.primitives.serialization import load_pem_public_key
        key = load_pem_public_key(public_bytes)
        if not isinstance(key, Ed25519PublicKey):
            raise ValueError("Registry handoff public key is not Ed25519")
        key.verify(
            base64.b64decode(document["signer"]["signature"], validate=True),
            package_tool.canonical_bytes(evidence_payload(document)),
        )
    except ImportError as error:
        raise ValueError("Registry handoff verification requires cryptography") from error
    except Exception as error:
        if isinstance(error, ValueError):
            raise
        raise ValueError("Registry handoff Ed25519 verification failed") from error
    return {"keyId": key_id, "publicKeySha256": signer["publicKeySha256"]}


def load_and_verify_evidence(evidence_path: str | Path, trust_policy: str | Path,
                             expected_trust_id: str, expected_trust_sha: str,
                             at: Any) -> tuple[dict[str, Any], str]:
    path = package_tool.resolved_path(evidence_path, "Registry handoff evidence")
    content = path.read_bytes()
    try:
        document = json.loads(content)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("Registry handoff evidence is invalid JSON") from error
    trust, _, trust_path = load_trust_policy(
        trust_policy, expected_trust_id, expected_trust_sha
    )
    verify_evidence(document, trust, trust_path, at)
    return document, package_tool.sha256_bytes(content)


def finalize_command(args: argparse.Namespace) -> int:
    committed = False
    try:
        if any(not package_tool.IDENTIFIER.fullmatch(str(value)) for value in (
                args.registry_id, args.node_id, args.handoff_id, args.operator,
                args.key_id)):
            raise ValueError("Registry handoff finalize identity is malformed")
        root, pointer, state = _identity(args)
        control = _control(args.control_directory)
        output = Path(args.output).resolve()
        _outside(output, root, "Registry handoff evidence")
        _outside(output, control, "Registry handoff evidence")
        archive = _archive(args)
        with remote_tool.ControlLease(control) as lease:
            lease.assert_current()
            _ensure_audit(control, state["registryId"], archive)
            loaded = read_state(control, state["registryId"])
            if loaded is None:
                raise ValueError("Registry is not draining")
            current = loaded[0]
            if (current["mode"] != "draining"
                    or current["generation"] != args.expected_generation
                    or current["handoffId"] != args.handoff_id
                    or current["nodeId"] != args.node_id
                    or current["registryRevision"] != pointer["revision"]
                    or current["registryStateSha256"] != pointer["stateSha256"]):
                raise ValueError("Registry drain state changed before finalize")
            pending, pending_sha = pending_requests(control)
            if pending:
                raise ValueError(
                    "Registry drain still has pending requests requiring recovery: "
                    + ",".join(pending[:8])
                )
            _, fence, grant_sha = leader_tool.verify_registry_fenced(
                root, args.leader_verification_time
            )
            audit = remote_tool.verify_audit_chain(
                control, state["registryId"], archive_directory=archive
            )
            evidence = {
                "schemaVersion": 1, "product": EVIDENCE_PRODUCT,
                "handoffId": args.handoff_id, "registryId": state["registryId"],
                "nodeId": args.node_id, "drainGeneration": current["generation"],
                "registryRevision": pointer["revision"],
                "registryStateSha256": pointer["stateSha256"],
                "observedFencingToken": fence["fencingToken"],
                "observedGrantSha256": grant_sha, "pendingRequestCount": 0,
                "pendingRequestSetSha256": pending_sha,
                "auditSequence": audit["sequence"],
                "auditHeadSha256": audit["headSha256"],
                "issuedAt": registry_tool.utc_time(args.issued_at),
                "expiresAt": registry_tool.utc_time(args.expires_at),
                "signer": {"keyId": args.key_id, "algorithm": "Ed25519"},
            }
            key = leader_tool._private_key(args)
            evidence["signer"]["signature"] = base64.b64encode(
                key.sign(package_tool.canonical_bytes(evidence))
            ).decode("ascii")
            validate_evidence(evidence)
            content = package_tool.json_bytes(evidence)
            evidence_sha = package_tool.sha256_bytes(content)
            registry_tool.exclusive_bytes(output, content)
            _, audit_sha = remote_tool.append_audit_record(
                control, state["registryId"], "handoff-completed",
                archive_directory=archive, request_id=args.handoff_id,
                request_sha=loaded[1], principal_id=args.operator,
                operation="registry-handoff", started_revision=pointer["revision"],
                final_revision=pointer["revision"],
                final_state_sha=pointer["stateSha256"], outcome="completed",
                response_sha=evidence_sha, recovery_id=None,
                reason=f"fencingToken={fence['fencingToken']}",
            )
            document = dict(current)
            document.update({
                "mode": "drained", "pendingRequestCount": 0,
                "pendingRequestSetSha256": pending_sha,
                "observedFencingToken": fence["fencingToken"],
                "observedGrantSha256": grant_sha,
                "handoffEvidenceSha256": evidence_sha,
                "auditRecordSha256": audit_sha,
                "updatedAt": registry_tool.utc_time(None),
            })
            _write_state(control, document)
            committed = True
        if args.report:
            package_tool.write_json(Path(args.report).resolve(), document)
        if not getattr(args, "quiet", False):
            print("PDR_TEAM_CONTRACT_REGISTRY_DRAIN_FINALIZE_PASS "
                  f"generation={document['generation']} "
                  f"token={fence['fencingToken']} evidence={evidence_sha}")
        return 0
    except (OSError, UnicodeError, ValueError, RuntimeError,
            json.JSONDecodeError) as error:
        if getattr(args, "raise_errors", False):
            raise
        marker = "COMMITTED_ERROR" if committed else "ERROR"
        print(f"PDR_TEAM_CONTRACT_REGISTRY_DRAIN_{marker}: {error}", file=sys.stderr)
        return 3 if committed else 2


def resume_command(args: argparse.Namespace) -> int:
    try:
        if any(not package_tool.IDENTIFIER.fullmatch(str(value)) for value in (
                args.registry_id, args.node_id, args.handoff_id, args.operator)):
            raise ValueError("Registry drain resume identity is malformed")
        root, pointer, state = _identity(args)
        registry_tool.require_primary(root)
        control = _control(args.control_directory)
        archive = _archive(args)
        with remote_tool.ControlLease(control) as lease:
            lease.assert_current()
            _ensure_audit(control, state["registryId"], archive)
            loaded = read_state(control, state["registryId"])
            if loaded is None:
                raise ValueError("Registry has no drain state to resume")
            current = loaded[0]
            if (current["generation"] != args.expected_generation
                    or current["nodeId"] != args.node_id
                    or current["handoffId"] != args.handoff_id
                    or current["mode"] == "accepting"):
                raise ValueError("Registry drain resume baseline changed")
            _, audit_sha = remote_tool.append_audit_record(
                control, state["registryId"], "handoff-resumed",
                archive_directory=archive, request_id=args.handoff_id,
                request_sha=loaded[1], principal_id=args.operator,
                operation="registry-handoff", started_revision=pointer["revision"],
                final_revision=pointer["revision"],
                final_state_sha=pointer["stateSha256"], outcome="completed",
                response_sha=None, recovery_id=None, reason=args.reason,
            )
            pending, pending_sha = pending_requests(control)
            document = dict(current)
            document.update({
                "mode": "accepting", "generation": current["generation"] + 1,
                "registryRevision": pointer["revision"],
                "registryStateSha256": pointer["stateSha256"],
                "pendingRequestCount": len(pending),
                "pendingRequestSetSha256": pending_sha,
                "observedFencingToken": None, "observedGrantSha256": None,
                "handoffEvidenceSha256": None, "auditRecordSha256": audit_sha,
                "reason": args.reason, "updatedAt": registry_tool.utc_time(None),
            })
            _write_state(control, document)
        if args.report:
            package_tool.write_json(Path(args.report).resolve(), document)
        if not getattr(args, "quiet", False):
            print("PDR_TEAM_CONTRACT_REGISTRY_DRAIN_RESUME_PASS "
                  f"generation={document['generation']}")
        return 0
    except (OSError, UnicodeError, ValueError, RuntimeError,
            json.JSONDecodeError) as error:
        if getattr(args, "raise_errors", False):
            raise
        print(f"PDR_TEAM_CONTRACT_REGISTRY_DRAIN_ERROR: {error}", file=sys.stderr)
        return 2


def status_command(args: argparse.Namespace) -> int:
    try:
        control = _control(args.control_directory)
        with remote_tool.ControlLease(control) as lease:
            lease.assert_current()
            loaded = read_state(control, args.registry_id)
            if loaded is None:
                raise ValueError("Registry drain state is unavailable")
            state = loaded[0]
            pending, pending_sha = pending_requests(control)
            report = {
                "schemaVersion": 1, "product": STATUS_PRODUCT, "passed": True,
                "registryId": state["registryId"], "nodeId": state["nodeId"],
                "handoffId": state["handoffId"], "mode": state["mode"],
                "generation": state["generation"],
                "registryRevision": state["registryRevision"],
                "registryStateSha256": state["registryStateSha256"],
                "pendingRequestCount": len(pending),
                "pendingRequestSetSha256": pending_sha,
                "observedFencingToken": state["observedFencingToken"],
                "handoffEvidenceSha256": state["handoffEvidenceSha256"],
                "observedAt": registry_tool.utc_time(None),
            }
        if args.report:
            package_tool.write_json(Path(args.report).resolve(), report)
        if not getattr(args, "quiet", False):
            print("PDR_TEAM_CONTRACT_REGISTRY_DRAIN_STATUS_PASS "
                  f"mode={report['mode']} generation={report['generation']} "
                  f"pending={report['pendingRequestCount']}")
        return 0
    except (OSError, UnicodeError, ValueError, RuntimeError,
            json.JSONDecodeError) as error:
        if getattr(args, "raise_errors", False):
            raise
        print(f"PDR_TEAM_CONTRACT_REGISTRY_DRAIN_ERROR: {error}", file=sys.stderr)
        return 2


def _common(command: argparse.ArgumentParser, identity: bool = True) -> None:
    command.add_argument("--control-directory", required=True)
    command.add_argument("--audit-archive-directory")
    command.add_argument("--registry-id", required=True)
    if identity:
        command.add_argument("--registry", required=True)
        command.add_argument("--node-id", required=True)
        command.add_argument("--handoff-id", required=True)
        command.add_argument("--expected-generation", type=int, required=True)
        command.add_argument("--expected-revision", type=int, required=True)
        command.add_argument("--expected-state-sha256", required=True)
        command.add_argument("--operator", required=True)
    command.add_argument("--report")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    start = commands.add_parser("start", help="persistently close command admission")
    _common(start)
    start.add_argument("--reason", required=True)
    start.set_defaults(handler=start_command)
    finalize = commands.add_parser(
        "finalize", help="prove zero pending requests and sign handoff evidence"
    )
    _common(finalize)
    finalize.add_argument("--leader-verification-time")
    finalize.add_argument("--issued-at", required=True)
    finalize.add_argument("--expires-at", required=True)
    finalize.add_argument("--key-id", required=True)
    finalize.add_argument("--private-key-environment", required=True)
    finalize.add_argument("--private-key-passphrase-environment")
    finalize.add_argument("--output", required=True)
    finalize.set_defaults(handler=finalize_command)
    resume = commands.add_parser("resume", help="reopen a still-authorized old leader")
    _common(resume)
    resume.add_argument("--reason", required=True)
    resume.set_defaults(handler=resume_command)
    status = commands.add_parser("status", help="inspect persistent drain state")
    _common(status, identity=False)
    status.set_defaults(handler=status_command)
    return result


def main() -> int:
    args = parser().parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
