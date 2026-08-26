#!/usr/bin/env python3
"""Role-separated signed approval for high-risk project configuration changes."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


PRODUCT = "PocoDDSRuntimeProjectConfiguration"
IDENTITY = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._@-]{0,127}$")
RULE_ID = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$")
KEY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
POINTER_TOKEN = re.compile(r"(?:[^~/]|~[01])+")
MAX_RULES = 32
MAX_APPROVERS = 64
MAX_QUORUM = 16
MAX_LIFETIME_SECONDS = 86400


def canonical_json(document: Any) -> bytes:
    return json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def digest(document: Any) -> str:
    return hashlib.sha256(canonical_json(document)).hexdigest()


def bytes_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def file_sha256(path: Path) -> str:
    return bytes_sha256(path.read_bytes())


def self_digest(document: dict[str, Any], field: str) -> str:
    return digest({key: value for key, value in document.items() if key != field})


def load_json_bytes(content: bytes, description: str) -> dict[str, Any]:
    try:
        document = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read {description}: {error}") from error
    if not isinstance(document, dict):
        raise ValueError(f"{description} root must be an object")
    return document


def load_json(path: Path, description: str) -> dict[str, Any]:
    try:
        return load_json_bytes(path.read_bytes(), description)
    except OSError as error:
        raise ValueError(f"cannot read {description}: {path}: {error}") from error


def parse_time(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"configuration approval {field} must be an ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"configuration approval {field} is invalid") from error
    if parsed.tzinfo is None:
        raise ValueError(f"configuration approval {field} requires timezone")
    return parsed.astimezone(timezone.utc)


def validate_pointer(value: Any, field: str) -> str:
    if (not isinstance(value, str) or not value.startswith("/") or value == "/"
            or any(not POINTER_TOKEN.fullmatch(token) for token in value[1:].split("/"))):
        raise ValueError(f"{field} must be a non-root JSON Pointer")
    return value


def pointer_contains(prefix: str, pointer: str) -> bool:
    return pointer == prefix or pointer.startswith(prefix + "/")


def same_or_child(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def exclusive_json(path: Path, document: dict[str, Any]) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(document, indent=2, ensure_ascii=False).encode("utf-8") + b"\n"
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(descriptor)


def confined_file(root: Path, value: str, field: str) -> Path:
    path = (root / value).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as error:
        raise ValueError(f"{field} must stay inside the project root") from error
    if not path.is_file():
        raise FileNotFoundError(f"{field} not found: {path}")
    return path


def validate_policy(document: dict[str, Any]) -> None:
    required = {
        "schemaVersion", "product", "policyId", "maxApprovalLifetimeSeconds",
        "rules", "allowedApprovers", "revokedKeys",
    }
    if set(document) != required or document.get("schemaVersion") != 1 \
            or document.get("product") != PRODUCT \
            or not isinstance(document.get("policyId"), str) \
            or RULE_ID.fullmatch(document["policyId"]) is None:
        raise ValueError("unsupported configuration approval policy")
    lifetime = document.get("maxApprovalLifetimeSeconds")
    if (not isinstance(lifetime, int) or isinstance(lifetime, bool)
            or not 60 <= lifetime <= MAX_LIFETIME_SECONDS):
        raise ValueError("configuration approval policy lifetime is malformed")
    rules = document.get("rules")
    approvers = document.get("allowedApprovers")
    revoked = document.get("revokedKeys")
    if (not isinstance(rules, list) or not 1 <= len(rules) <= MAX_RULES
            or not isinstance(approvers, list) or not 1 <= len(approvers) <= MAX_APPROVERS
            or not isinstance(revoked, list)):
        raise ValueError("configuration approval policy lists are malformed")

    rule_ids: set[str] = set()
    for index, rule in enumerate(rules):
        field = f"rules[{index}]"
        if not isinstance(rule, dict) or set(rule) != {
                "id", "pathPrefixes", "minimumApprovals", "requiredRoles",
                "separateInitiator"}:
            raise ValueError(f"{field} is malformed")
        identifier = rule.get("id")
        if not isinstance(identifier, str) or RULE_ID.fullmatch(identifier) is None \
                or identifier in rule_ids:
            raise ValueError(f"{field}.id is malformed or duplicated")
        rule_ids.add(identifier)
        prefixes = rule.get("pathPrefixes")
        if (not isinstance(prefixes, list) or not prefixes
                or len(prefixes) != len(set(prefixes))):
            raise ValueError(f"{field}.pathPrefixes is malformed")
        for prefix in prefixes:
            validate_pointer(prefix, f"{field}.pathPrefixes")
        minimum = rule.get("minimumApprovals")
        roles = rule.get("requiredRoles")
        if (not isinstance(minimum, int) or isinstance(minimum, bool)
                or not 1 <= minimum <= MAX_QUORUM
                or not isinstance(roles, list) or not roles
                or len(roles) != len(set(roles))
                or any(not isinstance(role, str) or RULE_ID.fullmatch(role) is None
                       for role in roles) or minimum < len(roles)
                or not isinstance(rule.get("separateInitiator"), bool)):
            raise ValueError(f"{field} quorum or role requirements are malformed")

    revoked_ids: set[str] = set()
    for index, item in enumerate(revoked):
        if not isinstance(item, dict) or set(item) != {"keyId", "revokedAt", "reason"}:
            raise ValueError(f"revokedKeys[{index}] is malformed")
        key_id = item.get("keyId")
        if not isinstance(key_id, str) or KEY_ID.fullmatch(key_id) is None \
                or key_id in revoked_ids or not str(item.get("reason", "")).strip():
            raise ValueError(f"revokedKeys[{index}] is malformed")
        revoked_ids.add(key_id)
        parse_time(item.get("revokedAt"), f"revokedKeys[{index}].revokedAt")

    pairs: set[tuple[str, str]] = set()
    key_ids: set[str] = set()
    for index, item in enumerate(approvers):
        field = f"allowedApprovers[{index}]"
        allowed = {
            "approverId", "keyId", "role", "algorithm", "publicKeySha256",
            "ruleIds", "notBefore", "notAfter",
        }
        required_approver = allowed - {"notBefore", "notAfter"}
        if not isinstance(item, dict) or not required_approver.issubset(item) \
                or set(item) - allowed:
            raise ValueError(f"{field} is malformed")
        approver_id, key_id, role = (
            item.get("approverId"), item.get("keyId"), item.get("role")
        )
        pair = (str(approver_id), str(key_id))
        ids = item.get("ruleIds")
        if (not isinstance(approver_id, str) or IDENTITY.fullmatch(approver_id) is None
                or not isinstance(key_id, str) or KEY_ID.fullmatch(key_id) is None
                or not isinstance(role, str) or RULE_ID.fullmatch(role) is None
                or item.get("algorithm") != "Ed25519"
                or SHA256.fullmatch(str(item.get("publicKeySha256", ""))) is None
                or not isinstance(ids, list) or not ids or len(ids) != len(set(ids))
                or any(identifier not in rule_ids for identifier in ids)
                or pair in pairs or key_id in key_ids):
            raise ValueError(f"{field} identity, role, key or scope is malformed")
        pairs.add(pair)
        key_ids.add(key_id)
        not_before = parse_time(item["notBefore"], f"{field}.notBefore") \
            if "notBefore" in item else None
        not_after = parse_time(item["notAfter"], f"{field}.notAfter") \
            if "notAfter" in item else None
        if not_before and not_after and not_before >= not_after:
            raise ValueError(f"{field} validity window is malformed")

    for rule in rules:
        eligible = [item for item in approvers if rule["id"] in item["ruleIds"]]
        identities = {item["approverId"] for item in eligible}
        roles = {item["role"] for item in eligible}
        if len(identities) < rule["minimumApprovals"] \
                or not set(rule["requiredRoles"]).issubset(roles):
            raise ValueError(
                f"configuration approval rule cannot meet its quorum: {rule['id']}"
            )


def load_policy(root: Path, project: dict[str, Any]) -> tuple[Path, dict[str, Any], str] | None:
    configured = project["config"].get("approvalPolicy")
    if not configured:
        return None
    path = confined_file(root, configured, "config.approvalPolicy")
    content = path.read_bytes()
    document = load_json_bytes(content, "configuration approval policy")
    validate_policy(document)
    return path, document, bytes_sha256(content)


def plan_requirements(root: Path, project: dict[str, Any],
                      changes: list[dict[str, str]]) -> dict[str, Any]:
    loaded = load_policy(root, project)
    if loaded is None:
        return {"required": False, "policy": None, "rules": []}
    path, policy, policy_sha = loaded
    requirements: list[dict[str, Any]] = []
    for rule in policy["rules"]:
        changed = sorted({
            change["path"] for change in changes
            if any(pointer_contains(prefix, change["path"])
                   for prefix in rule["pathPrefixes"])
        })
        if changed:
            requirements.append({
                "id": rule["id"],
                "changedPaths": changed,
                "minimumApprovals": rule["minimumApprovals"],
                "requiredRoles": sorted(rule["requiredRoles"]),
                "separateInitiator": rule["separateInitiator"],
            })
    return {
        "required": bool(requirements),
        "policy": {
            "path": path.relative_to(root).as_posix(),
            "policyId": policy["policyId"],
            "sha256": policy_sha,
        },
        "rules": requirements,
    }


def validate_request(request: dict[str, Any]) -> None:
    required = {
        "schemaVersion", "product", "operation", "requestId", "transactionId",
        "project", "planSha256", "policyId", "policySha256", "ticket",
        "initiator", "issuedAt", "expiresAt", "rules", "requestSha256",
    }
    if set(request) != required or request.get("schemaVersion") != 1 \
            or request.get("product") != PRODUCT \
            or request.get("operation") != "project-config-approval-request" \
            or not isinstance(request.get("requestId"), str) \
            or not isinstance(request.get("transactionId"), str) \
            or not isinstance(request.get("project"), str) \
            or SHA256.fullmatch(str(request.get("planSha256", ""))) is None \
            or SHA256.fullmatch(str(request.get("policySha256", ""))) is None \
            or not isinstance(request.get("policyId"), str) \
            or RULE_ID.fullmatch(request["policyId"]) is None \
            or not isinstance(request.get("ticket"), str) or not request["ticket"].strip() \
            or not isinstance(request.get("initiator"), str) \
            or IDENTITY.fullmatch(request["initiator"]) is None \
            or not isinstance(request.get("rules"), list) or not request["rules"] \
            or request.get("requestSha256") != self_digest(request, "requestSha256"):
        raise ValueError("configuration approval request is malformed or corrupted")
    try:
        import uuid
        uuid.UUID(request["requestId"])
        uuid.UUID(request["transactionId"])
    except (ValueError, TypeError, AttributeError) as error:
        raise ValueError("configuration approval request identifiers are malformed") from error
    issued = parse_time(request.get("issuedAt"), "issuedAt")
    expires = parse_time(request.get("expiresAt"), "expiresAt")
    if issued >= expires:
        raise ValueError("configuration approval request validity window is malformed")


def request_command(args: Any) -> int:
    import project_config_transaction as transaction
    import project_manager
    import uuid

    manifest = Path(args.manifest).resolve()
    project = project_manager.validate_manifest(manifest, check_paths=True)
    root = manifest.parent
    plan_path = transaction.confined_path(root, args.plan, "transaction plan", must_exist=True)
    plan = transaction.load_json(plan_path, "configuration transaction plan")
    current_path = transaction.confined_path(
        root, plan.get("current", {}).get("path", ""), "current configuration",
        must_exist=True,
    )
    candidate_path = transaction.confined_path(
        root, plan.get("candidate", {}).get("path", ""), "candidate configuration",
        must_exist=True,
    )
    capabilities, _, _ = transaction.load_capabilities(manifest)
    current = transaction.load_resolved(current_path, project["name"])
    candidate = transaction.load_resolved(candidate_path, project["name"])
    transaction.validate_plan(plan, manifest, capabilities, current, candidate)
    transaction.validate_plan_semantics(
        plan, transaction.create_plan(manifest, current_path, candidate_path)
    )
    approval = plan.get("approval")
    if not isinstance(approval, dict) or approval.get("required") is not True:
        raise ValueError("configuration transaction does not require signed approval")
    loaded = load_policy(root, project)
    if loaded is None:
        raise ValueError("configuration approval policy is unavailable")
    _, policy, policy_sha = loaded
    lifetime = args.expires_in_seconds
    if (not isinstance(lifetime, int) or isinstance(lifetime, bool)
            or not 60 <= lifetime <= policy["maxApprovalLifetimeSeconds"]):
        raise ValueError("configuration approval request lifetime exceeds policy")
    if not isinstance(args.ticket, str) or not args.ticket.strip() \
            or IDENTITY.fullmatch(args.initiator) is None:
        raise ValueError("configuration approval ticket or initiator is malformed")
    issued = datetime.now(timezone.utc)
    request = {
        "schemaVersion": 1,
        "product": PRODUCT,
        "operation": "project-config-approval-request",
        "requestId": str(uuid.uuid4()),
        "transactionId": plan["transactionId"],
        "project": plan["project"],
        "planSha256": transaction.digest(plan),
        "policyId": policy["policyId"],
        "policySha256": policy_sha,
        "ticket": args.ticket.strip(),
        "initiator": args.initiator,
        "issuedAt": issued.isoformat(),
        "expiresAt": (issued + timedelta(seconds=lifetime)).isoformat(),
        "rules": approval["rules"],
    }
    request["requestSha256"] = self_digest(request, "requestSha256")
    output = Path(args.output).resolve()
    exclusive_json(output, request)
    print(
        f"PDR_PROJECT_CONFIG_APPROVAL_REQUEST_PASS transaction={plan['transactionId']} "
        f"rules={len(approval['rules'])} output={output}"
    )
    return 0


def approve_command(args: Any) -> int:
    request_path = Path(args.request).resolve()
    payload = request_path.read_bytes()
    request = load_json_bytes(payload, "configuration approval request")
    validate_request(request)
    now = datetime.now(timezone.utc)
    if now >= parse_time(request["expiresAt"], "expiresAt"):
        raise ValueError("configuration approval request has expired")
    if IDENTITY.fullmatch(args.approver_id) is None or KEY_ID.fullmatch(args.key_id) is None:
        raise ValueError("configuration approver or key identity is malformed")
    key_value = os.environ.get(args.private_key_path_environment)
    if not key_value:
        raise ValueError("configuration approval private key path environment is unset")
    passphrase = None
    if args.private_key_passphrase_environment:
        value = os.environ.get(args.private_key_passphrase_environment)
        if value is None:
            raise ValueError("configuration approval key passphrase environment is unset")
        passphrase = value.encode("utf-8")
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
    except ImportError as error:
        raise ValueError("Ed25519 approval requires the release-host cryptography package") from error
    key = load_pem_private_key(Path(key_value).read_bytes(), password=passphrase)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("configuration approval private key is not Ed25519")
    signature = {
        "schemaVersion": 1,
        "product": PRODUCT,
        "algorithm": "Ed25519",
        "approverId": args.approver_id,
        "keyId": args.key_id,
        "manifestSha256": bytes_sha256(payload),
        "signature": base64.b64encode(key.sign(payload)).decode("ascii"),
    }
    output = Path(args.signature_output).resolve()
    exclusive_json(output, signature)
    print(
        f"PDR_PROJECT_CONFIG_APPROVED approver={args.approver_id} "
        f"key={args.key_id} signature={output}"
    )
    return 0


def verify_apply_approval(args: Any, root: Path, project: dict[str, Any],
                          plan: dict[str, Any]) -> dict[str, Any] | None:
    approval = plan.get("approval")
    required = isinstance(approval, dict) and approval.get("required") is True
    signed_fields = (
        "approval_request", "approval_policy", "expected_approval_policy_id",
        "expected_approval_policy_sha256", "approval_trusted_keys_directory",
        "signature_check_executable",
    )
    if required and (
            any(not getattr(args, field, None) for field in signed_fields)
            or not getattr(args, "approval_signature", None)):
        raise ValueError("high-risk configuration plan requires signed approval arguments")

    require_policy = required or bool(getattr(args, "require_approval_policy", False))
    policy_fields = (
        "approval_policy", "expected_approval_policy_id",
        "expected_approval_policy_sha256",
    )
    if require_policy and any(not getattr(args, field, None) for field in policy_fields):
        raise ValueError("configuration apply requires pinned approval policy arguments")
    if not require_policy:
        if any(getattr(args, field, None) for field in signed_fields) \
                or bool(getattr(args, "approval_signature", [])):
            raise ValueError("signed approval was supplied for a low-risk configuration plan")
        return None

    configured = load_policy(root, project)
    if configured is None:
        raise ValueError("configuration approval policy is unavailable")
    configured_path, configured_policy, configured_sha = configured
    policy_path = Path(args.approval_policy).resolve()
    policy_bytes = policy_path.read_bytes()
    policy = load_json_bytes(policy_bytes, "trusted configuration approval policy")
    validate_policy(policy)
    policy_sha = bytes_sha256(policy_bytes)
    expected_sha = str(args.expected_approval_policy_sha256).lower()
    plan_policy = approval.get("policy")
    if (SHA256.fullmatch(expected_sha) is None or policy_sha != expected_sha
            or configured_sha != expected_sha or policy != configured_policy
            or not isinstance(plan_policy, dict) or plan_policy.get("sha256") != expected_sha
            or policy.get("policyId") != args.expected_approval_policy_id
            or plan_policy.get("policyId") != args.expected_approval_policy_id
            or configured_path != confined_file(root, plan_policy.get("path", ""),
                                                 "plan approval policy")):
        raise ValueError("configuration approval policy differs from the pinned plan policy")

    if not required:
        unexpected_signed = (
            getattr(args, "approval_request", None),
            getattr(args, "approval_trusted_keys_directory", None),
            getattr(args, "signature_check_executable", None),
            getattr(args, "approval_signature", []),
        )
        if any(unexpected_signed):
            raise ValueError("signed approval was supplied for a low-risk configuration plan")
        return None

    request_path = Path(args.approval_request).resolve()
    request_bytes = request_path.read_bytes()
    request = load_json_bytes(request_bytes, "configuration approval request")
    validate_request(request)
    issued = parse_time(request["issuedAt"], "issuedAt")
    expires = parse_time(request["expiresAt"], "expiresAt")
    now = datetime.now(timezone.utc)
    if issued > now + timedelta(minutes=5) or now >= expires \
            or (expires - issued).total_seconds() > policy["maxApprovalLifetimeSeconds"]:
        raise ValueError("configuration approval request is expired or outside policy lifetime")
    expected_request = {
        "transactionId": plan["transactionId"],
        "project": plan["project"],
        "planSha256": digest(plan),
        "policyId": policy["policyId"],
        "policySha256": policy_sha,
        "rules": approval["rules"],
    }
    for field, value in expected_request.items():
        if request.get(field) != value:
            raise ValueError(f"configuration approval request has stale {field}")

    signature_paths = [Path(value).resolve() for value in args.approval_signature]
    if len(signature_paths) != len(set(signature_paths)):
        raise ValueError("duplicate configuration approval signature was supplied")
    verifier = Path(args.signature_check_executable).resolve()
    keys = Path(args.approval_trusted_keys_directory).resolve()
    if not verifier.is_file() or same_or_child(verifier, root):
        raise ValueError("trusted configuration signature verifier is unavailable or project-owned")
    if not keys.is_dir() or same_or_child(keys, root):
        raise ValueError("trusted configuration approval keys must be outside the project")
    revoked = {item["keyId"] for item in policy["revokedKeys"]}
    approvals: list[dict[str, str]] = []
    seen_approvers: set[str] = set()
    seen_keys: set[str] = set()
    approver_records: dict[str, dict[str, Any]] = {}

    with tempfile.TemporaryDirectory(prefix="pdr-config-approval-") as directory:
        staging = Path(directory)
        staged_request = staging / "request.json"
        staged_request.write_bytes(request_bytes)
        for index, signature_path in enumerate(signature_paths):
            signature_bytes = signature_path.read_bytes()
            signature = load_json_bytes(signature_bytes, "configuration approval signature")
            if set(signature) != {
                    "schemaVersion", "product", "algorithm", "approverId", "keyId",
                    "manifestSha256", "signature"} \
                    or signature.get("schemaVersion") != 1 \
                    or signature.get("product") != PRODUCT \
                    or signature.get("algorithm") != "Ed25519" \
                    or signature.get("manifestSha256") != bytes_sha256(request_bytes):
                raise ValueError("configuration approval signature envelope is malformed")
            approver_id, key_id = signature.get("approverId"), signature.get("keyId")
            if (not isinstance(approver_id, str) or not isinstance(key_id, str)
                    or approver_id in seen_approvers or key_id in seen_keys):
                raise ValueError("configuration approval quorum requires distinct people and keys")
            if key_id in revoked:
                raise ValueError(f"configuration approval key is revoked: {key_id}")
            matches = [item for item in policy["allowedApprovers"]
                       if item["approverId"] == approver_id and item["keyId"] == key_id]
            if len(matches) != 1:
                raise ValueError("configuration approver and key are not uniquely allowed")
            record = matches[0]
            not_before = parse_time(record["notBefore"], "approver notBefore") \
                if "notBefore" in record else None
            not_after = parse_time(record["notAfter"], "approver notAfter") \
                if "notAfter" in record else None
            if (not_before and (now < not_before or issued < not_before)) \
                    or (not_after and (now >= not_after or issued >= not_after)):
                raise ValueError("configuration approver key is outside its validity window")
            key_path = keys / f"{key_id}.pem"
            key_bytes = key_path.read_bytes()
            if bytes_sha256(key_bytes) != record["publicKeySha256"]:
                raise ValueError("configuration approval public key is absent or untrusted")
            staged_signature = staging / f"signature-{index}.json"
            staged_key = staging / f"key-{index}.pem"
            staged_signature.write_bytes(signature_bytes)
            staged_key.write_bytes(key_bytes)
            completed = subprocess.run(
                [str(verifier), str(staged_request), str(staged_signature),
                 str(staged_key), key_id, PRODUCT],
                capture_output=True, text=True, check=False,
            )
            if completed.returncode != 0:
                raise ValueError(
                    (completed.stderr or completed.stdout).strip()
                    or "configuration approval signature verification failed"
                )
            seen_approvers.add(approver_id)
            seen_keys.add(key_id)
            approver_records[approver_id] = record
            approvals.append({
                "approverId": approver_id,
                "keyId": key_id,
                "role": record["role"],
                "signatureSha256": bytes_sha256(signature_bytes),
            })

    initiator = request["initiator"]
    for rule in approval["rules"]:
        eligible = [item for item in approvals
                    if rule["id"] in approver_records[item["approverId"]]["ruleIds"]]
        if rule["separateInitiator"] and any(
                item["approverId"] == initiator for item in eligible):
            raise ValueError(
                f"configuration approval rule requires initiator separation: {rule['id']}"
            )
        if len(eligible) < rule["minimumApprovals"]:
            raise ValueError(
                f"configuration approval quorum not met for {rule['id']}: "
                f"{len(eligible)}/{rule['minimumApprovals']}"
            )
        roles = {item["role"] for item in eligible}
        missing = sorted(set(rule["requiredRoles"]) - roles)
        if missing:
            raise ValueError(
                f"configuration approval roles missing for {rule['id']}: {', '.join(missing)}"
            )

    approvals.sort(key=lambda item: (item["approverId"], item["keyId"]))
    return {
        "requestId": request["requestId"],
        "requestFileSha256": bytes_sha256(request_bytes),
        "requestContentSha256": request["requestSha256"],
        "ticket": request["ticket"],
        "initiator": initiator,
        "policyId": policy["policyId"],
        "policySha256": policy_sha,
        "rules": approval["rules"],
        "approvals": approvals,
        "verifiedAt": now.isoformat(),
    }
