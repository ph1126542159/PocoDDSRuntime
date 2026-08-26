#!/usr/bin/env python3
"""Publish and promote immutable signed team-contract packages through channels."""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any

import team_contract_package as package_tool
import process_file_lease as process_lease


POINTER_PRODUCT = "PocoDDSRuntimeTeamContractRegistryPointer"
STATE_PRODUCT = "PocoDDSRuntimeTeamContractRegistryState"
OPERATION_PRODUCT = "PocoDDSRuntimeTeamContractRegistryOperation"
RESOLUTION_PRODUCT = "PocoDDSRuntimeTeamContractRegistryResolution"
STANDBY_PRODUCT = "PocoDDSRuntimeTeamContractRegistryStandby"
IMPACT_GATE_PRODUCT = "PocoDDSRuntimeTeamContractImpactGate"
MAX_PACKAGES = 100000
MAX_LOCKS = 100000
MAX_CHANNELS = 16


def utc_time(value: str | None) -> str:
    return package_tool.verification_time(value).isoformat()


def linklike(path: Path) -> bool:
    return path.is_symlink() or bool(getattr(path, "is_junction", lambda: False)())


def registry_root(value: str | Path, create: bool = False) -> Path:
    supplied = Path(value)
    if linklike(supplied):
        raise ValueError(f"team contract Registry must not be a link: {supplied}")
    root = supplied.resolve()
    if create:
        root.mkdir(parents=True, exist_ok=True)
    if not root.is_dir() or linklike(root):
        raise FileNotFoundError(f"team contract Registry is unavailable: {root}")
    return root


def safe_member(root: Path, relative: str, label: str) -> Path:
    parts = package_tool.safe_archive_path(relative).parts
    raw = root.joinpath(*parts)
    current = root
    for part in parts:
        current = current / part
        if linklike(current):
            raise ValueError(f"{label} path contains a link or junction: {current}")
    resolved = raw.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as error:
        raise ValueError(f"{label} escapes the Registry root: {raw}") from error
    return resolved


def exclusive_bytes(path: Path, content: bytes) -> None:
    if linklike(path):
        raise ValueError(f"immutable Registry artifact must not be a link: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        if path.is_file() and not path.is_symlink() and path.read_bytes() == content:
            return
        raise ValueError(f"immutable Registry artifact already differs: {path}")
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(descriptor)


class RegistryLease(process_lease.ProcessFileLease):
    def __init__(self, root: Path, operation: str, actor: str) -> None:
        super().__init__(
            root / ".registry-write.lock",
            root / ".registry-write.epoch.json",
            "team-contract-registry-writer",
            {"operation": operation, "actor": actor},
        )

    def acquire(self) -> "RegistryLease":
        try:
            super().acquire()
            return self
        except process_lease.LeaseBusyError as error:
            raise ValueError(
                "team contract Registry is already being modified; inspect the writer lease"
            ) from error


def trust_identity(args: argparse.Namespace) -> dict[str, str]:
    if (not args.trust_policy or not args.expected_trust_policy_id
            or not args.expected_trust_policy_sha256):
        raise ValueError("Registry operations require a pinned team contract trust policy")
    policy_path = package_tool.resolved_path(
        args.trust_policy, "team contract Registry trust policy"
    )
    _, actual_sha = package_tool.load_trust_policy(
        policy_path, args.expected_trust_policy_id,
        args.expected_trust_policy_sha256,
    )
    return {
        "policyId": args.expected_trust_policy_id,
        "policySha256": actual_sha,
    }


def empty_channel(name: str) -> dict[str, Any]:
    return {
        "name": name,
        "generation": 0,
        "lockSha256": None,
        "updatedAt": None,
        "actor": None,
        "action": "empty",
        "sourceChannel": None,
        "sourceGeneration": None,
        "rollbackFromGeneration": None,
        "impactGateSha256": None,
        "gateAuthorizationSha256": None,
        "reason": None,
    }


def event(operation: str, actor: str, occurred_at: str, **values: Any) -> dict[str, Any]:
    result = {
        "operation": operation,
        "actor": actor,
        "occurredAt": occurred_at,
        "packageSha256": None,
        "lockSha256": None,
        "channel": None,
        "sourceChannel": None,
        "sourceGeneration": None,
        "rollbackFromGeneration": None,
        "rollbackToGeneration": None,
        "impactGateSha256": None,
        "gateAuthorizationSha256": None,
        "reason": None,
    }
    result.update(values)
    return result


def pointer_path(root: Path) -> Path:
    return safe_member(root, "registry.json", "Registry pointer")


def standby_marker_path(root: Path) -> Path:
    return safe_member(root, ".pdr-standby.json", "Registry standby marker")


def validate_standby_marker(document: Any, registry_id: str | None = None) -> None:
    fields = {
        "schemaVersion", "product", "standbyId", "registryId",
        "sourceRecoveryPointSha256", "appliedRevision", "appliedStateSha256",
        "syncGeneration", "previousMarkerSha256", "updatedAt",
    }
    if (not isinstance(document, dict) or set(document) != fields
            or document.get("schemaVersion") != 1
            or document.get("product") != STANDBY_PRODUCT
            or any(not package_tool.IDENTIFIER.fullmatch(str(document.get(name, "")))
                   for name in ("standbyId", "registryId"))
            or (registry_id is not None and document["registryId"] != registry_id)
            or not package_tool.SHA256.fullmatch(
                str(document.get("sourceRecoveryPointSha256", "")))
            or type(document.get("appliedRevision")) is not int
            or document["appliedRevision"] < 0
            or not package_tool.SHA256.fullmatch(
                str(document.get("appliedStateSha256", "")))
            or type(document.get("syncGeneration")) is not int
            or document["syncGeneration"] < 1
            or (document.get("previousMarkerSha256") is not None
                and not package_tool.SHA256.fullmatch(
                    str(document["previousMarkerSha256"])) )):
        raise ValueError("team contract Registry standby marker is malformed")
    package_tool.parse_time(document.get("updatedAt"), "standby updatedAt")


def read_standby_marker(root: Path, registry_id: str | None = None) \
        -> tuple[dict[str, Any], str] | None:
    path = standby_marker_path(root)
    if not path.exists():
        return None
    if linklike(path) or not path.is_file():
        raise ValueError("team contract Registry standby marker must be a regular file")
    content = path.read_bytes()
    try:
        document = json.loads(content)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("team contract Registry standby marker is invalid JSON") from error
    validate_standby_marker(document, registry_id)
    return document, package_tool.sha256_bytes(content)


def require_primary(root: Path) -> None:
    standby = read_standby_marker(root)
    if standby is not None:
        raise ValueError(
            "team contract Registry standby is read-only; external promotion is required"
        )
    leader_binding = safe_member(
        root, ".pdr-leader.json", "Registry leader binding"
    )
    if leader_binding.exists():
        import team_contract_registry_leader as leader_tool
        leader_tool.verify_registry_write_authority(root)


def state_path(root: Path, revision: int, digest: str) -> Path:
    return safe_member(
        root, f"revisions/{revision:020d}-{digest}.json", "Registry state"
    )


def package_blob(root: Path, digest: str) -> Path:
    return safe_member(
        root, f"blobs/packages/{digest[:2]}/{digest}.pdrcontracts",
        "Registry package blob",
    )


def lock_blob(root: Path, digest: str) -> Path:
    return safe_member(
        root, f"blobs/locks/{digest[:2]}/{digest}.lock.json", "Registry lock blob"
    )


def load_json(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError(f"{label} is unavailable or is a link: {path}")
    try:
        document = json.loads(path.read_bytes())
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} is invalid JSON: {path}") from error
    if not isinstance(document, dict):
        raise ValueError(f"{label} is not an object: {path}")
    return document


def validate_pointer(pointer: dict[str, Any]) -> None:
    if (set(pointer) != {
            "schemaVersion", "product", "registryId", "revision",
            "stateSha256", "updatedAt"
        } or pointer.get("schemaVersion") != 1
            or pointer.get("product") != POINTER_PRODUCT
            or not package_tool.IDENTIFIER.fullmatch(str(pointer.get("registryId", "")))
            or type(pointer.get("revision")) is not int or pointer["revision"] < 0
            or not package_tool.SHA256.fullmatch(str(pointer.get("stateSha256", "")))):
        raise ValueError("team contract Registry pointer is malformed")
    package_tool.parse_time(pointer.get("updatedAt"), "Registry pointer updatedAt")


def valid_nullable(value: Any, pattern: Any) -> bool:
    return value is None or bool(pattern.fullmatch(str(value)))


def validate_event(value: Any) -> None:
    fields = {
        "operation", "actor", "occurredAt", "packageSha256", "lockSha256",
        "channel", "sourceChannel", "sourceGeneration", "rollbackFromGeneration",
        "rollbackToGeneration", "impactGateSha256", "gateAuthorizationSha256", "reason",
    }
    if (not isinstance(value, dict) or set(value) != fields
            or value.get("operation") not in {"init", "publish", "promote", "rollback"}
            or not package_tool.IDENTIFIER.fullmatch(str(value.get("actor", "")))
            or not valid_nullable(value.get("packageSha256"), package_tool.SHA256)
            or not valid_nullable(value.get("lockSha256"), package_tool.SHA256)
            or not valid_nullable(value.get("channel"), package_tool.IDENTIFIER)
            or not valid_nullable(value.get("sourceChannel"), package_tool.IDENTIFIER)
            or not valid_nullable(value.get("impactGateSha256"), package_tool.SHA256)
            or not valid_nullable(value.get("gateAuthorizationSha256"), package_tool.SHA256)
            or any(item is not None and (type(item) is not int or item < 0)
                   for item in (value.get("sourceGeneration"),
                                value.get("rollbackFromGeneration"),
                                value.get("rollbackToGeneration")))
            or (value.get("reason") is not None and (
                not isinstance(value["reason"], str)
                or not 1 <= len(value["reason"]) <= 512))):
        raise ValueError("team contract Registry event is malformed")
    package_tool.parse_time(value.get("occurredAt"), "Registry event occurredAt")


def validate_state(state: dict[str, Any]) -> None:
    fields = {
        "schemaVersion", "product", "registryId", "revision",
        "previousStateSha256", "trustPolicy", "channelOrder", "packages",
        "locks", "channels", "event",
    }
    if (set(state) != fields or state.get("schemaVersion") != 1
            or state.get("product") != STATE_PRODUCT
            or not package_tool.IDENTIFIER.fullmatch(str(state.get("registryId", "")))
            or type(state.get("revision")) is not int or state["revision"] < 0
            or not valid_nullable(state.get("previousStateSha256"), package_tool.SHA256)):
        raise ValueError("team contract Registry state identity is malformed")
    trust = state.get("trustPolicy")
    if (not isinstance(trust, dict) or set(trust) != {"policyId", "policySha256"}
            or not package_tool.IDENTIFIER.fullmatch(str(trust.get("policyId", "")))
            or not package_tool.SHA256.fullmatch(str(trust.get("policySha256", "")))):
        raise ValueError("team contract Registry trust policy identity is malformed")
    order = state.get("channelOrder")
    channels = state.get("channels")
    if (not isinstance(order, list) or not 1 <= len(order) <= MAX_CHANNELS
            or len(order) != len(set(order))
            or any(not package_tool.IDENTIFIER.fullmatch(str(item)) for item in order)
            or not isinstance(channels, list) or len(channels) != len(order)):
        raise ValueError("team contract Registry channel order is malformed")
    package_fields = {
        "packageId", "version", "owner", "packageSha256", "manifestSha256",
        "artifactSetSha256", "signature", "blob",
    }
    packages = state.get("packages")
    if not isinstance(packages, list) or len(packages) > MAX_PACKAGES:
        raise ValueError("team contract Registry package inventory exceeds capacity")
    identities: set[tuple[str, str]] = set()
    digests: set[str] = set()
    for item in packages:
        if not isinstance(item, dict) or set(item) != package_fields:
            raise ValueError("team contract Registry package record is malformed")
        package_tool.validate_identity(item["packageId"], item["version"], item["owner"])
        if ((item["packageId"], item["version"]) in identities
                or item["packageSha256"] in digests
                or any(not package_tool.SHA256.fullmatch(str(item.get(field, "")))
                       for field in ("packageSha256", "manifestSha256",
                                     "artifactSetSha256"))
                or item["blob"] != (
                    f"blobs/packages/{item['packageSha256'][:2]}/"
                    f"{item['packageSha256']}.pdrcontracts")):
            raise ValueError("team contract Registry package identity is duplicated or malformed")
        signature = item.get("signature")
        if (not isinstance(signature, dict)
                or set(signature) != {"keyId", "signatureSha256", "publicKeySha256"}
                or not package_tool.IDENTIFIER.fullmatch(str(signature.get("keyId", "")))
                or any(not package_tool.SHA256.fullmatch(str(signature.get(field, "")))
                       for field in ("signatureSha256", "publicKeySha256"))):
            raise ValueError("team contract Registry package signature evidence is malformed")
        identities.add((item["packageId"], item["version"]))
        digests.add(item["packageSha256"])
    if packages != sorted(packages, key=lambda item: (item["packageId"], item["version"])):
        raise ValueError("team contract Registry package records are not sorted")
    lock_fields = {"lockSha256", "trustPolicy", "packages", "blob"}
    locks = state.get("locks")
    if not isinstance(locks, list) or len(locks) > MAX_LOCKS:
        raise ValueError("team contract Registry lock inventory exceeds capacity")
    lock_digests: set[str] = set()
    package_by_id = {(item["packageId"], item["version"], item["packageSha256"])
                     for item in packages}
    for item in locks:
        if (not isinstance(item, dict) or set(item) != lock_fields
                or not package_tool.SHA256.fullmatch(str(item.get("lockSha256", "")))
                or item["lockSha256"] in lock_digests
                or item.get("trustPolicy") != trust
                or item["blob"] != (
                    f"blobs/locks/{item['lockSha256'][:2]}/"
                    f"{item['lockSha256']}.lock.json")
                or not isinstance(item.get("packages"), list) or not item["packages"]):
            raise ValueError("team contract Registry lock record is malformed")
        lock_ids: set[str] = set()
        for package in item["packages"]:
            if (not isinstance(package, dict)
                    or set(package) != {"packageId", "version", "packageSha256"}
                    or package["packageId"] in lock_ids
                    or (package["packageId"], package["version"],
                        package["packageSha256"]) not in package_by_id):
                raise ValueError("Registry lock references an unpublished package")
            lock_ids.add(package["packageId"])
        if item["packages"] != sorted(item["packages"], key=lambda value: value["packageId"]):
            raise ValueError("team contract Registry lock packages are not sorted")
        lock_digests.add(item["lockSha256"])
    if locks != sorted(locks, key=lambda item: item["lockSha256"]):
        raise ValueError("team contract Registry lock records are not sorted")
    channel_fields = {
        "name", "generation", "lockSha256", "updatedAt", "actor", "action",
        "sourceChannel", "sourceGeneration", "rollbackFromGeneration",
        "impactGateSha256", "gateAuthorizationSha256", "reason",
    }
    for index, channel in enumerate(channels):
        if (not isinstance(channel, dict) or set(channel) != channel_fields
                or channel.get("name") != order[index]
                or type(channel.get("generation")) is not int
                or channel["generation"] < 0
                or not valid_nullable(channel.get("lockSha256"), package_tool.SHA256)
                or channel.get("lockSha256") not in ({None} | lock_digests)
                or not valid_nullable(channel.get("actor"), package_tool.IDENTIFIER)
                or channel.get("action") not in {"empty", "promote", "rollback"}
                or not valid_nullable(channel.get("sourceChannel"), package_tool.IDENTIFIER)
                or not valid_nullable(channel.get("impactGateSha256"), package_tool.SHA256)
                or not valid_nullable(channel.get("gateAuthorizationSha256"),
                                      package_tool.SHA256)
                or any(value is not None and (type(value) is not int or value < 0)
                       for value in (channel.get("sourceGeneration"),
                                    channel.get("rollbackFromGeneration")))):
            raise ValueError("team contract Registry channel state is malformed")
        if channel["generation"] == 0:
            if channel != empty_channel(order[index]):
                raise ValueError("empty Registry channel contains promotion evidence")
        else:
            if (channel["lockSha256"] is None or channel["updatedAt"] is None
                    or channel["actor"] is None or channel["action"] == "empty"):
                raise ValueError("promoted Registry channel lacks evidence")
            package_tool.parse_time(channel["updatedAt"], "Registry channel updatedAt")
    validate_event(state.get("event"))
    if state["revision"] == 0:
        if (state["previousStateSha256"] is not None or state["event"]["operation"] != "init"
                or packages or locks or any(item["generation"] != 0 for item in channels)):
            raise ValueError("initial Registry state is not empty")
    elif state["previousStateSha256"] is None or state["event"]["operation"] == "init":
        raise ValueError("non-initial Registry state lacks previous-state evidence")


def read_current(root: Path) -> tuple[dict[str, Any], dict[str, Any], Path]:
    pointer = load_json(pointer_path(root), "team contract Registry pointer")
    validate_pointer(pointer)
    path = state_path(root, pointer["revision"], pointer["stateSha256"])
    state = load_json(path, "team contract Registry state")
    validate_state(state)
    if (package_tool.sha256_file(path) != pointer["stateSha256"]
            or state["registryId"] != pointer["registryId"]
            or state["revision"] != pointer["revision"]
            or state["event"]["occurredAt"] != pointer["updatedAt"]):
        raise ValueError("team contract Registry pointer does not match immutable state")
    return pointer, state, path


def commit(root: Path, previous: dict[str, Any] | None,
           state: dict[str, Any], lease: RegistryLease) -> tuple[dict[str, Any], str]:
    validate_state(state)
    content = package_tool.json_bytes(state)
    digest = package_tool.sha256_bytes(content)
    path = state_path(root, state["revision"], digest)
    exclusive_bytes(path, content)
    pointer = {
        "schemaVersion": 1,
        "product": POINTER_PRODUCT,
        "registryId": state["registryId"],
        "revision": state["revision"],
        "stateSha256": digest,
        "updatedAt": state["event"]["occurredAt"],
    }
    if previous is not None and state["previousStateSha256"] != previous["stateSha256"]:
        raise ValueError("new Registry state does not extend the current pointer")
    # Re-read the external grant immediately before the mutable pointer commit.
    # A grant change that races an operation therefore fences the old writer.
    require_primary(root)
    lease.assert_current()
    package_tool.write_json(pointer_path(root), pointer)
    return pointer, digest


def validate_transition(previous: dict[str, Any], current: dict[str, Any],
                        history: dict[tuple[str, int], str | None]) -> None:
    if (current["revision"] != previous["revision"] + 1
            or current["registryId"] != previous["registryId"]
            or current["trustPolicy"] != previous["trustPolicy"]
            or current["channelOrder"] != previous["channelOrder"]
            or package_tool.parse_time(current["event"]["occurredAt"], "Registry event")
            < package_tool.parse_time(previous["event"]["occurredAt"], "Registry event")):
        raise ValueError("team contract Registry state transition identity changed")
    operation = current["event"]["operation"]
    changed_channels = [
        (before, after) for before, after in zip(previous["channels"], current["channels"])
        if before != after
    ]
    previous_packages = {
        (item["packageId"], item["version"], item["packageSha256"]): item
        for item in previous["packages"]
    }
    current_packages = {
        (item["packageId"], item["version"], item["packageSha256"]): item
        for item in current["packages"]
    }
    previous_locks = {item["lockSha256"]: item for item in previous["locks"]}
    current_locks = {item["lockSha256"]: item for item in current["locks"]}
    if operation == "publish":
        added = set(current_packages) - set(previous_packages)
        if (len(added) != 1 or not set(previous_packages).issubset(current_packages)
                or previous["locks"] != current["locks"]
                or previous["channels"] != current["channels"]
                or current["event"]["packageSha256"] != next(iter(added))[2]
                or any(current["event"][field] is not None for field in (
                    "lockSha256", "channel", "sourceChannel", "sourceGeneration",
                    "rollbackFromGeneration", "rollbackToGeneration",
                    "impactGateSha256", "gateAuthorizationSha256", "reason"))):
            raise ValueError("team contract Registry publish transition is malformed")
    elif operation == "promote":
        added_locks = set(current_locks) - set(previous_locks)
        if (current["packages"] != previous["packages"]
                or not set(previous_locks).issubset(current_locks)
                or len(added_locks) > 1 or len(changed_channels) != 1):
            raise ValueError("team contract Registry promotion transition is malformed")
        before, after = changed_channels[0]
        index = current["channelOrder"].index(after["name"])
        expected_source = current["channels"][index - 1] if index > 0 else None
        if (after["generation"] != before["generation"] + 1
                or after["action"] != "promote"
                or current["event"]["lockSha256"] != after["lockSha256"]
                or current["event"]["channel"] != after["name"]
                or current["event"]["sourceChannel"] != after["sourceChannel"]
                or current["event"]["sourceGeneration"] != after["sourceGeneration"]
                or current["event"]["impactGateSha256"] != after["impactGateSha256"]
                or current["event"]["gateAuthorizationSha256"]
                    != after["gateAuthorizationSha256"]
                or after["rollbackFromGeneration"] is not None or after["reason"] is not None
                or current["event"]["packageSha256"] is not None
                or current["event"]["rollbackFromGeneration"] is not None
                or current["event"]["rollbackToGeneration"] is not None
                or current["event"]["reason"] is not None
                or (index == 0 and (after["sourceChannel"] is not None
                                    or after["sourceGeneration"] is not None
                                    or after["impactGateSha256"] is not None
                                    or after["gateAuthorizationSha256"] is not None))
                or (index > 0 and (
                    after["sourceChannel"] != expected_source["name"]
                    or after["sourceGeneration"] != expected_source["generation"]
                    or after["lockSha256"] != expected_source["lockSha256"]
                    or after["impactGateSha256"] is None
                    or after["gateAuthorizationSha256"] is None))):
            raise ValueError("team contract Registry promotion evidence is inconsistent")
    elif operation == "rollback":
        if (current["packages"] != previous["packages"]
                or current["locks"] != previous["locks"] or len(changed_channels) != 1):
            raise ValueError("team contract Registry rollback transition is malformed")
        before, after = changed_channels[0]
        target_generation = current["event"]["rollbackToGeneration"]
        if (after["generation"] != before["generation"] + 1
                or after["action"] != "rollback"
                or after["rollbackFromGeneration"] != before["generation"]
                or current["event"]["rollbackFromGeneration"] != before["generation"]
                or type(target_generation) is not int
                or not 1 <= target_generation < before["generation"]
                or history.get((after["name"], target_generation)) != after["lockSha256"]
                or current["event"]["lockSha256"] != after["lockSha256"]
                or current["event"]["channel"] != after["name"]
                or current["event"]["reason"] != after["reason"]
                or after["sourceChannel"] is not None
                or after["sourceGeneration"] is not None
                or after["impactGateSha256"] is not None
                or after["gateAuthorizationSha256"] is not None
                or current["event"]["packageSha256"] is not None
                or current["event"]["sourceChannel"] is not None
                or current["event"]["sourceGeneration"] is not None
                or current["event"]["impactGateSha256"] is not None
                or current["event"]["gateAuthorizationSha256"] is not None):
            raise ValueError("team contract Registry rollback evidence is inconsistent")
    else:
        raise ValueError("team contract Registry contains an unexpected init transition")


def verify_chain(root: Path, pointer: dict[str, Any], state: dict[str, Any]) -> None:
    revision = pointer["revision"]
    digest = pointer["stateSha256"]
    current = state
    chain: list[tuple[str, dict[str, Any]]] = []
    while True:
        path = state_path(root, revision, digest)
        if package_tool.sha256_file(path) != digest:
            raise ValueError(f"Registry state revision {revision} digest changed")
        validate_state(current)
        if current["revision"] != revision or current["registryId"] != pointer["registryId"]:
            raise ValueError("Registry state history identity changed")
        if revision == 0:
            if current["previousStateSha256"] is not None:
                raise ValueError("Registry initial state has an unexpected predecessor")
            chain.append((digest, current))
            break
        chain.append((digest, current))
        digest = current["previousStateSha256"]
        revision -= 1
        path = state_path(root, revision, digest)
        current = load_json(path, f"team contract Registry state revision {revision}")
    chain.reverse()
    history: dict[tuple[str, int], str | None] = {}
    for channel in chain[0][1]["channels"]:
        history[(channel["name"], channel["generation"])] = channel["lockSha256"]
    for index in range(1, len(chain)):
        previous_digest, previous = chain[index - 1]
        _, current = chain[index]
        if current["previousStateSha256"] != previous_digest:
            raise ValueError("team contract Registry state chain is disconnected")
        validate_transition(previous, current, history)
        for channel in current["channels"]:
            history[(channel["name"], channel["generation"])] = channel["lockSha256"]


def package_record(verified: dict[str, Any], trust: dict[str, Any]) -> dict[str, Any]:
    manifest = verified["manifest"]
    digest = verified["packageSha256"]
    signature = verified.get("signature")
    if signature is None or verified.get("signatureSha256") is None:
        raise ValueError("Registry accepts only signed team contract packages")
    return {
        "packageId": manifest["packageId"],
        "version": manifest["version"],
        "owner": manifest["owner"],
        "packageSha256": digest,
        "manifestSha256": verified["manifestSha256"],
        "artifactSetSha256": manifest["artifactSetSha256"],
        "signature": {
            "keyId": signature["keyId"],
            "signatureSha256": verified["signatureSha256"],
            "publicKeySha256": trust["publicKeySha256"],
        },
        "blob": f"blobs/packages/{digest[:2]}/{digest}.pdrcontracts",
    }


def lock_record(lock: dict[str, Any], digest: str) -> dict[str, Any]:
    return {
        "lockSha256": digest,
        "trustPolicy": lock["trustPolicy"],
        "packages": [{
            "packageId": item["packageId"],
            "version": item["version"],
            "packageSha256": item["packageSha256"],
        } for item in lock["packages"]],
        "blob": f"blobs/locks/{digest[:2]}/{digest}.lock.json",
    }


def verify_inventory(root: Path, state: dict[str, Any], args: argparse.Namespace) -> None:
    expected_trust = trust_identity(args)
    if state["trustPolicy"] != expected_trust:
        raise ValueError("supplied trust policy does not match the Registry policy pin")
    at = package_tool.verification_time(args.verification_time)
    for record in state["packages"]:
        path = safe_member(root, record["blob"], "Registry package blob")
        if (linklike(path) or not path.is_file()
                or package_tool.sha256_file(path) != record["packageSha256"]):
            raise ValueError(f"Registry package blob changed: {record['packageId']}")
        verified = package_tool.verify_package(
            path, args.maximum_files, args.maximum_expanded_bytes
        )
        trust = package_tool.verify_trust(
            verified, Path(args.trust_policy), args.expected_trust_policy_id,
            args.expected_trust_policy_sha256, at,
        )
        if package_record(verified, trust) != record:
            raise ValueError(f"Registry package evidence changed: {record['packageId']}")
    for record in state["locks"]:
        path = safe_member(root, record["blob"], "Registry lock blob")
        if (linklike(path) or not path.is_file()
                or package_tool.sha256_file(path) != record["lockSha256"]):
            raise ValueError("Registry lock blob changed")
        lock = package_tool.load_lock(path)
        if lock.get("trustPolicy") != state["trustPolicy"] \
                or lock_record(lock, record["lockSha256"]) != record:
            raise ValueError("Registry lock evidence changed")


def verified_current(root: Path, args: argparse.Namespace) \
        -> tuple[dict[str, Any], dict[str, Any]]:
    pointer, state, _ = read_current(root)
    verify_chain(root, pointer, state)
    verify_inventory(root, state, args)
    return pointer, state


def operation_report(root: Path, pointer: dict[str, Any], operation: str,
                     package_sha: str | None = None, lock_sha: str | None = None,
                     channel: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "product": OPERATION_PRODUCT,
        "operation": operation,
        "passed": True,
        "registry": str(root),
        "registryId": pointer["registryId"],
        "revision": pointer["revision"],
        "stateSha256": pointer["stateSha256"],
        "packageSha256": package_sha,
        "lockSha256": lock_sha,
        "channel": channel["name"] if channel else None,
        "generation": channel["generation"] if channel else None,
    }


def write_report(args: argparse.Namespace, report: dict[str, Any]) -> None:
    if args.report:
        package_tool.write_json(Path(args.report).resolve(), report)


def require_expected_revision(args: argparse.Namespace, pointer: dict[str, Any]) -> None:
    expected = getattr(args, "expected_revision", None)
    if expected is not None and pointer["revision"] != expected:
        raise ValueError(
            f"Registry revision changed: expected={expected} actual={pointer['revision']}"
        )


def init_command(args: argparse.Namespace) -> int:
    try:
        root = registry_root(args.registry, create=True)
        if pointer_path(root).exists():
            raise FileExistsError(f"team contract Registry already exists: {root}")
        if not package_tool.IDENTIFIER.fullmatch(args.registry_id):
            raise ValueError("team contract Registry id is invalid")
        if not package_tool.IDENTIFIER.fullmatch(args.actor):
            raise ValueError("team contract Registry actor is invalid")
        channels = args.channel or ["dev", "staging", "production"]
        if (not 1 <= len(channels) <= MAX_CHANNELS or len(channels) != len(set(channels))
                or any(not package_tool.IDENTIFIER.fullmatch(value) for value in channels)):
            raise ValueError("team contract Registry channel order is invalid")
        trust = trust_identity(args)
        occurred_at = utc_time(args.occurred_at)
        with RegistryLease(root, "init", args.actor) as lease:
            state = {
                "schemaVersion": 1,
                "product": STATE_PRODUCT,
                "registryId": args.registry_id,
                "revision": 0,
                "previousStateSha256": None,
                "trustPolicy": trust,
                "channelOrder": channels,
                "packages": [],
                "locks": [],
                "channels": [empty_channel(value) for value in channels],
                "event": event("init", args.actor, occurred_at),
            }
            pointer, _ = commit(root, None, state, lease)
        report = operation_report(root, pointer, "init")
        write_report(args, report)
        print(f"PDR_TEAM_CONTRACT_REGISTRY_INIT_PASS id={args.registry_id} root={root}")
        return 0
    except (OSError, UnicodeError, ValueError, RuntimeError) as error:
        print(f"PDR_TEAM_CONTRACT_REGISTRY_INIT_ERROR: {error}", file=sys.stderr)
        return 2


def next_state(pointer: dict[str, Any], state: dict[str, Any],
               mutation_event: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(state)
    result["revision"] = state["revision"] + 1
    result["previousStateSha256"] = pointer["stateSha256"]
    result["event"] = mutation_event
    return result


def publish_command(args: argparse.Namespace) -> int:
    try:
        root = registry_root(args.registry)
        require_primary(root)
        if not package_tool.IDENTIFIER.fullmatch(args.actor):
            raise ValueError("team contract Registry actor is invalid")
        occurred_at = utc_time(args.occurred_at)
        package = package_tool.resolved_path(args.package, "team contract package")
        with RegistryLease(root, "publish", args.actor) as lease:
            require_primary(root)
            pointer, state = verified_current(root, args)
            require_expected_revision(args, pointer)
            verified = package_tool.verify_package(
                package, args.maximum_files, args.maximum_expanded_bytes
            )
            trust = package_tool.verify_trust(
                verified, Path(args.trust_policy), args.expected_trust_policy_id,
                args.expected_trust_policy_sha256,
                package_tool.verification_time(args.verification_time),
            )
            record = package_record(verified, trust)
            same_version = [item for item in state["packages"]
                            if item["packageId"] == record["packageId"]
                            and item["version"] == record["version"]]
            if same_version:
                if same_version[0] != record:
                    raise ValueError("Registry rejects same-version package content drift")
                report = operation_report(
                    root, pointer, "publish", package_sha=record["packageSha256"]
                )
                write_report(args, report)
                print("PDR_TEAM_CONTRACT_REGISTRY_PUBLISH_PASS existing=true "
                      f"sha256={record['packageSha256']}")
                return 0
            if len(state["packages"]) >= MAX_PACKAGES:
                raise ValueError("team contract Registry package capacity is exhausted")
            destination = package_blob(root, record["packageSha256"])
            exclusive_bytes(destination, package.read_bytes())
            updated = next_state(
                pointer, state,
                event("publish", args.actor, occurred_at,
                      packageSha256=record["packageSha256"]),
            )
            updated["packages"].append(record)
            updated["packages"].sort(key=lambda item: (item["packageId"], item["version"]))
            new_pointer, _ = commit(root, pointer, updated, lease)
        report = operation_report(
            root, new_pointer, "publish", package_sha=record["packageSha256"]
        )
        write_report(args, report)
        print(f"PDR_TEAM_CONTRACT_REGISTRY_PUBLISH_PASS id={record['packageId']} "
              f"version={record['version']} revision={new_pointer['revision']}")
        return 0
    except (OSError, UnicodeError, ValueError, RuntimeError) as error:
        print(f"PDR_TEAM_CONTRACT_REGISTRY_PUBLISH_ERROR: {error}", file=sys.stderr)
        return 2


def validate_impact_gate(path: str | None, lock_sha: str) -> tuple[str, dict[str, Any]]:
    if not path:
        raise ValueError("non-development promotion requires impact Gate evidence")
    gate_path = package_tool.resolved_path(path, "team contract impact Gate")
    gate = load_json(gate_path, "team contract impact Gate")
    fields = {
        "schemaVersion", "product", "operation", "passed", "impactReportSha256",
        "impactInputSetSha256", "candidateLockSha256", "executionEvidenceSha256",
        "junitSha256", "runnerAttestation", "approvalPolicy", "requiredOwners",
        "approvedOwners", "approvals",
    }
    runner = gate.get("runnerAttestation")
    runner_fields = {
        "attestationSha256", "policyId", "policySha256", "runnerId", "repository",
        "sourceRevision", "workflow", "jobId", "runId", "keyId",
        "publicKeySha256", "issuedAt", "expiresAt",
    }
    if (set(gate) != fields or gate.get("schemaVersion") != 1
            or gate.get("product") != IMPACT_GATE_PRODUCT
            or gate.get("operation") != "team-contract-impact-gate"
            or gate.get("passed") is not True
            or gate.get("candidateLockSha256") != lock_sha
            or any(not package_tool.SHA256.fullmatch(str(gate.get(field, "")))
                   for field in ("impactReportSha256", "impactInputSetSha256",
                                 "executionEvidenceSha256"))
            or not isinstance(gate.get("requiredOwners"), list)
            or gate.get("approvedOwners") != gate["requiredOwners"]
            or len(gate["requiredOwners"]) != len(set(gate["requiredOwners"]))
            or not isinstance(runner, dict) or set(runner) != runner_fields
            or any(not package_tool.SHA256.fullmatch(str(runner.get(field, "")))
                   for field in ("attestationSha256", "policySha256", "publicKeySha256"))
            or any(not package_tool.IDENTIFIER.fullmatch(str(runner.get(field, "")))
                   for field in ("policyId", "runnerId", "workflow", "jobId", "runId", "keyId"))
            or not re.fullmatch(r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+",
                                str(runner.get("repository", "")))
            or not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})",
                                str(runner.get("sourceRevision", "")))):
        raise ValueError("team contract impact Gate is malformed or for another lock")
    package_tool.parse_time(runner["issuedAt"], "runner issuedAt")
    package_tool.parse_time(runner["expiresAt"], "runner expiresAt")
    return package_tool.sha256_file(gate_path), runner


def register_lock(root: Path, state: dict[str, Any], lock_path: Path) \
        -> tuple[dict[str, Any], dict[str, Any]]:
    lock = package_tool.load_lock(lock_path)
    if lock.get("trustPolicy") != state["trustPolicy"]:
        raise ValueError("promoted lock does not match the Registry trust policy pin")
    digest = package_tool.sha256_file(lock_path)
    record = lock_record(lock, digest)
    available = {(item["packageId"], item["version"], item["packageSha256"])
                 for item in state["packages"]}
    missing = [item for item in record["packages"]
               if (item["packageId"], item["version"], item["packageSha256"])
               not in available]
    if missing:
        raise ValueError("promoted lock references packages not published in the Registry")
    existing = [item for item in state["locks"] if item["lockSha256"] == digest]
    if existing and existing[0] != record:
        raise ValueError("Registry lock digest identity changed")
    if not existing:
        if len(state["locks"]) >= MAX_LOCKS:
            raise ValueError("team contract Registry lock capacity is exhausted")
        exclusive_bytes(lock_blob(root, digest), lock_path.read_bytes())
        state["locks"].append(record)
        state["locks"].sort(key=lambda item: item["lockSha256"])
    return record, lock


def core_version(value: str) -> tuple[int, int, int]:
    return tuple(int(item) for item in value.split("-", 1)[0].split("+", 1)[0].split("."))


def reject_downgrade(state: dict[str, Any], current_sha: str | None,
                     candidate: dict[str, Any]) -> None:
    if current_sha is None:
        return
    current = next(item for item in state["locks"] if item["lockSha256"] == current_sha)
    current_versions = {item["packageId"]: item["version"] for item in current["packages"]}
    candidate_versions = {item["packageId"]: item["version"] for item in candidate["packages"]}
    removed = sorted(set(current_versions) - set(candidate_versions))
    downgraded = sorted(package_id for package_id in set(current_versions) & set(candidate_versions)
                        if core_version(candidate_versions[package_id])
                        < core_version(current_versions[package_id]))
    if removed or downgraded:
        raise ValueError(
            f"Registry promotion cannot remove or downgrade packages; "
            f"removed={removed} downgraded={downgraded}"
        )


def promote_command(args: argparse.Namespace) -> int:
    try:
        root = registry_root(args.registry)
        require_primary(root)
        if not package_tool.IDENTIFIER.fullmatch(args.actor):
            raise ValueError("team contract Registry actor is invalid")
        occurred_at = utc_time(args.occurred_at)
        supplied_lock = package_tool.resolved_path(args.lock, "team contract package lock")
        with RegistryLease(root, "promote", args.actor) as lease:
            require_primary(root)
            pointer, state = verified_current(root, args)
            require_expected_revision(args, pointer)
            if args.channel not in state["channelOrder"]:
                raise ValueError(f"unknown Registry channel: {args.channel}")
            index = state["channelOrder"].index(args.channel)
            target = state["channels"][index]
            if target["generation"] != args.expected_generation:
                raise ValueError(
                    f"Registry channel generation changed: expected={args.expected_generation} "
                    f"actual={target['generation']}"
                )
            updated = next_state(pointer, state, {})
            record, _ = register_lock(root, updated, supplied_lock)
            lock_sha = record["lockSha256"]
            source = updated["channels"][index - 1] if index > 0 else None
            if source is not None and source["lockSha256"] != lock_sha:
                raise ValueError(
                    f"Registry channel {args.channel} may only promote the current "
                    f"{source['name']} lock"
                )
            if index > 0:
                gate_sha, gate_runner = validate_impact_gate(args.impact_gate, lock_sha)
                runner_arguments = (
                    args.runner_attestation, args.runner_trust_policy,
                    args.expected_runner_trust_policy_id,
                    args.expected_runner_trust_policy_sha256,
                )
                if not all(runner_arguments):
                    raise ValueError(
                        "non-development promotion requires a pinned Runner attestation"
                    )
                import team_contract_provenance as provenance_tool
                attestation, runner_verification = provenance_tool.verify_runner_signature(
                    args.runner_attestation, args.runner_trust_policy,
                    args.expected_runner_trust_policy_id,
                    args.expected_runner_trust_policy_sha256, args.verification_time,
                )
                if (attestation["candidateLockSha256"] != lock_sha
                        or runner_verification != gate_runner):
                    raise ValueError(
                        "Runner attestation does not match the promoted lock and impact Gate"
                    )
                authorization_arguments = (
                    args.gate_authorization, args.gate_authorization_policy,
                    args.expected_gate_authorization_policy_id,
                    args.expected_gate_authorization_policy_sha256,
                )
                if not all(authorization_arguments):
                    raise ValueError(
                        "non-development promotion requires a pinned Gate authorization"
                    )
                authorization = provenance_tool.verify_gate_authorization(
                    args.impact_gate, args.gate_authorization,
                    args.gate_authorization_policy,
                    args.expected_gate_authorization_policy_id,
                    args.expected_gate_authorization_policy_sha256,
                    state["registryId"], args.channel, args.verification_time,
                )
                if (authorization["candidateLockSha256"] != lock_sha
                        or authorization["gateReportSha256"] != gate_sha):
                    raise ValueError(
                        "Gate authorization does not match the promoted lock and impact Gate"
                    )
                authorization_sha = authorization["authorizationSha256"]
            else:
                gate_sha = None
                authorization_sha = None
            reject_downgrade(updated, target["lockSha256"], record)
            if target["lockSha256"] == lock_sha:
                report = operation_report(root, pointer, "promote", lock_sha=lock_sha,
                                          channel=target)
                write_report(args, report)
                print("PDR_TEAM_CONTRACT_REGISTRY_PROMOTE_PASS existing=true "
                      f"channel={target['name']} generation={target['generation']}")
                return 0
            generation = target["generation"] + 1
            promoted = {
                "name": target["name"],
                "generation": generation,
                "lockSha256": lock_sha,
                "updatedAt": occurred_at,
                "actor": args.actor,
                "action": "promote",
                "sourceChannel": source["name"] if source else None,
                "sourceGeneration": source["generation"] if source else None,
                "rollbackFromGeneration": None,
                "impactGateSha256": gate_sha,
                "gateAuthorizationSha256": authorization_sha,
                "reason": None,
            }
            updated["channels"][index] = promoted
            updated["event"] = event(
                "promote", args.actor, occurred_at, lockSha256=lock_sha,
                channel=target["name"], sourceChannel=promoted["sourceChannel"],
                sourceGeneration=promoted["sourceGeneration"],
                impactGateSha256=gate_sha,
                gateAuthorizationSha256=authorization_sha,
            )
            new_pointer, _ = commit(root, pointer, updated, lease)
        report = operation_report(
            root, new_pointer, "promote", lock_sha=lock_sha, channel=promoted
        )
        write_report(args, report)
        print(f"PDR_TEAM_CONTRACT_REGISTRY_PROMOTE_PASS channel={promoted['name']} "
              f"generation={generation} lockSha256={lock_sha}")
        return 0
    except (OSError, UnicodeError, ValueError, RuntimeError) as error:
        print(f"PDR_TEAM_CONTRACT_REGISTRY_PROMOTE_ERROR: {error}", file=sys.stderr)
        return 2


def historical_channel(root: Path, pointer: dict[str, Any], state: dict[str, Any],
                       channel_name: str, generation: int) -> dict[str, Any]:
    current = state
    revision = pointer["revision"]
    while True:
        channel = next(item for item in current["channels"] if item["name"] == channel_name)
        if channel["generation"] == generation:
            return channel
        if revision == 0:
            break
        digest = current["previousStateSha256"]
        revision -= 1
        current = load_json(
            state_path(root, revision, digest),
            f"team contract Registry state revision {revision}",
        )
        validate_state(current)
    raise ValueError(
        f"Registry channel {channel_name} has no historical generation {generation}"
    )


def rollback_command(args: argparse.Namespace) -> int:
    try:
        root = registry_root(args.registry)
        require_primary(root)
        if (not package_tool.IDENTIFIER.fullmatch(args.actor)
                or not isinstance(args.reason, str) or not 1 <= len(args.reason) <= 512):
            raise ValueError("Registry rollback actor or reason is invalid")
        occurred_at = utc_time(args.occurred_at)
        with RegistryLease(root, "rollback", args.actor) as lease:
            require_primary(root)
            pointer, state = verified_current(root, args)
            require_expected_revision(args, pointer)
            if args.channel not in state["channelOrder"]:
                raise ValueError(f"unknown Registry channel: {args.channel}")
            index = state["channelOrder"].index(args.channel)
            current = state["channels"][index]
            if current["generation"] != args.expected_generation:
                raise ValueError(
                    f"Registry channel generation changed: expected={args.expected_generation} "
                    f"actual={current['generation']}"
                )
            if not 1 <= args.to_generation < current["generation"]:
                raise ValueError("rollback target must be an earlier non-empty channel generation")
            target = historical_channel(
                root, pointer, state, args.channel, args.to_generation
            )
            if target["lockSha256"] is None:
                raise ValueError("Registry rollback target channel generation is empty")
            updated = next_state(pointer, state, {})
            rolled_back = {
                "name": current["name"],
                "generation": current["generation"] + 1,
                "lockSha256": target["lockSha256"],
                "updatedAt": occurred_at,
                "actor": args.actor,
                "action": "rollback",
                "sourceChannel": None,
                "sourceGeneration": None,
                "rollbackFromGeneration": current["generation"],
                "impactGateSha256": None,
                "gateAuthorizationSha256": None,
                "reason": args.reason,
            }
            updated["channels"][index] = rolled_back
            updated["event"] = event(
                "rollback", args.actor, occurred_at,
                lockSha256=target["lockSha256"], channel=args.channel,
                rollbackFromGeneration=current["generation"],
                rollbackToGeneration=args.to_generation, reason=args.reason,
            )
            new_pointer, _ = commit(root, pointer, updated, lease)
        report = operation_report(
            root, new_pointer, "rollback", lock_sha=target["lockSha256"],
            channel=rolled_back,
        )
        write_report(args, report)
        print(f"PDR_TEAM_CONTRACT_REGISTRY_ROLLBACK_PASS channel={args.channel} "
              f"generation={rolled_back['generation']} to={args.to_generation}")
        return 0
    except (OSError, UnicodeError, ValueError, RuntimeError) as error:
        print(f"PDR_TEAM_CONTRACT_REGISTRY_ROLLBACK_ERROR: {error}", file=sys.stderr)
        return 2


def verify_command(args: argparse.Namespace) -> int:
    try:
        root = registry_root(args.registry)
        pointer, state = verified_current(root, args)
        report = operation_report(root, pointer, "verify")
        write_report(args, report)
        print(f"PDR_TEAM_CONTRACT_REGISTRY_VERIFY_PASS id={state['registryId']} "
              f"revision={state['revision']} packages={len(state['packages'])} "
              f"locks={len(state['locks'])}")
        return 0
    except (OSError, UnicodeError, ValueError, RuntimeError) as error:
        print(f"PDR_TEAM_CONTRACT_REGISTRY_VERIFY_ERROR: {error}", file=sys.stderr)
        return 2


def resolve_command(args: argparse.Namespace) -> int:
    try:
        root = registry_root(args.registry)
        pointer, state = verified_current(root, args)
        matches = [item for item in state["channels"] if item["name"] == args.channel]
        if len(matches) != 1 or matches[0]["lockSha256"] is None:
            raise ValueError(f"Registry channel is unknown or empty: {args.channel}")
        channel = matches[0]
        lock = next(item for item in state["locks"]
                    if item["lockSha256"] == channel["lockSha256"])
        output = Path(args.output).resolve()
        package_report = (Path(args.package_report).resolve() if args.package_report
                          else output.parent / f"{args.channel}.package-resolution.json")
        package_args = argparse.Namespace(
            lock=str(safe_member(root, lock["blob"], "Registry lock blob")),
            package=[str(safe_member(root, next(
                item["blob"] for item in state["packages"]
                if item["packageSha256"] == package["packageSha256"]
            ), "Registry package blob")) for package in lock["packages"]],
            output=str(output),
            report=str(package_report),
            require_signature=True,
            trust_policy=args.trust_policy,
            expected_trust_policy_id=args.expected_trust_policy_id,
            expected_trust_policy_sha256=args.expected_trust_policy_sha256,
            verification_time=args.verification_time,
            maximum_files=args.maximum_files,
            maximum_expanded_bytes=args.maximum_expanded_bytes,
        )
        result = package_tool.resolve(package_args)
        if result != 0:
            raise ValueError(f"team contract package resolution failed: {result}")
        report = {
            "schemaVersion": 1,
            "product": RESOLUTION_PRODUCT,
            "operation": "resolve",
            "passed": True,
            "registry": str(root),
            "registryId": state["registryId"],
            "registryRevision": state["revision"],
            "registryStateSha256": pointer["stateSha256"],
            "channel": channel["name"],
            "generation": channel["generation"],
            "lockSha256": lock["lockSha256"],
            "output": str(output),
            "packageResolutionReport": str(package_report),
            "packageResolutionReportSha256": package_tool.sha256_file(package_report),
            "packages": lock["packages"],
        }
        package_tool.write_json(Path(args.report).resolve(), report)
        print(f"PDR_TEAM_CONTRACT_REGISTRY_RESOLVE_PASS channel={channel['name']} "
              f"generation={channel['generation']} packages={len(lock['packages'])}")
        return 0
    except (OSError, UnicodeError, ValueError, RuntimeError) as error:
        print(f"PDR_TEAM_CONTRACT_REGISTRY_RESOLVE_ERROR: {error}", file=sys.stderr)
        return 2


def lease_status(root: Path) -> dict[str, Any]:
    return process_lease.inspect_lease(
        root / ".registry-write.lock",
        root / ".registry-write.epoch.json",
        "team-contract-registry-writer",
    )


def lease_status_command(args: argparse.Namespace) -> int:
    try:
        root = registry_root(args.registry)
        report = lease_status(root)
        if args.report:
            package_tool.write_json(Path(args.report).resolve(), report)
        marker = "PASS" if report["healthy"] else "ERROR"
        stream = sys.stdout if report["healthy"] else sys.stderr
        print(
            f"PDR_TEAM_CONTRACT_REGISTRY_LEASE_{marker} "
            f"active={str(report['active']).lower()} epoch={report['epoch']} "
            f"healthy={str(report['healthy']).lower()}",
            file=stream,
        )
        return 0 if report["healthy"] else 2
    except (OSError, UnicodeError, ValueError, RuntimeError) as error:
        print(f"PDR_TEAM_CONTRACT_REGISTRY_LEASE_ERROR: {error}", file=sys.stderr)
        return 2


def add_trust_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--trust-policy", required=True)
    parser.add_argument("--expected-trust-policy-id", required=True)
    parser.add_argument("--expected-trust-policy-sha256", required=True)
    parser.add_argument("--verification-time")


def add_limits(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--maximum-files", type=int,
                        default=package_tool.MAX_FILES_DEFAULT)
    parser.add_argument("--maximum-expanded-bytes", type=int,
                        default=package_tool.MAX_EXPANDED_BYTES_DEFAULT)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="initialize an immutable Registry state chain")
    init.add_argument("--registry", required=True)
    init.add_argument("--registry-id", required=True)
    init.add_argument("--channel", action="append", default=[])
    init.add_argument("--actor", required=True)
    init.add_argument("--occurred-at")
    init.add_argument("--report")
    add_trust_arguments(init)
    init.set_defaults(handler=init_command)
    publish = commands.add_parser("publish", help="publish one trusted immutable package blob")
    publish.add_argument("--registry", required=True)
    publish.add_argument("--package", required=True)
    publish.add_argument("--actor", required=True)
    publish.add_argument("--expected-revision", type=int)
    publish.add_argument("--occurred-at")
    publish.add_argument("--report")
    add_trust_arguments(publish)
    add_limits(publish)
    publish.set_defaults(handler=publish_command)
    promote = commands.add_parser("promote", help="atomically promote one exact lock to a channel")
    promote.add_argument("--registry", required=True)
    promote.add_argument("--channel", required=True)
    promote.add_argument("--lock", required=True)
    promote.add_argument("--expected-generation", type=int, required=True)
    promote.add_argument("--expected-revision", type=int)
    promote.add_argument("--impact-gate")
    promote.add_argument("--runner-attestation")
    promote.add_argument("--runner-trust-policy")
    promote.add_argument("--expected-runner-trust-policy-id")
    promote.add_argument("--expected-runner-trust-policy-sha256")
    promote.add_argument("--gate-authorization")
    promote.add_argument("--gate-authorization-policy")
    promote.add_argument("--expected-gate-authorization-policy-id")
    promote.add_argument("--expected-gate-authorization-policy-sha256")
    promote.add_argument("--actor", required=True)
    promote.add_argument("--occurred-at")
    promote.add_argument("--report")
    add_trust_arguments(promote)
    add_limits(promote)
    promote.set_defaults(handler=promote_command)
    rollback = commands.add_parser("rollback", help="restore an earlier channel generation")
    rollback.add_argument("--registry", required=True)
    rollback.add_argument("--channel", required=True)
    rollback.add_argument("--expected-generation", type=int, required=True)
    rollback.add_argument("--expected-revision", type=int)
    rollback.add_argument("--to-generation", type=int, required=True)
    rollback.add_argument("--actor", required=True)
    rollback.add_argument("--reason", required=True)
    rollback.add_argument("--occurred-at")
    rollback.add_argument("--report")
    add_trust_arguments(rollback)
    add_limits(rollback)
    rollback.set_defaults(handler=rollback_command)
    verify = commands.add_parser("verify", help="verify state history, blobs, locks and signatures")
    verify.add_argument("--registry", required=True)
    verify.add_argument("--report")
    add_trust_arguments(verify)
    add_limits(verify)
    verify.set_defaults(handler=verify_command)
    resolve = commands.add_parser("resolve", help="resolve one promoted channel without package paths")
    resolve.add_argument("--registry", required=True)
    resolve.add_argument("--channel", required=True)
    resolve.add_argument("--output", required=True)
    resolve.add_argument("--package-report")
    resolve.add_argument("--report", required=True)
    add_trust_arguments(resolve)
    add_limits(resolve)
    resolve.set_defaults(handler=resolve_command)
    lease_status_parser = commands.add_parser(
        "lease-status", help="inspect the OS-owned Registry writer lease"
    )
    lease_status_parser.add_argument("--registry", required=True)
    lease_status_parser.add_argument("--report")
    lease_status_parser.set_defaults(handler=lease_status_command)
    return result


def main() -> int:
    args = parser().parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
