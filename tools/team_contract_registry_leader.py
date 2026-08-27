#!/usr/bin/env python3
"""Issue external Registry leader grants and activate fenced single-writer nodes."""

from __future__ import annotations

import argparse
import base64
import json
import os
import secrets
import sys
from pathlib import Path
from typing import Any

import process_file_lease as process_lease
import team_contract_package as package_tool
import team_contract_registry as registry_tool
import team_contract_registry_leader_backend as backend_tool


GRANT_PRODUCT = "PocoDDSRuntimeTeamContractRegistryLeaderGrant"
TRUST_PRODUCT = "PocoDDSRuntimeTeamContractRegistryLeaderTrustPolicy"
BINDING_PRODUCT = "PocoDDSRuntimeTeamContractRegistryLeaderBinding"
FENCING_STATE_PRODUCT = "PocoDDSRuntimeTeamContractRegistryFencingState"
STATUS_PRODUCT = "PocoDDSRuntimeTeamContractRegistryLeaderStatus"
REPORT_PRODUCT = "PocoDDSRuntimeTeamContractRegistryLeaderActivation"
MAX_GRANT_SECONDS = 24 * 60 * 60
ZERO_SHA256 = "0" * 64


def _outside(path: Path, root: Path, label: str) -> None:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return
    raise ValueError(f"{label} must be outside the Registry root")


def _directory(value: str | Path, create: bool = False) -> Path:
    supplied = Path(value)
    if registry_tool.linklike(supplied):
        raise ValueError("Registry leader authority must not be a link")
    path = supplied.resolve()
    if create:
        path.mkdir(parents=True, exist_ok=True)
    if not path.is_dir() or registry_tool.linklike(path):
        raise FileNotFoundError(f"Registry leader authority is unavailable: {path}")
    return path


def _json_file(path: Path, label: str) -> tuple[dict[str, Any], bytes, str]:
    if registry_tool.linklike(path) or not path.is_file():
        raise ValueError(f"{label} must be a regular file")
    content = path.read_bytes()
    try:
        document = json.loads(content)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} is invalid JSON") from error
    if not isinstance(document, dict):
        raise ValueError(f"{label} must be a JSON object")
    return document, content, package_tool.sha256_bytes(content)


def _atomic_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if registry_tool.linklike(path):
        raise ValueError(f"atomic leader artifact must not be a link: {path}")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(8)}.tmp")
    descriptor: int | None = os.open(
        temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600
    )
    try:
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = None
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def _append_audit(path: Path, document: dict[str, Any]) -> None:
    if registry_tool.linklike(path):
        raise ValueError("Registry leader operation audit must not be a link")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(document, ensure_ascii=False,
                                separators=(",", ":")) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def validate_trust_policy(document: Any) -> None:
    fields = {"schemaVersion", "product", "policyId", "allowedSigners", "revokedKeys"}
    if (not isinstance(document, dict) or set(document) != fields
            or document.get("schemaVersion") != 1
            or document.get("product") != TRUST_PRODUCT
            or not package_tool.IDENTIFIER.fullmatch(str(document.get("policyId", "")))
            or not isinstance(document.get("allowedSigners"), list)
            or not document["allowedSigners"]
            or len(document["allowedSigners"]) > 64
            or not isinstance(document.get("revokedKeys"), list)
            or len(document["revokedKeys"]) > 64):
        raise ValueError("Registry leader trust policy is malformed")
    signer_fields = {
        "keyId", "algorithm", "publicKey", "publicKeySha256",
        "authorityIds", "registryIds", "notBefore", "notAfter",
    }
    key_ids: set[str] = set()
    for signer in document["allowedSigners"]:
        if (not isinstance(signer, dict) or set(signer) != signer_fields
                or not package_tool.IDENTIFIER.fullmatch(str(signer.get("keyId", "")))
                or signer["keyId"] in key_ids
                or signer.get("algorithm") != "Ed25519"
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
                       for name in ("authorityIds", "registryIds"))):
            raise ValueError("Registry leader trusted signer is malformed")
        before = package_tool.parse_time(signer["notBefore"], "leader signer notBefore")
        after = package_tool.parse_time(signer["notAfter"], "leader signer notAfter")
        if before >= after:
            raise ValueError("Registry leader signer validity is reversed")
        key_ids.add(signer["keyId"])
    revoked: set[str] = set()
    for item in document["revokedKeys"]:
        if (not isinstance(item, dict)
                or set(item) != {"keyId", "revokedAt", "reason"}
                or not package_tool.IDENTIFIER.fullmatch(str(item.get("keyId", "")))
                or item["keyId"] in revoked
                or not isinstance(item.get("reason"), str)
                or not 1 <= len(item["reason"]) <= 512):
            raise ValueError("Registry leader revoked signer is malformed")
        package_tool.parse_time(item["revokedAt"], "leader signer revokedAt")
        revoked.add(item["keyId"])


def load_trust_policy(path: str | Path, expected_id: str,
                      expected_sha: str) -> tuple[dict[str, Any], str, Path]:
    trust_path = package_tool.resolved_path(path, "Registry leader trust policy")
    document, _, actual_sha = _json_file(trust_path, "Registry leader trust policy")
    expected = str(expected_sha).lower()
    if (document.get("policyId") != expected_id
            or not package_tool.SHA256.fullmatch(expected)
            or actual_sha != expected):
        raise ValueError("Registry leader trust policy identity is not pinned")
    validate_trust_policy(document)
    return document, actual_sha, trust_path


def validate_grant(document: Any) -> None:
    fields = {
        "schemaVersion", "product", "authorityId", "registryId", "purpose",
        "leaderId", "fencingToken", "previousGrantSha256", "baselineRevision",
        "baselineStateSha256", "issuedAt", "notBefore", "expiresAt",
        "handoffEvidenceSha256", "trustPolicy", "signer",
    }
    if (not isinstance(document, dict) or set(document) != fields
            or document.get("schemaVersion") != 1
            or document.get("product") != GRANT_PRODUCT
            or any(not package_tool.IDENTIFIER.fullmatch(str(document.get(name, "")))
                   for name in ("authorityId", "registryId"))
            or document.get("purpose") not in {"leadership", "fence"}
            or (document["purpose"] == "leadership"
                and not package_tool.IDENTIFIER.fullmatch(
                    str(document.get("leaderId", ""))))
            or (document["purpose"] == "fence" and document.get("leaderId") is not None)
            or type(document.get("fencingToken")) is not int
            or not 1 <= document["fencingToken"] <= 2 ** 63 - 1
            or (document.get("previousGrantSha256") is not None
                and not package_tool.SHA256.fullmatch(
                    str(document["previousGrantSha256"])))
            or type(document.get("baselineRevision")) is not int
            or document["baselineRevision"] < 0
            or not package_tool.SHA256.fullmatch(
                str(document.get("baselineStateSha256", "")))
            or (document.get("handoffEvidenceSha256") is not None
                and not package_tool.SHA256.fullmatch(
                    str(document["handoffEvidenceSha256"])))):
        raise ValueError("Registry leader grant is malformed")
    trust = document.get("trustPolicy")
    signer = document.get("signer")
    if (not isinstance(trust, dict) or set(trust) != {"policyId", "policySha256"}
            or not package_tool.IDENTIFIER.fullmatch(str(trust.get("policyId", "")))
            or not package_tool.SHA256.fullmatch(str(trust.get("policySha256", "")))
            or not isinstance(signer, dict)
            or set(signer) != {"keyId", "algorithm", "signature"}
            or not package_tool.IDENTIFIER.fullmatch(str(signer.get("keyId", "")))
            or signer.get("algorithm") != "Ed25519"
            or not isinstance(signer.get("signature"), str)):
        raise ValueError("Registry leader grant signer or trust binding is malformed")
    try:
        signature = base64.b64decode(signer["signature"], validate=True)
    except (ValueError, TypeError) as error:
        raise ValueError("Registry leader grant signature encoding is invalid") from error
    if len(signature) != 64:
        raise ValueError("Registry leader grant signature length is invalid")
    issued = package_tool.parse_time(document["issuedAt"], "leader grant issuedAt")
    before = package_tool.parse_time(document["notBefore"], "leader grant notBefore")
    expires = package_tool.parse_time(document["expiresAt"], "leader grant expiresAt")
    if issued > before or before >= expires:
        raise ValueError("Registry leader grant validity window is malformed")
    if (expires - before).total_seconds() > MAX_GRANT_SECONDS:
        raise ValueError("Registry leader grant exceeds the maximum lease duration")
    if ((document["fencingToken"] == 1) !=
            (document["previousGrantSha256"] is None)):
        raise ValueError("Registry leader grant predecessor linkage is malformed")


def grant_payload(document: dict[str, Any]) -> dict[str, Any]:
    payload = dict(document)
    signer = dict(payload["signer"])
    signer.pop("signature", None)
    payload["signer"] = signer
    return payload


def verify_grant(document: dict[str, Any], trust: dict[str, Any],
                 trust_path: Path, at: Any, require_active: bool = True) \
        -> dict[str, str]:
    validate_grant(document)
    if document["trustPolicy"] != {
            "policyId": trust["policyId"],
            "policySha256": package_tool.sha256_file(trust_path),
    }:
        raise ValueError("Registry leader grant trust-policy binding changed")
    when = package_tool.verification_time(at)
    issued = package_tool.parse_time(document["issuedAt"], "leader grant issuedAt")
    before = package_tool.parse_time(document["notBefore"], "leader grant notBefore")
    expires = package_tool.parse_time(document["expiresAt"], "leader grant expiresAt")
    if require_active and not before <= when < expires:
        raise ValueError("Registry leader grant is not currently active")
    key_id = document["signer"]["keyId"]
    matches = [
        signer for signer in trust["allowedSigners"]
        if signer["keyId"] == key_id
        and document["authorityId"] in signer["authorityIds"]
        and document["registryId"] in signer["registryIds"]
    ]
    if len(matches) != 1:
        raise ValueError("Registry leader grant signer is not trusted for this scope")
    signer = matches[0]
    if (issued < package_tool.parse_time(signer["notBefore"], "leader signer notBefore")
            or issued >= package_tool.parse_time(
                signer["notAfter"], "leader signer notAfter")):
        raise ValueError("Registry leader grant is outside signer validity")
    for revoked in trust["revokedKeys"]:
        if (revoked["keyId"] == key_id
                and when >= package_tool.parse_time(
                    revoked["revokedAt"], "leader signer revokedAt")):
            raise ValueError("Registry leader grant signer is revoked")
    public_path = registry_tool.safe_member(
        trust_path.parent, signer["publicKey"], "Registry leader public key"
    )
    public_bytes = public_path.read_bytes()
    if package_tool.sha256_bytes(public_bytes) != signer["publicKeySha256"]:
        raise ValueError("Registry leader public key digest changed")
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        from cryptography.hazmat.primitives.serialization import load_pem_public_key
        key = load_pem_public_key(public_bytes)
        if not isinstance(key, Ed25519PublicKey):
            raise ValueError("Registry leader public key is not Ed25519")
        key.verify(
            base64.b64decode(document["signer"]["signature"], validate=True),
            package_tool.canonical_bytes(grant_payload(document)),
        )
    except ImportError as error:
        raise ValueError("Registry leader verification requires cryptography") from error
    except Exception as error:
        if isinstance(error, ValueError):
            raise
        raise ValueError("Registry leader Ed25519 verification failed") from error
    return {"keyId": key_id, "publicKeySha256": signer["publicKeySha256"]}


def current_grant_path(authority: Path) -> Path:
    return authority / "current-grant.json"


def grant_blob_path(authority: Path, token: int, digest: str) -> Path:
    return authority / "grants" / f"{token:020d}-{digest}.json"


def _load_current(authority: Path) -> tuple[dict[str, Any], bytes, str]:
    document, content, digest = _json_file(
        current_grant_path(authority), "Registry current leader grant"
    )
    validate_grant(document)
    blob = grant_blob_path(authority, document["fencingToken"], digest)
    if (not blob.is_file() or registry_tool.linklike(blob)
            or blob.read_bytes() != content):
        raise ValueError("Registry current leader grant lacks immutable authority evidence")
    return document, content, digest


class FileAuthorityBackend:
    def __init__(self, authority: str | Path, authority_id: str,
                 registry_id: str, create: bool = False) -> None:
        self.authority = _directory(authority, create=create)
        self.authority_id = authority_id
        self.registry_id = registry_id

    def current(self) -> tuple[dict[str, Any], bytes, str] | None:
        path = current_grant_path(self.authority)
        if not path.exists() and not path.is_symlink():
            return None
        return _load_current(self.authority)

    def grant(self, token: int, digest: str) \
            -> tuple[dict[str, Any], bytes, str]:
        document, content, actual = _json_file(
            grant_blob_path(self.authority, token, digest),
            f"Registry leader grant token {token}",
        )
        if actual != digest:
            raise ValueError("Registry leader grant history digest changed")
        return document, content, actual

    def compare_and_swap(self, expected_token: int, expected_sha256: str,
                         grant: dict[str, Any], content: bytes, digest: str) -> None:
        lease = process_lease.ProcessFileLease(
            self.authority / ".leader-authority.lock",
            self.authority / ".leader-authority.epoch.json",
            "team-contract-registry-leader-authority",
            {"authorityId": self.authority_id, "operation": "compare-and-swap"},
        )
        with lease:
            lease.assert_current()
            loaded = self.current()
            if expected_token == 0:
                if loaded is not None or expected_sha256 != ZERO_SHA256:
                    raise ValueError(
                        "Registry current leader grant changed before file CAS"
                    )
            elif (loaded is None
                  or loaded[0]["fencingToken"] != expected_token
                  or loaded[2] != expected_sha256):
                raise ValueError(
                    "Registry current leader grant changed before file CAS"
                )
            registry_tool.exclusive_bytes(
                grant_blob_path(
                    self.authority, grant["fencingToken"], digest
                ),
                content,
            )
            lease.assert_current()
            _atomic_bytes(current_grant_path(self.authority), content)

    def binding_descriptor(self) -> tuple[str, dict[str, Any] | None]:
        return str(current_grant_path(self.authority)), None


def _configured_backend(args: argparse.Namespace, *, create_file: bool = False) \
        -> FileAuthorityBackend | backend_tool.ExternalCommandBackend:
    authority = getattr(args, "authority", None)
    config = getattr(args, "authority_backend_config", None)
    config_sha = getattr(args, "expected_authority_backend_config_sha256", None)
    if bool(authority) == bool(config):
        raise ValueError(
            "exactly one Registry leader file authority or backend config is required"
        )
    if authority:
        if config_sha:
            raise ValueError(
                "backend config SHA is only valid with an external authority backend"
            )
        return FileAuthorityBackend(
            authority, args.authority_id, args.registry_id, create=create_file
        )
    if not config_sha:
        raise ValueError("external authority backend requires a pinned config SHA")
    backend = backend_tool.ExternalCommandBackend(
        config, config_sha, args.authority_id, args.registry_id
    )
    signing_environments = {
        value for value in (
            getattr(args, "private_key_environment", None),
            getattr(args, "private_key_passphrase_environment", None),
        ) if value
    }
    if signing_environments & set(backend.config["environmentVariables"]):
        raise ValueError(
            "Registry leader backend must not receive signing key environment"
        )
    return backend


def verify_history(backend: Any, current: dict[str, Any], current_sha: str,
                   trust: dict[str, Any], trust_path: Path) -> None:
    token = current["fencingToken"]
    document = current
    digest = current_sha
    while True:
        loaded, _, actual = backend.grant(token, digest)
        if actual != digest or loaded != document:
            raise ValueError("Registry leader grant history digest changed")
        verify_grant(loaded, trust, trust_path, loaded["issuedAt"], False)
        if token == 1:
            if loaded["previousGrantSha256"] is not None:
                raise ValueError("Registry leader grant history origin changed")
            return
        predecessor_sha = loaded["previousGrantSha256"]
        document, _, digest = backend.grant(token - 1, predecessor_sha)
        validate_grant(document)
        if (document["fencingToken"] != token - 1
                or document["authorityId"] != current["authorityId"]
                or document["registryId"] != current["registryId"]):
            raise ValueError("Registry leader grant history identity changed")
        token -= 1


def latest_leadership_grant(backend: Any, current: dict[str, Any]) \
        -> tuple[dict[str, Any], str] | None:
    document = current
    while True:
        if document["purpose"] == "leadership":
            content = package_tool.json_bytes(document)
            return document, package_tool.sha256_bytes(content)
        token = document["fencingToken"]
        predecessor_sha = document["previousGrantSha256"]
        if token == 1 or predecessor_sha is None:
            return None
        document, _, actual = backend.grant(token - 1, predecessor_sha)
        if actual != predecessor_sha:
            raise ValueError("Registry leader predecessor grant digest changed")
        validate_grant(document)


def _private_key(args: argparse.Namespace) -> Any:
    value = os.environ.get(args.private_key_environment)
    if not value:
        raise ValueError("Registry leader private key environment is unset")
    passphrase = None
    if args.private_key_passphrase_environment:
        supplied = os.environ.get(args.private_key_passphrase_environment)
        if supplied is None:
            raise ValueError("Registry leader private key passphrase is unset")
        passphrase = supplied.encode("utf-8")
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
        key = load_pem_private_key(Path(value).resolve().read_bytes(), password=passphrase)
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError("Registry leader private key is not Ed25519")
        return key
    except ImportError as error:
        raise ValueError("Registry leader signing requires cryptography") from error


def issue_command(args: argparse.Namespace) -> int:
    committed = False
    try:
        if any(not package_tool.IDENTIFIER.fullmatch(str(value)) for value in (
                args.authority_id, args.registry_id, args.operator, args.key_id)):
            raise ValueError("Registry leader issue identity is malformed")
        if (args.purpose == "leadership"
                and not package_tool.IDENTIFIER.fullmatch(str(args.leader_id or ""))):
            raise ValueError("leadership grant requires a valid leader id")
        if args.purpose == "fence" and args.leader_id is not None:
            raise ValueError("fence grant must not name a leader")
        if (args.expected_current_token < 0
                or not package_tool.SHA256.fullmatch(
                    str(args.expected_current_grant_sha256).lower())
                or args.baseline_revision < 0
                or not package_tool.SHA256.fullmatch(
                    str(args.baseline_state_sha256).lower())):
            raise ValueError("Registry leader issue baseline is malformed")
        backend = _configured_backend(args, create_file=True)
        trust, trust_sha, trust_path = load_trust_policy(
            args.leader_trust_policy, args.expected_leader_trust_policy_id,
            args.expected_leader_trust_policy_sha256,
        )
        current_loaded = backend.current()
        current: dict[str, Any] | None = None
        previous_sha: str | None = None
        handoff_sha: str | None = None
        expected_sha = str(args.expected_current_grant_sha256).lower()
        if args.expected_current_token == 0:
            if current_loaded is not None:
                raise ValueError("Registry leader authority is already initialized")
            if expected_sha != ZERO_SHA256:
                raise ValueError("initial leader grant requires the zero predecessor SHA")
            token = 1
        else:
            if current_loaded is None:
                raise ValueError("Registry current leader grant is unavailable")
            current, _, previous_sha = current_loaded
            validate_grant(current)
            if (current["fencingToken"] != args.expected_current_token
                    or previous_sha != expected_sha):
                raise ValueError("Registry current leader grant changed before issue")
            if (current["authorityId"] != args.authority_id
                    or current["registryId"] != args.registry_id):
                raise ValueError("Registry leader authority identity changed")
            verify_history(backend, current, previous_sha, trust, trust_path)
            if (args.purpose == "leadership"
                    and current["purpose"] == "leadership"
                    and current["leaderId"] != args.leader_id):
                raise ValueError(
                    "leadership transfer requires an intervening fence grant"
                )
            if args.purpose == "leadership":
                previous_leader = latest_leadership_grant(backend, current)
                transfer = previous_leader is not None \
                    and previous_leader[0]["leaderId"] != args.leader_id
                handoff_values = (
                    args.handoff_evidence, args.handoff_trust_policy,
                    args.expected_handoff_trust_policy_id,
                    args.expected_handoff_trust_policy_sha256,
                )
                if transfer:
                    if not all(handoff_values):
                        raise ValueError(
                            "cross-node leadership transfer requires signed "
                            "handoff evidence"
                        )
                    import team_contract_registry_handoff as handoff_tool
                    evidence, handoff_sha = handoff_tool.load_and_verify_evidence(
                        args.handoff_evidence, args.handoff_trust_policy,
                        args.expected_handoff_trust_policy_id,
                        args.expected_handoff_trust_policy_sha256,
                        args.handoff_verification_time,
                    )
                    if (evidence["registryId"] != args.registry_id
                            or evidence["nodeId"] != previous_leader[0]["leaderId"]
                            or evidence["registryRevision"]
                                != args.baseline_revision
                            or evidence["registryStateSha256"]
                                != str(args.baseline_state_sha256).lower()
                            or evidence["observedFencingToken"]
                                != current["fencingToken"]
                            or evidence["observedGrantSha256"] != previous_sha):
                        raise ValueError(
                            "handoff evidence does not bind the fenced old "
                            "leader and candidate baseline"
                        )
                elif any(handoff_values):
                    raise ValueError(
                        "handoff evidence is only valid for a cross-node transfer"
                    )
            token = current["fencingToken"] + 1
        grant = {
            "schemaVersion": 1, "product": GRANT_PRODUCT,
            "authorityId": args.authority_id, "registryId": args.registry_id,
            "purpose": args.purpose,
            "leaderId": args.leader_id if args.purpose == "leadership" else None,
            "fencingToken": token, "previousGrantSha256": previous_sha,
            "baselineRevision": args.baseline_revision,
            "baselineStateSha256": str(args.baseline_state_sha256).lower(),
            "handoffEvidenceSha256": handoff_sha,
            "issuedAt": registry_tool.utc_time(args.issued_at),
            "notBefore": registry_tool.utc_time(args.not_before),
            "expiresAt": registry_tool.utc_time(args.expires_at),
            "trustPolicy": {
                "policyId": trust["policyId"], "policySha256": trust_sha,
            },
            "signer": {"keyId": args.key_id, "algorithm": "Ed25519"},
        }
        key = _private_key(args)
        grant["signer"]["signature"] = base64.b64encode(
            key.sign(package_tool.canonical_bytes(grant))
        ).decode("ascii")
        validate_grant(grant)
        verify_grant(grant, trust, trust_path, grant["notBefore"], True)
        content = package_tool.json_bytes(grant)
        digest = package_tool.sha256_bytes(content)
        backend.compare_and_swap(
            args.expected_current_token, expected_sha, grant, content, digest
        )
        committed = True
        report = {
            "schemaVersion": 1, "product": REPORT_PRODUCT, "passed": True,
            "operation": "issue", "authorityId": args.authority_id,
            "registryId": args.registry_id, "leaderId": grant["leaderId"],
            "purpose": grant["purpose"], "fencingToken": token,
            "grantSha256": digest, "registry": None,
            "completedAt": registry_tool.utc_time(None), "operator": args.operator,
        }
        if args.operation_audit:
            _append_audit(Path(args.operation_audit).resolve(), report)
        if args.report:
            package_tool.write_json(Path(args.report).resolve(), report)
        print("PDR_TEAM_CONTRACT_REGISTRY_LEADER_ISSUE_PASS "
              f"purpose={grant['purpose']} token={token} sha256={digest}")
        return 0
    except backend_tool.BackendCommitUncertainError as error:
        print(
            f"PDR_TEAM_CONTRACT_REGISTRY_LEADER_COMMITTED_ERROR: {error}",
            file=sys.stderr,
        )
        return 3
    except (OSError, UnicodeError, ValueError, RuntimeError,
            json.JSONDecodeError) as error:
        marker = "COMMITTED_ERROR" if committed else "ERROR"
        print(f"PDR_TEAM_CONTRACT_REGISTRY_LEADER_{marker}: {error}", file=sys.stderr)
        return 3 if committed else 2


def binding_path(root: Path) -> Path:
    return registry_tool.safe_member(root, ".pdr-leader.json", "Registry leader binding")


def validate_binding(document: Any, registry_id: str | None = None) -> None:
    base_fields = {
        "schemaVersion", "product", "authorityId", "registryId", "leaderId",
        "fencingToken", "grantPath", "grantSha256", "trustPolicyPath",
        "trustPolicyId", "trustPolicySha256", "promotedFromStandbyMarkerSha256",
        "boundAt",
    }
    if not isinstance(document, dict):
        raise ValueError("Registry leader binding is malformed")
    version = document.get("schemaVersion")
    backend_fields = {"authorityBackend"}
    migration_fields = {
        "backendMigrationEvidencePath", "backendMigrationEvidenceSha256",
    }
    expected_fields = base_fields if version == 1 else base_fields | backend_fields
    if version == 3:
        expected_fields |= migration_fields
    if (version not in {1, 2, 3} or set(document) != expected_fields
            or document.get("product") != BINDING_PRODUCT
            or any(not package_tool.IDENTIFIER.fullmatch(str(document.get(name, "")))
                   for name in ("authorityId", "registryId", "leaderId",
                                "trustPolicyId"))
            or (registry_id is not None and document["registryId"] != registry_id)
            or type(document.get("fencingToken")) is not int
            or document["fencingToken"] < 1
            or not isinstance(document.get("trustPolicyPath"), str)
            or not document["trustPolicyPath"]
            or any(not package_tool.SHA256.fullmatch(str(document.get(name, "")))
                   for name in ("grantSha256", "trustPolicySha256"))
            or (document.get("promotedFromStandbyMarkerSha256") is not None
                and not package_tool.SHA256.fullmatch(
                    str(document["promotedFromStandbyMarkerSha256"])) )):
        raise ValueError("Registry leader binding is malformed")
    if version == 1:
        if not isinstance(document.get("grantPath"), str) or not document["grantPath"]:
            raise ValueError("Registry leader file binding is malformed")
    else:
        backend = document.get("authorityBackend")
        if (document.get("grantPath") is not None
                or not isinstance(backend, dict)
                or set(backend) != {
                    "kind", "backendId", "configPath", "configSha256"
                }
                or backend.get("kind") != "external-command"
                or not package_tool.IDENTIFIER.fullmatch(
                    str(backend.get("backendId", "")))
                or not isinstance(backend.get("configPath"), str)
                or not backend["configPath"]
                or not package_tool.SHA256.fullmatch(
                    str(backend.get("configSha256", "")))):
            raise ValueError("Registry leader backend binding is malformed")
        if version == 3 and (
                not isinstance(document.get("backendMigrationEvidencePath"), str)
                or not document["backendMigrationEvidencePath"]
                or not package_tool.SHA256.fullmatch(
                    str(document.get("backendMigrationEvidenceSha256", "")))):
            raise ValueError("Registry leader backend migration binding is malformed")
    package_tool.parse_time(document.get("boundAt"), "leader binding boundAt")


def read_binding(root: Path, registry_id: str | None = None) \
        -> tuple[dict[str, Any], str] | None:
    path = binding_path(root)
    if not path.exists():
        return None
    document, _, digest = _json_file(path, "Registry leader binding")
    validate_binding(document, registry_id)
    return document, digest


def _binding_current_grant(root: Path, binding: dict[str, Any]) \
        -> tuple[dict[str, Any], bytes, str]:
    if binding["schemaVersion"] == 1:
        grant_path = Path(binding["grantPath"]).resolve()
        _outside(grant_path, root, "Registry current leader grant")
        return _json_file(grant_path, "Registry current leader grant")
    descriptor = binding["authorityBackend"]
    config_path = Path(descriptor["configPath"]).resolve()
    _outside(config_path, root, "Registry leader backend config")
    backend = backend_tool.ExternalCommandBackend(
        config_path, descriptor["configSha256"], binding["authorityId"],
        binding["registryId"],
    )
    if backend.backend_id != descriptor["backendId"]:
        raise ValueError("Registry leader backend identity changed")
    loaded = backend.current()
    if loaded is None:
        raise ValueError("Registry current leader grant is unavailable")
    return loaded


def fencing_state_path(root: Path) -> Path:
    return registry_tool.safe_member(
        root, ".pdr-fencing.json", "Registry fencing high-water state"
    )


def validate_fencing_state(document: Any, binding: dict[str, Any]) -> None:
    fields = {
        "schemaVersion", "product", "authorityId", "registryId",
        "highestObservedFencingToken", "grantSha256", "observedAt",
    }
    if (not isinstance(document, dict) or set(document) != fields
            or document.get("schemaVersion") != 1
            or document.get("product") != FENCING_STATE_PRODUCT
            or document.get("authorityId") != binding["authorityId"]
            or document.get("registryId") != binding["registryId"]
            or type(document.get("highestObservedFencingToken")) is not int
            or document["highestObservedFencingToken"] < 1
            or not package_tool.SHA256.fullmatch(
                str(document.get("grantSha256", "")))):
        raise ValueError("Registry fencing high-water state is malformed")
    package_tool.parse_time(document.get("observedAt"), "fencing state observedAt")


def _fencing_high_water(root: Path, binding: dict[str, Any]) \
        -> tuple[int, dict[str, Any] | None]:
    path = fencing_state_path(root)
    if not path.exists():
        return binding["fencingToken"], None
    document, _, _ = _json_file(path, "Registry fencing high-water state")
    validate_fencing_state(document, binding)
    return max(binding["fencingToken"], document["highestObservedFencingToken"]), document


def _observe_fencing_token(root: Path, binding: dict[str, Any],
                           grant: dict[str, Any], grant_sha: str) -> int:
    token = grant["fencingToken"]
    highest, existing = _fencing_high_water(root, binding)
    if token < highest:
        raise ValueError("Registry leader authority rollback detected; write denied")
    observed = existing["highestObservedFencingToken"] if existing else 0
    if token <= observed:
        return token
    lease = process_lease.ProcessFileLease(
        root / ".pdr-fencing.lock", root / ".pdr-fencing.epoch.json",
        "team-contract-registry-fencing-observer",
        {"authorityId": binding["authorityId"], "registryId": binding["registryId"]},
    )
    with lease:
        lease.assert_current()
        highest, existing = _fencing_high_water(root, binding)
        if token < highest:
            raise ValueError("Registry leader authority rollback detected; write denied")
        observed = existing["highestObservedFencingToken"] if existing else 0
        if token <= observed:
            return token
        document = {
            "schemaVersion": 1, "product": FENCING_STATE_PRODUCT,
            "authorityId": binding["authorityId"],
            "registryId": binding["registryId"],
            "highestObservedFencingToken": token,
            "grantSha256": grant_sha,
            "observedAt": registry_tool.utc_time(None),
        }
        _atomic_bytes(fencing_state_path(root), package_tool.json_bytes(document))
    return token


def verify_registry_write_authority(root: Path, at: Any = None) \
        -> tuple[dict[str, Any], dict[str, Any], str]:
    loaded = read_binding(root)
    if loaded is None:
        raise ValueError("Registry is not bound to an external leader authority")
    binding, _ = loaded
    trust_path = Path(binding["trustPolicyPath"]).resolve()
    _outside(trust_path, root, "Registry leader trust policy")
    grant, _, grant_sha = _binding_current_grant(root, binding)
    trust, trust_sha, pinned_path = load_trust_policy(
        trust_path, binding["trustPolicyId"], binding["trustPolicySha256"]
    )
    verify_grant(grant, trust, pinned_path, at, False)
    if (trust_sha != binding["trustPolicySha256"]
            or grant["authorityId"] != binding["authorityId"]
            or grant["registryId"] != binding["registryId"]):
        raise ValueError("Registry leader authority identity changed; write denied")
    _observe_fencing_token(root, binding, grant, grant_sha)
    if grant_sha != binding["grantSha256"]:
        raise ValueError("Registry leader fencing token is stale; write denied")
    verify_grant(grant, trust, pinned_path, at, True)
    if (grant["purpose"] != "leadership"
            or grant["leaderId"] != binding["leaderId"]
            or grant["fencingToken"] != binding["fencingToken"]):
        raise ValueError("Registry leader binding is fenced; write denied")
    return binding, grant, grant_sha


def verify_registry_fenced(root: Path, at: Any = None) \
        -> tuple[dict[str, Any], dict[str, Any], str]:
    loaded = read_binding(root)
    if loaded is None:
        raise ValueError("Registry is not enrolled with a leader authority")
    binding, _ = loaded
    trust_path = Path(binding["trustPolicyPath"]).resolve()
    _outside(trust_path, root, "Registry leader trust policy")
    grant, _, grant_sha = _binding_current_grant(root, binding)
    trust, _, pinned_path = load_trust_policy(
        trust_path, binding["trustPolicyId"], binding["trustPolicySha256"]
    )
    verify_grant(grant, trust, pinned_path, at, True)
    if (grant["authorityId"] != binding["authorityId"]
            or grant["registryId"] != binding["registryId"]
            or grant["purpose"] != "fence"
            or grant["leaderId"] is not None
            or grant["fencingToken"] <= binding["fencingToken"]):
        raise ValueError("Registry does not observe a newer active fence grant")
    _observe_fencing_token(root, binding, grant, grant_sha)
    return binding, grant, grant_sha


def _activation_report(operation: str, root: Path, binding: dict[str, Any],
                       grant_sha: str, operator: str) -> dict[str, Any]:
    return {
        "schemaVersion": 1, "product": REPORT_PRODUCT, "passed": True,
        "operation": operation, "authorityId": binding["authorityId"],
        "registryId": binding["registryId"], "leaderId": binding["leaderId"],
        "purpose": "leadership", "fencingToken": binding["fencingToken"],
        "grantSha256": grant_sha, "registry": str(root),
        "backendMigrationEvidenceSha256":
            binding.get("backendMigrationEvidenceSha256"),
        "completedAt": registry_tool.utc_time(None), "operator": operator,
    }


def _verify_backend_migration(
        root: Path, evidence_path_value: str, expected_evidence_sha: str,
        old_binding: dict[str, Any], target_descriptor: dict[str, Any],
        target_grant: dict[str, Any], target_grant_sha: str,
        pointer: dict[str, Any], state: dict[str, Any], at: Any,
        args: argparse.Namespace) \
        -> tuple[Path, str]:
    import team_contract_registry_leader_backend_migration as migration_tool

    evidence, evidence_path, evidence_sha = migration_tool.load_migration(
        evidence_path_value, expected_evidence_sha
    )
    _outside(evidence_path, root, "Registry leader backend migration evidence")
    source = migration_tool._backend_from_descriptor(
        evidence["sourceBackend"], evidence["authorityId"],
        evidence["registryId"], args, "migration source backend",
    )
    target = migration_tool._backend_from_descriptor(
        evidence["targetBackend"], evidence["authorityId"],
        evidence["registryId"], args, "migration target backend",
    )
    if (old_binding.get("authorityBackend") != source.descriptor()
            or target_descriptor != target.descriptor()
            or evidence["authorityId"] != old_binding["authorityId"]
            or evidence["registryId"] != state["registryId"]
            or evidence["targetLeadershipGrantSha256"] != target_grant_sha
            or evidence["targetLeadershipToken"]
                != target_grant["fencingToken"]
            or evidence["leaderId"] != target_grant["leaderId"]
            or evidence["baselineRevision"] != pointer["revision"]
            or evidence["baselineStateSha256"] != pointer["stateSha256"]):
        raise ValueError("Registry leader backend migration evidence does not bind activation")
    if evidence["schemaVersion"] == 1:
        sync, _, _ = migration_tool.load_sync(
            evidence["syncEvidencePath"], evidence["syncEvidenceSha256"]
        )
    else:
        reference = evidence["syncEvidenceRef"]
        artifact_store = migration_tool._artifact_store(
            args, evidence["migrationId"], reference["storeId"]
        )
        if artifact_store is None:
            raise ValueError("Registry leader migration Artifact Store is unavailable")
        sync, _ = migration_tool._sync_bytes(
            artifact_store.get(reference), reference["sha256"]
        )
    if (sync["migrationId"] != evidence["migrationId"]
            or sync["sourceBackend"] != evidence["sourceBackend"]
            or sync["targetBackend"] != evidence["targetBackend"]
            or sync["synchronizedThroughToken"]
                != evidence["sourceFenceToken"]
            or sync["synchronizedGrantSha256"]
                != evidence["sourceFenceGrantSha256"]
            or sync["grantChainSha256"] != evidence["grantChainSha256"]):
        raise ValueError("Registry leader backend migration sync evidence changed")
    source_current = source.current()
    if source_current is None:
        raise ValueError("Registry leader migration source fence disappeared")
    source_fence, _, source_sha = source_current
    trust_path = Path(old_binding["trustPolicyPath"]).resolve()
    trust, _, pinned_trust = load_trust_policy(
        trust_path, old_binding["trustPolicyId"],
        old_binding["trustPolicySha256"],
    )
    verify_grant(source_fence, trust, pinned_trust, at, True)
    if (source_sha != evidence["sourceFenceGrantSha256"]
            or source_fence["fencingToken"] != evidence["sourceFenceToken"]
            or source_fence["purpose"] != "fence"
            or source_fence["leaderId"] is not None
            or target_grant["previousGrantSha256"] != source_sha
            or target_grant["fencingToken"] != source_fence["fencingToken"] + 1):
        raise ValueError("Registry leader migration source fence or target chain changed")
    return evidence_path, evidence_sha


def activate_command(args: argparse.Namespace) -> int:
    committed = False
    try:
        if (not package_tool.IDENTIFIER.fullmatch(str(args.node_id))
                or not package_tool.IDENTIFIER.fullmatch(str(args.operator))
                or not package_tool.SHA256.fullmatch(
                    str(args.expected_current_grant_sha256).lower())):
            raise ValueError("Registry leader activation identity is malformed")
        root = registry_tool.registry_root(args.registry)
        supplied_grant = getattr(args, "current_grant", None)
        supplied_backend = getattr(args, "authority_backend_config", None)
        if bool(supplied_grant) == bool(supplied_backend):
            raise ValueError(
                "activation requires exactly one current grant path or backend config"
            )
        trust, trust_sha, trust_path = load_trust_policy(
            args.leader_trust_policy, args.expected_leader_trust_policy_id,
            args.expected_leader_trust_policy_sha256,
        )
        _outside(trust_path, root, "Registry leader trust policy")
        audit = Path(args.operation_audit).resolve()
        _outside(audit, root, "Registry leader operation audit")
        pointer, state = registry_tool.verified_current(root, args)
        grant_path: Path | None = None
        authority_backend: backend_tool.ExternalCommandBackend | None = None
        backend_descriptor: dict[str, Any] | None = None
        if supplied_grant:
            grant_path = package_tool.resolved_path(
                supplied_grant, "Registry current leader grant"
            )
            _outside(grant_path, root, "Registry current leader grant")
            grant, _, grant_sha = _json_file(
                grant_path, "Registry current leader grant"
            )
        else:
            authority_id = getattr(args, "authority_id", None)
            config_sha = getattr(
                args, "expected_authority_backend_config_sha256", None
            )
            if (not package_tool.IDENTIFIER.fullmatch(str(authority_id or ""))
                    or not config_sha):
                raise ValueError(
                    "backend activation requires authority id and pinned config SHA"
                )
            config_path = package_tool.resolved_path(
                supplied_backend, "Registry leader backend config"
            )
            _outside(config_path, root, "Registry leader backend config")
            authority_backend = backend_tool.ExternalCommandBackend(
                config_path, config_sha, authority_id, state["registryId"]
            )
            loaded_grant = authority_backend.current()
            if loaded_grant is None:
                raise ValueError("Registry current leader grant is unavailable")
            grant, _, grant_sha = loaded_grant
            backend_descriptor = authority_backend.descriptor()
        if grant_sha != str(args.expected_current_grant_sha256).lower():
            raise ValueError("Registry current leader grant digest changed")
        verify_grant(grant, trust, trust_path, args.leader_verification_time, True)
        if grant["purpose"] != "leadership" or grant["leaderId"] != args.node_id:
            raise ValueError("Registry current grant does not authorize this node")
        if (grant["registryId"] != state["registryId"]
                or grant["baselineRevision"] != pointer["revision"]
                or grant["baselineStateSha256"] != pointer["stateSha256"]):
            raise ValueError("Registry leader grant baseline does not match local state")
        standby = registry_tool.read_standby_marker(root, state["registryId"])
        existing = read_binding(root, state["registryId"])
        operation: str
        promoted_sha: str | None = None
        migration_evidence_path: Path | None = None
        migration_evidence_sha: str | None = None
        migration_evidence_value = getattr(
            args, "backend_migration_evidence", None
        )
        expected_migration_sha = getattr(
            args, "expected_backend_migration_evidence_sha256", None
        )
        if bool(migration_evidence_value) != bool(expected_migration_sha):
            raise ValueError(
                "backend migration activation requires evidence and pinned SHA"
            )
        if standby is not None:
            if standby[0]["standbyId"] != args.node_id:
                raise ValueError("Registry standby identity does not match leader grant")
            operation = "promote"
            promoted_sha = standby[1]
        elif existing is not None:
            old = existing[0]
            if (old["authorityId"] != grant["authorityId"]
                    or old["leaderId"] != args.node_id
                    or grant["fencingToken"] <= old["fencingToken"]):
                raise ValueError("Registry leader renewal is not a newer same-node grant")
            old_backend = old.get("authorityBackend")
            if old_backend != backend_descriptor:
                if (not migration_evidence_value or backend_descriptor is None
                        or old_backend is None):
                    raise ValueError(
                        "Registry leader renewal cannot change the authority backend"
                    )
                migration_evidence_path, migration_evidence_sha = \
                    _verify_backend_migration(
                        root, migration_evidence_value, expected_migration_sha,
                        old, backend_descriptor, grant, grant_sha,
                        pointer, state, args.leader_verification_time,
                        args,
                    )
                operation = "migrate"
            else:
                if migration_evidence_value:
                    raise ValueError(
                        "backend migration evidence cannot authorize a renewal"
                    )
                operation = "renew"
            if old["schemaVersion"] == 3 and operation == "renew":
                migration_evidence_path = Path(
                    old["backendMigrationEvidencePath"]
                ).resolve()
                migration_evidence_sha = old[
                    "backendMigrationEvidenceSha256"
                ]
            promoted_sha = old["promotedFromStandbyMarkerSha256"]
        else:
            if (not args.confirm_enroll_primary or grant["fencingToken"] != 1
                    or grant["previousGrantSha256"] is not None):
                raise ValueError(
                    "unmanaged primary enrollment requires token 1 and "
                    "--confirm-enroll-primary"
                )
            operation = "enroll"
        if migration_evidence_value and operation != "migrate":
            raise ValueError(
                "backend migration evidence is only valid for backend cutover"
            )
        binding_version = 1
        if backend_descriptor is not None:
            binding_version = 3 if migration_evidence_path is not None else 2
        binding = {
            "schemaVersion": binding_version,
            "product": BINDING_PRODUCT,
            "authorityId": grant["authorityId"], "registryId": grant["registryId"],
            "leaderId": grant["leaderId"], "fencingToken": grant["fencingToken"],
            "grantPath": str(grant_path) if grant_path is not None else None,
            "grantSha256": grant_sha,
            "trustPolicyPath": str(trust_path),
            "trustPolicyId": trust["policyId"], "trustPolicySha256": trust_sha,
            "promotedFromStandbyMarkerSha256": promoted_sha,
            "boundAt": registry_tool.utc_time(args.bound_at),
        }
        if backend_descriptor is not None:
            binding["authorityBackend"] = backend_descriptor
        if migration_evidence_path is not None:
            binding["backendMigrationEvidencePath"] = str(
                migration_evidence_path
            )
            binding["backendMigrationEvidenceSha256"] = migration_evidence_sha
        validate_binding(binding, state["registryId"])
        with registry_tool.RegistryLease(root, f"leader-{operation}", args.operator) as lease:
            lease.assert_current()
            final_pointer, final_state = registry_tool.verified_current(root, args)
            if (final_pointer != pointer or final_state != state):
                raise ValueError("Registry state changed during leader activation")
            if operation == "migrate":
                final_existing = read_binding(root, state["registryId"])
                if final_existing != existing:
                    raise ValueError(
                        "Registry leader binding changed during backend migration"
                    )
                _verify_backend_migration(
                    root, str(migration_evidence_path),
                    str(migration_evidence_sha), existing[0],
                    backend_descriptor, grant, grant_sha,
                    final_pointer, final_state,
                    args.leader_verification_time,
                    args,
                )
            if authority_backend is None:
                if grant_path is None:
                    raise ValueError("Registry current leader grant path disappeared")
                final_grant, _, final_sha = _json_file(
                    grant_path, "Registry current leader grant"
                )
            else:
                final_loaded = authority_backend.current()
                if final_loaded is None:
                    raise ValueError("Registry current leader grant disappeared")
                final_grant, _, final_sha = final_loaded
            if final_sha != grant_sha or final_grant != grant:
                raise ValueError("Registry current leader grant changed during activation")
            verify_grant(
                final_grant, trust, trust_path, args.leader_verification_time, True
            )
            _atomic_bytes(binding_path(root), package_tool.json_bytes(binding))
            if standby is not None:
                registry_tool.standby_marker_path(root).unlink()
            lease.assert_current()
            verify_registry_write_authority(root, args.leader_verification_time)
        report = _activation_report(operation, root, binding, grant_sha, args.operator)
        _append_audit(audit, report)
        committed = True
        if args.report:
            package_tool.write_json(Path(args.report).resolve(), report)
        print("PDR_TEAM_CONTRACT_REGISTRY_LEADER_ACTIVATE_PASS "
              f"operation={operation} token={grant['fencingToken']} node={args.node_id}")
        return 0
    except (OSError, UnicodeError, ValueError, RuntimeError,
            json.JSONDecodeError) as error:
        marker = "COMMITTED_ERROR" if committed else "ERROR"
        print(f"PDR_TEAM_CONTRACT_REGISTRY_LEADER_{marker}: {error}", file=sys.stderr)
        return 3 if committed else 2


def status_command(args: argparse.Namespace) -> int:
    try:
        root = registry_tool.registry_root(args.registry)
        binding, grant, grant_sha = verify_registry_write_authority(
            root, args.verification_time
        )
        pointer, state = registry_tool.read_current(root)[:2]
        if state["registryId"] != binding["registryId"]:
            raise ValueError("Registry leader status identity changed")
        report = {
            "schemaVersion": 1, "product": STATUS_PRODUCT, "passed": True,
            "mode": "leader-writable", "writable": True,
            "authorityId": binding["authorityId"],
            "registryId": binding["registryId"], "leaderId": binding["leaderId"],
            "fencingToken": binding["fencingToken"], "grantSha256": grant_sha,
            "revision": pointer["revision"], "stateSha256": pointer["stateSha256"],
            "expiresAt": grant["expiresAt"],
            "verifiedAt": registry_tool.utc_time(args.verification_time),
        }
        if args.report:
            package_tool.write_json(Path(args.report).resolve(), report)
        print("PDR_TEAM_CONTRACT_REGISTRY_LEADER_STATUS_PASS "
              f"token={binding['fencingToken']} revision={pointer['revision']}")
        return 0
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        print(f"PDR_TEAM_CONTRACT_REGISTRY_LEADER_STATUS_ERROR: {error}", file=sys.stderr)
        return 2


def _leader_trust(command: argparse.ArgumentParser) -> None:
    command.add_argument("--leader-trust-policy", required=True)
    command.add_argument("--expected-leader-trust-policy-id", required=True)
    command.add_argument("--expected-leader-trust-policy-sha256", required=True)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    issue = commands.add_parser("issue", help="atomically issue the next signed grant")
    issue_backend = issue.add_mutually_exclusive_group(required=True)
    issue_backend.add_argument("--authority")
    issue_backend.add_argument("--authority-backend-config")
    issue.add_argument("--expected-authority-backend-config-sha256")
    issue.add_argument("--authority-id", required=True)
    issue.add_argument("--registry-id", required=True)
    issue.add_argument("--purpose", choices=("leadership", "fence"), required=True)
    issue.add_argument("--leader-id")
    issue.add_argument("--expected-current-token", type=int, required=True)
    issue.add_argument("--expected-current-grant-sha256", required=True)
    issue.add_argument("--baseline-revision", type=int, required=True)
    issue.add_argument("--baseline-state-sha256", required=True)
    issue.add_argument("--issued-at")
    issue.add_argument("--not-before", required=True)
    issue.add_argument("--expires-at", required=True)
    issue.add_argument("--key-id", required=True)
    issue.add_argument("--private-key-environment", required=True)
    issue.add_argument("--private-key-passphrase-environment")
    issue.add_argument("--operator", required=True)
    issue.add_argument("--operation-audit")
    issue.add_argument("--report")
    issue.add_argument("--handoff-evidence")
    issue.add_argument("--handoff-trust-policy")
    issue.add_argument("--expected-handoff-trust-policy-id")
    issue.add_argument("--expected-handoff-trust-policy-sha256")
    issue.add_argument("--handoff-verification-time")
    _leader_trust(issue)
    issue.set_defaults(handler=issue_command)
    activate = commands.add_parser(
        "activate", help="bind an exact current grant to a primary or standby"
    )
    activate.add_argument("--registry", required=True)
    activate.add_argument("--node-id", required=True)
    activate_source = activate.add_mutually_exclusive_group(required=True)
    activate_source.add_argument("--current-grant")
    activate_source.add_argument("--authority-backend-config")
    activate.add_argument("--authority-id")
    activate.add_argument("--expected-authority-backend-config-sha256")
    activate.add_argument("--expected-current-grant-sha256", required=True)
    activate.add_argument("--operator", required=True)
    activate.add_argument("--operation-audit", required=True)
    activate.add_argument("--confirm-enroll-primary", action="store_true")
    activate.add_argument("--backend-migration-evidence")
    activate.add_argument("--expected-backend-migration-evidence-sha256")
    activate.add_argument("--artifact-store-config")
    activate.add_argument("--expected-artifact-store-config-sha256")
    activate.add_argument("--backend-config-resolver-config")
    activate.add_argument(
        "--expected-backend-config-resolver-config-sha256"
    )
    activate.add_argument("--bound-at")
    activate.add_argument("--report")
    activate.add_argument("--trust-policy", required=True)
    activate.add_argument("--expected-trust-policy-id", required=True)
    activate.add_argument("--expected-trust-policy-sha256", required=True)
    activate.add_argument("--verification-time")
    activate.add_argument("--leader-verification-time")
    activate.add_argument("--maximum-files", type=int,
                          default=package_tool.MAX_FILES_DEFAULT)
    activate.add_argument("--maximum-expanded-bytes", type=int,
                          default=package_tool.MAX_EXPANDED_BYTES_DEFAULT)
    _leader_trust(activate)
    activate.set_defaults(handler=activate_command)
    status = commands.add_parser("status", help="verify the current writable leader")
    status.add_argument("--registry", required=True)
    status.add_argument("--verification-time")
    status.add_argument("--report")
    status.set_defaults(handler=status_command)
    return result


def main() -> int:
    args = parser().parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
