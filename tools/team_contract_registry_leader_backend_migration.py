#!/usr/bin/env python3
"""Synchronize and finalize a fenced Registry leader backend migration."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import team_contract_package as package_tool
import team_contract_artifact_store as artifact_tool
import team_contract_backend_config_resolver as resolver_tool
import team_contract_registry as registry_tool
import team_contract_registry_leader as leader_tool
import team_contract_registry_leader_backend as backend_tool
import process_file_lease as process_lease


SYNC_PRODUCT = "PocoDDSRuntimeTeamContractRegistryLeaderBackendMigrationSync"
MIGRATION_PRODUCT = "PocoDDSRuntimeTeamContractRegistryLeaderBackendMigration"
TRANSACTION_PRODUCT = \
    "PocoDDSRuntimeTeamContractRegistryLeaderBackendMigrationTransaction"
STATUS_PRODUCT = \
    "PocoDDSRuntimeTeamContractRegistryLeaderBackendMigrationStatus"
ABORT_PRODUCT = \
    "PocoDDSRuntimeTeamContractRegistryLeaderBackendMigrationAbort"


def descriptor(document: Any, label: str) -> dict[str, Any]:
    if isinstance(document, dict) and document.get("kind") == "backend-config-ref":
        try:
            return resolver_tool.validate_reference(document)
        except ValueError as error:
            raise ValueError(f"{label} descriptor is malformed") from error
    fields = {"kind", "backendId", "configPath", "configSha256"}
    if (not isinstance(document, dict) or set(document) != fields
            or document.get("kind") != "external-command"
            or not package_tool.IDENTIFIER.fullmatch(
                str(document.get("backendId", "")))
            or not isinstance(document.get("configPath"), str)
            or not document["configPath"]
            or not package_tool.SHA256.fullmatch(
                str(document.get("configSha256", "")))):
        raise ValueError(f"{label} descriptor is malformed")
    return document


def transaction_store_descriptor(document: Any) -> dict[str, Any]:
    if (isinstance(document, dict) and set(document) == {"kind", "path"}
            and document.get("kind") == "file"
            and isinstance(document.get("path"), str)
            and Path(document["path"]).is_absolute()):
        return document
    return descriptor(document, "transaction store backend")


def _backend(config: str, digest: str, authority_id: str,
             registry_id: str, label: str) \
        -> backend_tool.ExternalCommandBackend:
    backend = backend_tool.ExternalCommandBackend(
        config, digest, authority_id, registry_id
    )
    if (backend.config["schemaVersion"] != 2
            or backend.capability_manifest is None
            or backend.capability_manifest_sha256 is None):
        raise ValueError(f"{label} requires negotiated v2 capabilities")
    return backend


def _config_resolver(args: argparse.Namespace, *, required: bool = False) \
        -> resolver_tool.ExternalCommandBackendConfigResolver | None:
    config = getattr(args, "backend_config_resolver_config", None)
    digest = getattr(
        args, "expected_backend_config_resolver_config_sha256", None
    )
    if bool(config) != bool(digest):
        raise ValueError(
            "backend config resolver requires config and pinned SHA"
        )
    if not config:
        if required:
            raise ValueError(
                "portable backend references require a backend config resolver"
            )
        return None
    return resolver_tool.ExternalCommandBackendConfigResolver(config, digest)


def _reference_file(path_value: str, expected_sha: str, label: str) \
        -> dict[str, Any]:
    path = package_tool.resolved_path(path_value, label)
    content = path.read_bytes()
    digest = package_tool.sha256_bytes(content)
    if digest != str(expected_sha).lower():
        raise ValueError(f"{label} identity changed")
    document = json.loads(content)
    return resolver_tool.validate_reference(document)


def _backend_from_descriptor(
        document: dict[str, Any], authority_id: str, registry_id: str,
        args: argparse.Namespace, label: str) \
        -> backend_tool.ExternalCommandBackend:
    descriptor(document, label)
    if document["kind"] == "external-command":
        return _backend(
            document["configPath"], document["configSha256"],
            authority_id, registry_id, label,
        )
    resolver = _config_resolver(args, required=True)
    assert resolver is not None
    backend = resolver.resolve(document, authority_id, registry_id)
    if (backend.config["schemaVersion"] != 2
            or backend.capability_manifest is None
            or backend.capability_manifest_sha256 is None):
        raise ValueError(f"{label} requires negotiated v2 capabilities")
    return backend


def _backend_endpoints(args: argparse.Namespace) \
        -> tuple[backend_tool.ExternalCommandBackend, dict[str, Any],
                 backend_tool.ExternalCommandBackend, dict[str, Any]]:
    source_ref_value = getattr(args, "source_backend_ref", None)
    source_ref_sha = getattr(args, "expected_source_backend_ref_sha256", None)
    target_ref_value = getattr(args, "target_backend_ref", None)
    target_ref_sha = getattr(args, "expected_target_backend_ref_sha256", None)
    refs = any((source_ref_value, source_ref_sha, target_ref_value, target_ref_sha))
    direct = any((
        getattr(args, "source_backend_config", None),
        getattr(args, "expected_source_backend_config_sha256", None),
        getattr(args, "target_backend_config", None),
        getattr(args, "expected_target_backend_config_sha256", None),
    ))
    if refs == direct:
        raise ValueError(
            "select exactly one direct backend pair or portable reference pair"
        )
    if refs:
        if not all((source_ref_value, source_ref_sha,
                    target_ref_value, target_ref_sha)):
            raise ValueError("portable backend reference pair is incomplete")
        source_descriptor = _reference_file(
            source_ref_value, source_ref_sha, "source backend reference"
        )
        target_descriptor = _reference_file(
            target_ref_value, target_ref_sha, "target backend reference"
        )
        if source_descriptor["resolverId"] != target_descriptor["resolverId"]:
            raise ValueError("migration endpoint resolver identities differ")
        source = _backend_from_descriptor(
            source_descriptor, args.authority_id, args.registry_id,
            args, "source backend",
        )
        target = _backend_from_descriptor(
            target_descriptor, args.authority_id, args.registry_id,
            args, "target backend",
        )
        return source, source_descriptor, target, target_descriptor
    required = (
        getattr(args, "source_backend_config", None),
        getattr(args, "expected_source_backend_config_sha256", None),
        getattr(args, "target_backend_config", None),
        getattr(args, "expected_target_backend_config_sha256", None),
    )
    if not all(required):
        raise ValueError("direct backend configuration pair is incomplete")
    source = _backend(
        required[0], required[1], args.authority_id, args.registry_id,
        "source backend",
    )
    target = _backend(
        required[2], required[3], args.authority_id, args.registry_id,
        "target backend",
    )
    return source, source.descriptor(), target, target.descriptor()


def _chain(backend: backend_tool.ExternalCommandBackend) \
        -> list[tuple[dict[str, Any], bytes, str]]:
    current = backend.current()
    if current is None:
        return []
    token = current[0].get("fencingToken")
    digest = current[2]
    if type(token) is not int or token < 1:
        raise ValueError("backend current fencing token is malformed")
    reversed_chain: list[tuple[dict[str, Any], bytes, str]] = []
    while token >= 1:
        item = backend.grant(token, digest)
        if item[0].get("fencingToken") != token:
            raise ValueError("backend grant chain token changed")
        reversed_chain.append(item)
        previous = item[0].get("previousGrantSha256")
        if token == 1:
            if previous is not None:
                raise ValueError("backend grant chain origin is malformed")
        elif not package_tool.SHA256.fullmatch(str(previous or "")):
            raise ValueError("backend grant chain predecessor is malformed")
        digest = str(previous or "")
        token -= 1
    return list(reversed(reversed_chain))


def _chain_identity(chain: list[tuple[dict[str, Any], bytes, str]]) \
        -> list[dict[str, Any]]:
    return [
        {"fencingToken": item[0]["fencingToken"], "grantSha256": item[2]}
        for item in chain
    ]


def _chain_sha(chain: list[tuple[dict[str, Any], bytes, str]]) -> str:
    return package_tool.sha256_bytes(
        package_tool.json_bytes(_chain_identity(chain))
    )


def _exclusive_report(path_value: str, document: dict[str, Any]) -> Path:
    path = Path(path_value)
    if not path.is_absolute():
        raise ValueError("migration evidence output must be absolute")
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(package_tool.json_bytes(document))
    return path


def _validate_identity(args: argparse.Namespace) -> None:
    if any(not package_tool.IDENTIFIER.fullmatch(str(getattr(args, name, "")))
           for name in ("migration_id", "authority_id", "registry_id")):
        raise ValueError("backend migration identity is malformed")


def _transaction_path(path_value: str) -> Path:
    raw = Path(path_value)
    if not raw.is_absolute():
        raise ValueError("migration transaction path must be absolute")
    if raw.is_symlink():
        raise ValueError("migration transaction path cannot be a link")
    path = raw.resolve()
    if path.exists() and (not path.is_file() or path.is_symlink()):
        raise ValueError("migration transaction path is not a regular file")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _transaction_lease(path: Path, operation: str, actor: str) \
        -> process_lease.ProcessFileLease:
    if (not package_tool.IDENTIFIER.fullmatch(actor)
            or not package_tool.IDENTIFIER.fullmatch(operation)):
        raise ValueError("migration transaction actor or operation is malformed")
    return process_lease.ProcessFileLease(
        path.with_name(path.name + ".lock"),
        path.with_name(path.name + ".epoch.json"),
        "registry-leader-backend-migration",
        {"operation": operation, "actor": actor},
    )


def _distinct_transaction_artifact(transaction_path: Path,
                                   artifact_value: str, label: str) -> None:
    if transaction_path == Path(artifact_value).resolve():
        raise ValueError(f"migration transaction and {label} must differ")


def validate_transaction(document: Any) -> None:
    base_fields = {
        "schemaVersion", "product", "migrationId", "authorityId",
        "registryId", "sourceBackend", "targetBackend", "status",
        "stateVersion", "actor", "updatedAt",
    }
    path_fields = {
        "lastSyncEvidencePath", "lastSyncEvidenceSha256",
        "migrationEvidencePath", "migrationEvidenceSha256",
        "abortEvidencePath", "abortEvidenceSha256",
    }
    reference_fields = {
        "artifactStoreId", "lastSyncEvidenceRef",
        "migrationEvidenceRef", "abortEvidenceRef",
    }
    resolver_fields = {"backendConfigResolverId"}
    chain_fields = {"fencingToken", "previousGrantSha256"}
    if not isinstance(document, dict):
        raise ValueError("backend migration transaction is malformed")
    version = document.get("schemaVersion")
    expected_fields = base_fields | path_fields if version == 1 else \
        base_fields | path_fields | chain_fields if version == 2 else \
        base_fields | reference_fields | chain_fields if version == 3 else \
        base_fields | reference_fields | resolver_fields | chain_fields
    if (version not in {1, 2, 3, 4} or set(document) != expected_fields
            or document.get("product") != TRANSACTION_PRODUCT
            or document.get("status") not in {
                "active", "prepared", "completed", "aborted"
            }
            or type(document.get("stateVersion")) is not int
            or document["stateVersion"] < 1
            or any(not package_tool.IDENTIFIER.fullmatch(
                str(document.get(name, "")))
                for name in (
                    "migrationId", "authorityId", "registryId", "actor"
                ))):
        raise ValueError("backend migration transaction is malformed")
    if version in {2, 3, 4} and (
            document.get("fencingToken") != document["stateVersion"]
            or (document["stateVersion"] == 1
                and document.get("previousGrantSha256") is not None)
            or (document["stateVersion"] > 1
                and not package_tool.SHA256.fullmatch(
                    str(document.get("previousGrantSha256", ""))))):
        raise ValueError("backend migration transaction CAS chain is malformed")
    descriptor(document.get("sourceBackend"), "transaction source backend")
    descriptor(document.get("targetBackend"), "transaction target backend")
    if document["sourceBackend"] == document["targetBackend"]:
        raise ValueError("backend migration transaction endpoints are identical")
    if version == 4:
        resolver_id = str(document.get("backendConfigResolverId", ""))
        if (not package_tool.IDENTIFIER.fullmatch(resolver_id)
                or document["sourceBackend"].get("kind")
                    != "backend-config-ref"
                or document["targetBackend"].get("kind")
                    != "backend-config-ref"
                or document["sourceBackend"]["resolverId"] != resolver_id
                or document["targetBackend"]["resolverId"] != resolver_id):
            raise ValueError(
                "portable migration transaction resolver identity is malformed"
            )
    elif (document["sourceBackend"].get("kind") == "backend-config-ref"
          or document["targetBackend"].get("kind") == "backend-config-ref"):
        raise ValueError(
            "legacy migration transaction cannot contain portable references"
        )
    if version < 3:
        for path_name, sha_name in (
            ("lastSyncEvidencePath", "lastSyncEvidenceSha256"),
            ("migrationEvidencePath", "migrationEvidenceSha256"),
            ("abortEvidencePath", "abortEvidenceSha256"),
        ):
            path_value = document.get(path_name)
            sha_value = document.get(sha_name)
            if ((path_value is None) != (sha_value is None)
                    or (path_value is not None
                        and (not isinstance(path_value, str) or not path_value
                             or not Path(path_value).is_absolute()
                             or not package_tool.SHA256.fullmatch(
                                 str(sha_value))))):
                raise ValueError(
                    "backend migration transaction evidence is malformed"
                )
        sync_value = document["lastSyncEvidencePath"]
        migration_value = document["migrationEvidencePath"]
        abort_value = document["abortEvidencePath"]
    else:
        store_id = str(document.get("artifactStoreId", ""))
        if not package_tool.IDENTIFIER.fullmatch(store_id):
            raise ValueError("migration artifact store identity is malformed")
        for field in (
            "lastSyncEvidenceRef", "migrationEvidenceRef", "abortEvidenceRef"
        ):
            reference = document.get(field)
            if reference is not None:
                artifact_tool.validate_reference(
                    reference, store_id=store_id,
                    namespace_id=document["migrationId"],
                )
        sync_value = document["lastSyncEvidenceRef"]
        migration_value = document["migrationEvidenceRef"]
        abort_value = document["abortEvidenceRef"]
    if sync_value is None:
        raise ValueError("backend migration transaction lacks sync evidence")
    if (document["status"] in {"prepared", "completed"}
            and migration_value is None):
        raise ValueError("prepared migration transaction lacks cutover evidence")
    if (document["status"] in {"active", "aborted"}
            and migration_value is not None):
        raise ValueError("non-cutover migration transaction has cutover evidence")
    if (document["status"] == "aborted"
            and abort_value is None):
        raise ValueError("aborted migration transaction lacks abort evidence")
    if (document["status"] != "aborted"
            and abort_value is not None):
        raise ValueError("active migration transaction has abort evidence")
    package_tool.parse_time(document.get("updatedAt"), "transaction updatedAt")


def load_transaction(path_value: str, expected_sha: str | None = None) \
        -> tuple[dict[str, Any], Path, str]:
    path = _transaction_path(path_value)
    if not path.exists():
        raise ValueError("backend migration transaction does not exist")
    content = path.read_bytes()
    digest = package_tool.sha256_bytes(content)
    if expected_sha is not None and digest != str(expected_sha).lower():
        raise ValueError("backend migration transaction identity changed")
    document = json.loads(content)
    validate_transaction(document)
    return document, path, digest


def _new_transaction(sync: dict[str, Any], sync_path: Path,
                     sync_sha: str, actor: str,
                     backend_stored: bool = False,
                     artifact_store: artifact_tool.ExternalCommandArtifactStore
                     | None = None,
                     sync_reference: dict[str, Any] | None = None) \
        -> dict[str, Any]:
    portable = sync["sourceBackend"].get("kind") == "backend-config-ref"
    if portable and artifact_store is None:
        raise ValueError(
            "portable backend transactions require an Artifact Store"
        )
    version = 4 if portable else \
        3 if artifact_store is not None else 2 if backend_stored else 1
    transaction = {
        "schemaVersion": version,
        "product": TRANSACTION_PRODUCT,
        "migrationId": sync["migrationId"],
        "authorityId": sync["authorityId"],
        "registryId": sync["registryId"],
        "sourceBackend": sync["sourceBackend"],
        "targetBackend": sync["targetBackend"],
        "status": "active", "stateVersion": 1,
        "actor": actor, "updatedAt": registry_tool.utc_time(None),
    }
    if artifact_store is not None:
        if sync_reference is None or sync_reference.get("sha256") != sync_sha:
            raise ValueError("artifact sync reference identity changed")
        transaction.update({
            "artifactStoreId": artifact_store.store_id,
            "lastSyncEvidenceRef": sync_reference,
            "migrationEvidenceRef": None, "abortEvidenceRef": None,
        })
        if portable:
            resolver_id = sync["sourceBackend"]["resolverId"]
            if sync["targetBackend"].get("resolverId") != resolver_id:
                raise ValueError("migration endpoint resolver identities differ")
            transaction["backendConfigResolverId"] = resolver_id
    else:
        transaction.update({
            "lastSyncEvidencePath": str(sync_path),
            "lastSyncEvidenceSha256": sync_sha,
            "migrationEvidencePath": None, "migrationEvidenceSha256": None,
            "abortEvidencePath": None, "abortEvidenceSha256": None,
        })
    if version >= 2:
        transaction["fencingToken"] = 1
        transaction["previousGrantSha256"] = None
    validate_transaction(transaction)
    return transaction


def _advance_transaction(transaction: dict[str, Any], actor: str,
                         previous_sha256: str | None = None,
                         **updates: Any) -> dict[str, Any]:
    updated = dict(transaction)
    updated.update(updates)
    updated["stateVersion"] = transaction["stateVersion"] + 1
    if transaction["schemaVersion"] >= 2:
        if not package_tool.SHA256.fullmatch(str(previous_sha256 or "")):
            raise ValueError("backend transaction update requires predecessor SHA")
        updated["fencingToken"] = updated["stateVersion"]
        updated["previousGrantSha256"] = previous_sha256
    updated["actor"] = actor
    updated["updatedAt"] = registry_tool.utc_time(None)
    validate_transaction(updated)
    return updated


class FileTransactionStore:
    def __init__(self, path_value: str) -> None:
        self.path = _transaction_path(path_value)

    @property
    def backend_stored(self) -> bool:
        return False

    def descriptor(self) -> dict[str, Any]:
        return {"kind": "file", "path": str(self.path)}

    def read(self, expected_sha: str | None = None) \
            -> tuple[dict[str, Any], str] | None:
        if not self.path.exists():
            if expected_sha not in {None, backend_tool.ZERO_SHA256}:
                raise ValueError("backend migration transaction does not exist")
            return None
        document, _, digest = load_transaction(str(self.path), expected_sha)
        return document, digest

    def compare_and_swap(self, expected_sha: str, document: dict[str, Any],
                         operation: str, actor: str) -> str:
        validate_transaction(document)
        with _transaction_lease(self.path, operation, actor) as lease:
            current = self.read()
            current_sha = backend_tool.ZERO_SHA256 \
                if current is None else current[1]
            if current_sha != expected_sha:
                raise ValueError("backend migration transaction identity changed")
            lease.assert_current()
            package_tool.write_json(self.path, document)
            loaded = self.read()
            if loaded is None or loaded[0] != document:
                raise RuntimeError("backend migration transaction write-back changed")
            return loaded[1]


class BackendTransactionStore:
    def __init__(self, config: str, expected_config_sha256: str,
                 migration_id: str, registry_id: str) -> None:
        self.backend = _backend(
            config, expected_config_sha256, migration_id, registry_id,
            "migration transaction backend",
        )
        self.migration_id = migration_id
        self.registry_id = registry_id

    @property
    def backend_stored(self) -> bool:
        return True

    def descriptor(self) -> dict[str, Any]:
        return self.backend.descriptor()

    def read(self, expected_sha: str | None = None) \
            -> tuple[dict[str, Any], str] | None:
        loaded = self.backend.current()
        if loaded is None:
            if expected_sha not in {None, backend_tool.ZERO_SHA256}:
                raise ValueError("backend migration transaction does not exist")
            return None
        document, _, digest = loaded
        validate_transaction(document)
        if (document["schemaVersion"] not in {2, 3, 4}
                or document["migrationId"] != self.migration_id
                or document["registryId"] != self.registry_id):
            raise ValueError("migration transaction backend scope changed")
        if expected_sha is not None and digest != expected_sha:
            raise ValueError("backend migration transaction identity changed")
        return document, digest

    def compare_and_swap(self, expected_sha: str, document: dict[str, Any],
                         operation: str, actor: str) -> str:
        del operation, actor
        validate_transaction(document)
        if (document["schemaVersion"] not in {2, 3, 4}
                or document["migrationId"] != self.migration_id
                or document["registryId"] != self.registry_id):
            raise ValueError("migration transaction backend candidate changed scope")
        current = self.read()
        actual_sha = backend_tool.ZERO_SHA256 \
            if current is None else current[1]
        if actual_sha != expected_sha:
            raise ValueError("backend migration transaction identity changed")
        expected_token = 0 if current is None else current[0]["stateVersion"]
        content = package_tool.json_bytes(document)
        digest = package_tool.sha256_bytes(content)
        self.backend.compare_and_swap(
            expected_token, expected_sha, document, content, digest
        )
        loaded = self.read(digest)
        if loaded is None or loaded[0] != document:
            raise backend_tool.BackendCommitUncertainError(
                "migration transaction CAS committed but read-back changed"
            )
        return digest


TransactionStore = FileTransactionStore | BackendTransactionStore


def _artifact_store(args: argparse.Namespace, namespace_id: str,
                    required_store_id: str | None = None) \
        -> artifact_tool.ExternalCommandArtifactStore | None:
    config = getattr(args, "artifact_store_config", None)
    config_sha = getattr(args, "expected_artifact_store_config_sha256", None)
    if bool(config) != bool(config_sha):
        raise ValueError("artifact store requires config and pinned config SHA")
    if not config:
        if required_store_id is not None:
            raise ValueError(
                "content-addressed transaction requires an artifact store"
            )
        return None
    store = artifact_tool.ExternalCommandArtifactStore(
        str(config), str(config_sha), namespace_id
    )
    if required_store_id is not None and store.store_id != required_store_id:
        raise ValueError("migration artifact store identity changed")
    return store


def _transaction_artifact_store(
        args: argparse.Namespace, transaction: dict[str, Any]) \
        -> artifact_tool.ExternalCommandArtifactStore | None:
    required = transaction.get("artifactStoreId") \
        if transaction["schemaVersion"] >= 3 else None
    store = _artifact_store(args, transaction["migrationId"], required)
    if transaction["schemaVersion"] < 3 and store is not None:
        raise ValueError(
            "legacy path transaction cannot change to an artifact store"
        )
    return store


def _put_json_evidence(
        store: artifact_tool.ExternalCommandArtifactStore | None,
        path: Path) -> dict[str, Any] | None:
    if store is None:
        return None
    return store.put(path.read_bytes(), "application/json")


def _evidence_update(transaction: dict[str, Any], kind: str,
                     path: Path, digest: str,
                     reference: dict[str, Any] | None) -> dict[str, Any]:
    if transaction["schemaVersion"] >= 3:
        if reference is None or reference.get("sha256") != digest:
            raise ValueError("migration evidence reference identity changed")
        return {f"{kind}EvidenceRef": reference}
    return {
        f"{kind}EvidencePath": str(path),
        f"{kind}EvidenceSha256": digest,
    }


def _store_distinct_artifact(store: TransactionStore,
                             artifact_value: str, label: str) -> None:
    if isinstance(store, FileTransactionStore):
        _distinct_transaction_artifact(store.path, artifact_value, label)


def _transaction_store(args: argparse.Namespace) -> TransactionStore:
    path_value = getattr(args, "transaction", None)
    config_value = getattr(args, "transaction_backend_config", None)
    config_sha = getattr(
        args, "expected_transaction_backend_config_sha256", None
    )
    if bool(config_value) != bool(config_sha):
        raise ValueError(
            "transaction backend requires config and pinned config SHA"
        )
    if bool(path_value) == bool(config_value):
        raise ValueError(
            "select exactly one file transaction or transaction backend"
        )
    if path_value:
        return FileTransactionStore(path_value)
    migration_id = str(getattr(args, "migration_id", "") or "")
    registry_id = str(getattr(args, "registry_id", "") or "")
    if (not package_tool.IDENTIFIER.fullmatch(migration_id)
            or not package_tool.IDENTIFIER.fullmatch(registry_id)):
        raise ValueError(
            "transaction backend requires migration and Registry identities"
        )
    return BackendTransactionStore(
        str(config_value), str(config_sha), migration_id, registry_id
    )


def _transaction_matches_args(transaction: dict[str, Any],
                              args: argparse.Namespace) -> None:
    for attribute, field in (
        ("migration_id", "migrationId"), ("registry_id", "registryId")
    ):
        value = getattr(args, attribute, None)
        if value is not None and transaction[field] != value:
            raise ValueError("migration transaction command identity changed")


def _synchronize(args: argparse.Namespace,
                 expected_capabilities: tuple[str, str] | None = None) \
        -> dict[str, Any]:
    _validate_identity(args)
    if not args.confirm_target_migration_scope:
        raise ValueError(
            "backend migration target requires explicit scope confirmation"
        )
    if hasattr(args, "source_backend_descriptor"):
        source_descriptor = args.source_backend_descriptor
        target_descriptor = args.target_backend_descriptor
        source = _backend_from_descriptor(
            source_descriptor, args.authority_id, args.registry_id,
            args, "source backend",
        )
        target = _backend_from_descriptor(
            target_descriptor, args.authority_id, args.registry_id,
            args, "target backend",
        )
    else:
        source, source_descriptor, target, target_descriptor = \
            _backend_endpoints(args)
    if source_descriptor == target_descriptor \
            or source.backend_id == target.backend_id:
        raise ValueError("migration source and target backend must differ")
    if (expected_capabilities is not None
            and expected_capabilities != (
                source.capability_manifest_sha256,
                target.capability_manifest_sha256,
            )):
        raise ValueError(
            "migration backend capability changed since the last checkpoint"
        )
    source_before = _chain(source)
    if not source_before:
        raise ValueError("migration source backend is empty")
    target_before = _chain(target)
    if len(target_before) > len(source_before):
        raise ValueError("migration target is ahead of source")
    for index, item in enumerate(target_before):
        if item[1] != source_before[index][1] \
                or item[2] != source_before[index][2]:
            raise ValueError("migration target history diverges from source")
    for index in range(len(target_before), len(source_before)):
        grant, content, digest = source_before[index]
        previous_token = index
        previous_sha = backend_tool.ZERO_SHA256 \
            if index == 0 else source_before[index - 1][2]
        target.compare_and_swap(
            previous_token, previous_sha, grant, content, digest
        )
    source_after = _chain(source)
    target_after = _chain(target)
    if (_chain_identity(source_after) != _chain_identity(source_before)
            or len(target_after) != len(source_after)
            or any(left[1] != right[1] or left[2] != right[2]
                   for left, right in zip(source_after, target_after))):
        raise ValueError(
            "migration source changed during synchronization; rerun required"
        )
    current = source_after[-1]
    return {
        "schemaVersion": 2
            if source_descriptor["kind"] == "backend-config-ref" else 1,
        "product": SYNC_PRODUCT, "passed": True,
        "migrationId": args.migration_id,
        "authorityId": args.authority_id, "registryId": args.registry_id,
        "sourceBackend": source_descriptor,
        "targetBackend": target_descriptor,
        "sourceCapabilityManifestSha256":
            source.capability_manifest_sha256,
        "targetCapabilityManifestSha256":
            target.capability_manifest_sha256,
        "synchronizedThroughToken": current[0]["fencingToken"],
        "synchronizedGrantSha256": current[2],
        "grantCount": len(source_after),
        "grantChainSha256": _chain_sha(source_after),
        "completedAt": registry_tool.utc_time(None),
    }


def _sync_namespace(transaction: dict[str, Any], output: str,
                    confirmed: bool, args: argparse.Namespace) \
        -> argparse.Namespace:
    namespace = argparse.Namespace(
        migration_id=transaction["migrationId"],
        authority_id=transaction["authorityId"],
        registry_id=transaction["registryId"],
        source_backend_descriptor=transaction["sourceBackend"],
        target_backend_descriptor=transaction["targetBackend"],
        confirm_target_migration_scope=confirmed,
        output=output,
    )
    namespace.backend_config_resolver_config = getattr(
        args, "backend_config_resolver_config", None
    )
    namespace.expected_backend_config_resolver_config_sha256 = getattr(
        args, "expected_backend_config_resolver_config_sha256", None
    )
    return namespace


def _write_sync(report: dict[str, Any], output_value: str) \
        -> tuple[Path, str]:
    output = _exclusive_report(output_value, report)
    return output, package_tool.sha256_bytes(output.read_bytes())


def sync_command(args: argparse.Namespace) -> int:
    try:
        state_sha: str | None = None
        transaction_value = getattr(args, "transaction", None)
        transaction_backend_value = getattr(
            args, "transaction_backend_config", None
        )
        transaction_selected = bool(
            transaction_value or transaction_backend_value
        )
        actor_value = getattr(args, "actor", None)
        if transaction_selected != bool(actor_value):
            raise ValueError(
                "transactional sync requires transaction store and actor"
            )
        artifact_store = _artifact_store(args, args.migration_id)
        if artifact_store is not None and not transaction_selected:
            raise ValueError(
                "artifact-backed evidence requires a migration transaction"
            )
        if getattr(args, "source_backend_ref", None) and (
                not transaction_selected or artifact_store is None):
            raise ValueError(
                "portable backend references require a transaction and Artifact Store"
            )
        if transaction_selected:
            actor = str(actor_value)
            store = _transaction_store(args)
            _store_distinct_artifact(store, args.output, "sync evidence")
            if store.read() is not None:
                raise ValueError(
                    "migration transaction already exists; use resume"
                )
            report = _synchronize(args)
            output, output_sha = _write_sync(report, args.output)
            sync_reference = _put_json_evidence(artifact_store, output)
            transaction = _new_transaction(
                report, output, output_sha, actor, store.backend_stored,
                artifact_store, sync_reference,
            )
            state_sha = store.compare_and_swap(
                backend_tool.ZERO_SHA256, transaction, "begin", actor
            )
        else:
            report = _synchronize(args)
            output, _ = _write_sync(report, args.output)
        print(
            "PDR_REGISTRY_LEADER_BACKEND_MIGRATION_SYNC_PASS "
            f"migration={args.migration_id} grants={report['grantCount']} "
            f"token={report['synchronizedThroughToken']} output={output}"
            + (f" state-sha256={state_sha}" if state_sha else "")
        )
        return 0
    except (OSError, UnicodeError, ValueError, RuntimeError,
            json.JSONDecodeError) as error:
        print(
            f"PDR_REGISTRY_LEADER_BACKEND_MIGRATION_SYNC_ERROR: {error}",
            file=sys.stderr,
        )
        return 2


def validate_sync(document: Any) -> None:
    fields = {
        "schemaVersion", "product", "passed", "migrationId", "authorityId",
        "registryId", "sourceBackend", "targetBackend",
        "sourceCapabilityManifestSha256", "targetCapabilityManifestSha256",
        "synchronizedThroughToken", "synchronizedGrantSha256", "grantCount",
        "grantChainSha256", "completedAt",
    }
    if (not isinstance(document, dict) or set(document) != fields
            or document.get("schemaVersion") not in {1, 2}
            or document.get("product") != SYNC_PRODUCT
            or document.get("passed") is not True
            or any(not package_tool.IDENTIFIER.fullmatch(
                str(document.get(name, "")))
                for name in ("migrationId", "authorityId", "registryId"))
            or any(not package_tool.SHA256.fullmatch(
                str(document.get(name, "")))
                for name in (
                    "sourceCapabilityManifestSha256",
                    "targetCapabilityManifestSha256",
                    "synchronizedGrantSha256", "grantChainSha256",
                ))
            or type(document.get("synchronizedThroughToken")) is not int
            or document["synchronizedThroughToken"] < 1
            or type(document.get("grantCount")) is not int
            or document["grantCount"] != document["synchronizedThroughToken"]):
        raise ValueError("backend migration sync evidence is malformed")
    descriptor(document.get("sourceBackend"), "source backend")
    descriptor(document.get("targetBackend"), "target backend")
    source_kind = document["sourceBackend"].get("kind")
    target_kind = document["targetBackend"].get("kind")
    if ((document["schemaVersion"] == 1)
            != (source_kind == "external-command")
            or source_kind != target_kind):
        raise ValueError("backend migration sync descriptor version is malformed")
    package_tool.parse_time(document.get("completedAt"), "migration completedAt")


def load_sync(path_value: str, expected_sha: str) \
        -> tuple[dict[str, Any], Path, str]:
    path = package_tool.resolved_path(path_value, "backend migration sync evidence")
    content = path.read_bytes()
    document, digest = _sync_bytes(content, expected_sha)
    return document, path, digest


def _sync_bytes(content: bytes, expected_sha: str) \
        -> tuple[dict[str, Any], str]:
    digest = package_tool.sha256_bytes(content)
    if digest != str(expected_sha).lower():
        raise ValueError("backend migration sync evidence identity changed")
    document = json.loads(content)
    validate_sync(document)
    return document, digest


def _transaction_sync(
        transaction: dict[str, Any],
        artifact_store: artifact_tool.ExternalCommandArtifactStore | None = None) \
        -> dict[str, Any]:
    if transaction["schemaVersion"] >= 3:
        if artifact_store is None:
            raise ValueError("migration sync artifact store is unavailable")
        reference = transaction["lastSyncEvidenceRef"]
        sync, _ = _sync_bytes(
            artifact_store.get(reference), reference["sha256"]
        )
    else:
        sync, _, _ = load_sync(
            transaction["lastSyncEvidencePath"],
            transaction["lastSyncEvidenceSha256"],
        )
    if any(transaction[name] != sync[name]
           for name in (
               "migrationId", "authorityId", "registryId",
               "sourceBackend", "targetBackend",
           )):
        raise ValueError("migration transaction sync evidence does not match")
    return sync


def _verify_evidence_chain(
        source: backend_tool.ExternalCommandBackend,
        target: backend_tool.ExternalCommandBackend,
        expected_token: int, expected_chain_sha: str) \
        -> tuple[list[tuple[dict[str, Any], bytes, str]],
                 list[tuple[dict[str, Any], bytes, str]]]:
    source_chain = _chain(source)
    target_chain = _chain(target)
    if (len(source_chain) != expected_token
            or len(target_chain) < expected_token
            or _chain_sha(source_chain) != expected_chain_sha):
        raise ValueError("backend migration synchronized chain changed")
    for index in range(expected_token):
        if (source_chain[index][1] != target_chain[index][1]
                or source_chain[index][2] != target_chain[index][2]):
            raise ValueError("backend migration source and target history differ")
    return source_chain, target_chain


def finalize_command(args: argparse.Namespace) -> int:
    try:
        _validate_identity(args)
        transaction_selected = bool(
            getattr(args, "transaction", None)
            or getattr(args, "transaction_backend_config", None)
        )
        if transaction_selected != bool(
                getattr(args, "expected_transaction_sha256", None)
                and getattr(args, "actor", None)):
            raise ValueError(
                "transactional finalize requires store, pinned SHA and actor"
            )
        sync, sync_path, sync_sha = load_sync(
            args.sync_evidence, args.expected_sync_evidence_sha256
        )
        if sync["schemaVersion"] == 2 and not transaction_selected:
            raise ValueError(
                "portable migration finalize requires a shared transaction"
            )
        if any(sync[name] != getattr(args, name.replace("Id", "_id"), None)
               for name in ("migrationId", "authorityId", "registryId")):
            raise ValueError("backend migration sync identity does not match")
        root = registry_tool.registry_root(args.registry)
        leader_tool._outside(
            sync_path, root, "backend migration sync evidence"
        )
        leader_tool._outside(
            Path(args.output).resolve(), root, "backend migration evidence"
        )
        pointer, state = registry_tool.verified_current(root, args)
        binding, fence, fence_sha = leader_tool.verify_registry_fenced(
            root, args.leader_verification_time
        )
        source = _backend_from_descriptor(
            sync["sourceBackend"], args.authority_id, args.registry_id,
            args, "source backend",
        )
        target = _backend_from_descriptor(
            sync["targetBackend"], args.authority_id, args.registry_id,
            args, "target backend",
        )
        if (binding.get("authorityBackend") != source.descriptor()
                or source.capability_manifest_sha256
                    != sync["sourceCapabilityManifestSha256"]
                or target.capability_manifest_sha256
                    != sync["targetCapabilityManifestSha256"]):
            raise ValueError("backend migration descriptor or capability changed")
        if (fence["fencingToken"] != sync["synchronizedThroughToken"]
                or fence_sha != sync["synchronizedGrantSha256"]
                or fence["purpose"] != "fence"):
            raise ValueError("migration sync does not end at the active source fence")
        source_chain, target_chain = _verify_evidence_chain(
            source, target, fence["fencingToken"], sync["grantChainSha256"]
        )
        target_current = target.current()
        if target_current is None:
            raise ValueError("migration target leadership grant is unavailable")
        target_grant, _, target_sha = target_current
        trust_path = Path(binding["trustPolicyPath"]).resolve()
        trust, _, pinned_trust = leader_tool.load_trust_policy(
            trust_path, binding["trustPolicyId"], binding["trustPolicySha256"]
        )
        leader_tool.verify_grant(
            target_grant, trust, pinned_trust,
            args.leader_verification_time, True,
        )
        if (target_sha != str(args.expected_target_grant_sha256).lower()
                or target_grant["purpose"] != "leadership"
                or target_grant["fencingToken"] != fence["fencingToken"] + 1
                or target_grant["previousGrantSha256"] != fence_sha
                or target_grant["registryId"] != state["registryId"]
                or target_grant["authorityId"] != args.authority_id
                or target_grant["baselineRevision"] != pointer["revision"]
                or target_grant["baselineStateSha256"] != pointer["stateSha256"]):
            raise ValueError("migration target leadership does not extend the source fence")
        if len(target_chain) != target_grant["fencingToken"]:
            raise ValueError("migration target history is incomplete")
        report = {
            "schemaVersion": 2 if sync["schemaVersion"] == 2 else 1,
            "product": MIGRATION_PRODUCT, "passed": True,
            "migrationId": args.migration_id,
            "authorityId": args.authority_id, "registryId": args.registry_id,
            "sourceBackend": sync["sourceBackend"],
            "targetBackend": sync["targetBackend"],
            "sourceCapabilityManifestSha256":
                source.capability_manifest_sha256,
            "targetCapabilityManifestSha256":
                target.capability_manifest_sha256,
            "sourceFenceToken": fence["fencingToken"],
            "sourceFenceGrantSha256": fence_sha,
            "targetLeadershipToken": target_grant["fencingToken"],
            "targetLeadershipGrantSha256": target_sha,
            "leaderId": target_grant["leaderId"],
            "baselineRevision": pointer["revision"],
            "baselineStateSha256": pointer["stateSha256"],
            "grantChainSha256": _chain_sha(source_chain),
            "verifiedAt": registry_tool.utc_time(None),
        }
        if report["schemaVersion"] == 1:
            report.update({
                "syncEvidencePath": str(sync_path),
                "syncEvidenceSha256": sync_sha,
            })
        else:
            preview_store = _transaction_store(args)
            preview_loaded = preview_store.read(
                getattr(args, "expected_transaction_sha256", None)
            )
            if preview_loaded is None:
                raise ValueError("backend migration transaction does not exist")
            preview_transaction, _ = preview_loaded
            preview_artifact_store = _transaction_artifact_store(
                args, preview_transaction
            )
            if (preview_transaction["status"] != "active"
                    or any(preview_transaction[name] != report[name]
                           for name in (
                               "migrationId", "authorityId", "registryId",
                               "sourceBackend", "targetBackend",
                           ))
                    or preview_transaction["lastSyncEvidenceRef"]["sha256"]
                        != sync_sha
                    or preview_artifact_store is None
                    or preview_artifact_store.get(
                        preview_transaction["lastSyncEvidenceRef"]
                    ) != sync_path.read_bytes()):
                raise ValueError(
                    "portable migration sync does not match active transaction"
                )
            report["syncEvidenceRef"] = preview_transaction[
                "lastSyncEvidenceRef"
            ]
            validate_migration(report)
        output = _exclusive_report(args.output, report)
        output_sha = package_tool.sha256_bytes(output.read_bytes())
        if transaction_selected:
            actor = str(getattr(args, "actor", ""))
            expected_transaction_sha = getattr(
                args, "expected_transaction_sha256", None
            )
            if not expected_transaction_sha:
                raise ValueError(
                    "transactional finalize requires pinned transaction SHA"
                )
            store = _transaction_store(args)
            _store_distinct_artifact(store, args.output, "migration evidence")
            loaded = store.read(expected_transaction_sha)
            if loaded is None:
                raise ValueError("backend migration transaction does not exist")
            transaction, transaction_sha = loaded
            _transaction_matches_args(transaction, args)
            artifact_store = _transaction_artifact_store(args, transaction)
            expected_sync_sha = (
                transaction["lastSyncEvidenceRef"]["sha256"]
                if transaction["schemaVersion"] >= 3
                else transaction["lastSyncEvidenceSha256"]
            )
            if (transaction["status"] != "active"
                    or any(transaction[name] != report[name]
                           for name in (
                               "migrationId", "authorityId", "registryId",
                               "sourceBackend", "targetBackend",
                           ))
                    or expected_sync_sha != sync_sha):
                raise ValueError(
                    "migration evidence does not match active transaction"
                )
            if (artifact_store is not None
                    and artifact_store.get(
                        transaction["lastSyncEvidenceRef"]
                    ) != sync_path.read_bytes()):
                raise ValueError("migration sync artifact content changed")
            migration_reference = _put_json_evidence(artifact_store, output)
            updated = _advance_transaction(
                transaction, actor, transaction_sha, status="prepared",
                **_evidence_update(
                    transaction, "migration", output, output_sha,
                    migration_reference,
                ),
            )
            store.compare_and_swap(
                transaction_sha, updated, "finalize", actor
            )
        print(
            "PDR_REGISTRY_LEADER_BACKEND_MIGRATION_FINALIZE_PASS "
            f"migration={args.migration_id} fence={fence['fencingToken']} "
            f"target={target_grant['fencingToken']} output={output}"
        )
        return 0
    except (OSError, UnicodeError, ValueError, RuntimeError,
            json.JSONDecodeError) as error:
        print(
            f"PDR_REGISTRY_LEADER_BACKEND_MIGRATION_FINALIZE_ERROR: {error}",
            file=sys.stderr,
        )
        return 2


def validate_migration(document: Any) -> None:
    base_fields = {
        "schemaVersion", "product", "passed", "migrationId", "authorityId",
        "registryId", "sourceBackend", "targetBackend",
        "sourceCapabilityManifestSha256", "targetCapabilityManifestSha256",
        "sourceFenceToken", "sourceFenceGrantSha256",
        "targetLeadershipToken", "targetLeadershipGrantSha256", "leaderId",
        "baselineRevision", "baselineStateSha256", "grantChainSha256",
        "verifiedAt",
    }
    version = document.get("schemaVersion") if isinstance(document, dict) else None
    evidence_fields = {"syncEvidencePath", "syncEvidenceSha256"} \
        if version == 1 else {"syncEvidenceRef"}
    if (not isinstance(document, dict)
            or version not in {1, 2}
            or set(document) != base_fields | evidence_fields
            or document.get("product") != MIGRATION_PRODUCT
            or document.get("passed") is not True
            or any(not package_tool.IDENTIFIER.fullmatch(
                str(document.get(name, "")))
                for name in (
                    "migrationId", "authorityId", "registryId", "leaderId"
                ))
            or type(document.get("sourceFenceToken")) is not int
            or type(document.get("targetLeadershipToken")) is not int
            or document["sourceFenceToken"] < 1
            or document["targetLeadershipToken"]
                != document["sourceFenceToken"] + 1
            or type(document.get("baselineRevision")) is not int
            or document["baselineRevision"] < 0
            or any(not package_tool.SHA256.fullmatch(
                str(document.get(name, "")))
                for name in (
                    "sourceCapabilityManifestSha256",
                    "targetCapabilityManifestSha256",
                    "sourceFenceGrantSha256",
                    "targetLeadershipGrantSha256", "baselineStateSha256",
                    "grantChainSha256",
                ))):
        raise ValueError("backend migration evidence is malformed")
    descriptor(document.get("sourceBackend"), "source backend")
    descriptor(document.get("targetBackend"), "target backend")
    if version == 1:
        if (document["sourceBackend"].get("kind") != "external-command"
                or not isinstance(document.get("syncEvidencePath"), str)
                or not document["syncEvidencePath"]
                or not package_tool.SHA256.fullmatch(
                    str(document.get("syncEvidenceSha256", "")))):
            raise ValueError("backend migration legacy evidence is malformed")
    else:
        if (document["sourceBackend"].get("kind") != "backend-config-ref"
                or document["targetBackend"].get("kind")
                    != "backend-config-ref"):
            raise ValueError("portable backend migration evidence is malformed")
        artifact_tool.validate_reference(
            document.get("syncEvidenceRef"),
            namespace_id=document["migrationId"],
        )
    package_tool.parse_time(document.get("verifiedAt"), "migration verifiedAt")


def load_migration(path_value: str, expected_sha: str) \
        -> tuple[dict[str, Any], Path, str]:
    path = package_tool.resolved_path(path_value, "backend migration evidence")
    content = path.read_bytes()
    document, digest = _migration_bytes(content, expected_sha)
    return document, path, digest


def _migration_bytes(content: bytes, expected_sha: str) \
        -> tuple[dict[str, Any], str]:
    digest = package_tool.sha256_bytes(content)
    if digest != str(expected_sha).lower():
        raise ValueError("backend migration evidence identity changed")
    document = json.loads(content)
    validate_migration(document)
    return document, digest


def _current_summary(
        chain: list[tuple[dict[str, Any], bytes, str]]) \
        -> dict[str, Any] | None:
    if not chain:
        return None
    grant, _, digest = chain[-1]
    return {
        "fencingToken": grant["fencingToken"],
        "grantSha256": digest,
        "purpose": grant["purpose"],
        "leaderId": grant.get("leaderId"),
    }


def _common_prefix(
        left: list[tuple[dict[str, Any], bytes, str]],
        right: list[tuple[dict[str, Any], bytes, str]]) -> int:
    count = 0
    for left_item, right_item in zip(left, right):
        if left_item[1] != right_item[1] or left_item[2] != right_item[2]:
            break
        count += 1
    return count


def _live_snapshot(transaction: dict[str, Any], registry_value: str,
                   args: argparse.Namespace) \
        -> dict[str, Any]:
    root = registry_tool.registry_root(registry_value)
    binding_entry = leader_tool.read_binding(root, transaction["registryId"])
    if binding_entry is None:
        raise ValueError("Registry leader binding is unavailable")
    binding = binding_entry[0]
    if binding["authorityId"] != transaction["authorityId"]:
        raise ValueError("Registry leader authority changed during migration")
    source = _backend_from_descriptor(
        transaction["sourceBackend"], transaction["authorityId"],
        transaction["registryId"], args, "transaction source backend",
    )
    target = _backend_from_descriptor(
        transaction["targetBackend"], transaction["authorityId"],
        transaction["registryId"], args, "transaction target backend",
    )
    source_chain = _chain(source)
    target_chain = _chain(target)
    common = _common_prefix(source_chain, target_chain)
    binding_backend = binding.get("authorityBackend")
    binding_role = "other"
    if binding_backend == source.descriptor():
        binding_role = "source"
    elif binding_backend == target.descriptor():
        binding_role = "target"
    source_current = _current_summary(source_chain)
    target_current = _current_summary(target_chain)
    phase = "inconsistent"
    action = "manual-repair"
    if transaction["status"] == "aborted":
        phase, action = "aborted", "start-new-migration"
    elif common < min(len(source_chain), len(target_chain)):
        phase, action = "diverged", "manual-repair"
    elif not source_chain or binding_role == "other":
        phase, action = "inconsistent", "manual-repair"
    elif len(target_chain) == 0 and source_current["purpose"] == "leadership":
        phase, action = "ready", "resume"
    elif len(target_chain) < len(source_chain):
        if source_current["purpose"] == "fence":
            phase, action = "source-fenced-needs-resume", "resume"
        else:
            phase, action = "synchronizing", "resume"
    elif len(target_chain) == len(source_chain):
        if source_current["purpose"] == "fence":
            phase, action = "source-fenced", "issue-target-leadership"
        elif binding_role == "source":
            phase, action = "synchronized", "fence-or-abort"
        else:
            phase, action = "inconsistent", "manual-repair"
    elif (len(target_chain) == len(source_chain) + 1
          and source_current["purpose"] == "fence"
          and target_current is not None
          and target_current["purpose"] == "leadership"
          and target_chain[-1][0].get("previousGrantSha256")
              == source_current["grantSha256"]):
        if binding_role == "source":
            phase, action = "target-led", "finalize-and-activate"
        else:
            phase, action = "cutover-complete", "reconcile-completion"
    safe_to_resume = (
        transaction["status"] == "active"
        and binding_role == "source"
        and common == len(target_chain)
        and len(target_chain) <= len(source_chain)
    )
    safe_to_abort = (
        safe_to_resume and source_current is not None
        and source_current["purpose"] == "leadership"
    )
    return {
        "root": root, "binding": binding,
        "sourceChain": source_chain, "targetChain": target_chain,
        "sourceCurrent": source_current, "targetCurrent": target_current,
        "commonGrantCount": common, "bindingRole": binding_role,
        "phase": phase, "recommendedAction": action,
        "safeToResume": safe_to_resume, "safeToAbort": safe_to_abort,
    }


def _status_report(transaction: dict[str, Any],
                   transaction_store: dict[str, Any],
                   transaction_sha: str, live: dict[str, Any],
                   artifact_store: artifact_tool.ExternalCommandArtifactStore
                   | None = None,
                   args: argparse.Namespace | None = None) \
        -> dict[str, Any]:
    passed = live["phase"] not in {"diverged", "inconsistent"}
    report = {
        "schemaVersion": 2, "product": STATUS_PRODUCT, "passed": passed,
        "migrationId": transaction["migrationId"],
        "authorityId": transaction["authorityId"],
        "registryId": transaction["registryId"],
        "transactionStore": transaction_store,
        "transactionSha256": transaction_sha,
        "transactionStatus": transaction["status"],
        "stateVersion": transaction["stateVersion"],
        "sourceBackend": transaction["sourceBackend"],
        "targetBackend": transaction["targetBackend"],
        "sourceGrantCount": len(live["sourceChain"]),
        "targetGrantCount": len(live["targetChain"]),
        "commonGrantCount": live["commonGrantCount"],
        "sourceCurrent": live["sourceCurrent"],
        "targetCurrent": live["targetCurrent"],
        "bindingRole": live["bindingRole"],
        "phase": live["phase"],
        "recommendedAction": live["recommendedAction"],
        "safeToResume": live["safeToResume"],
        "safeToAbort": live["safeToAbort"],
        "verifiedAt": registry_tool.utc_time(None),
    }
    if transaction["schemaVersion"] >= 3:
        if artifact_store is None:
            raise ValueError("migration status artifact store is unavailable")
        report.update({
            "schemaVersion": 3,
            "artifactStore": artifact_store.descriptor(),
            "lastSyncEvidenceRef": transaction["lastSyncEvidenceRef"],
            "migrationEvidenceRef": transaction["migrationEvidenceRef"],
            "abortEvidenceRef": transaction["abortEvidenceRef"],
        })
    if transaction["schemaVersion"] == 4:
        if args is None:
            raise ValueError("migration status resolver context is unavailable")
        resolver = _config_resolver(args, required=True)
        assert resolver is not None
        if resolver.resolver_id != transaction["backendConfigResolverId"]:
            raise ValueError("migration backend config resolver identity changed")
        report.update({
            "schemaVersion": 4,
            "backendConfigResolver": resolver.descriptor(),
        })
    return report


def status_command(args: argparse.Namespace) -> int:
    try:
        store = _transaction_store(args)
        loaded = store.read()
        if loaded is None:
            raise ValueError("backend migration transaction does not exist")
        transaction, digest = loaded
        _transaction_matches_args(transaction, args)
        artifact_store = _transaction_artifact_store(args, transaction)
        _transaction_sync(transaction, artifact_store)
        live = _live_snapshot(transaction, args.registry, args)
        final = store.read()
        if final is None or final[1] != digest:
            raise ValueError("migration transaction changed during status read")
        report = _status_report(
            transaction, store.descriptor(), digest, live, artifact_store, args
        )
        if args.report:
            package_tool.write_json(Path(args.report).resolve(), report)
        print(
            "PDR_REGISTRY_LEADER_BACKEND_MIGRATION_STATUS_"
            f"{'PASS' if report['passed'] else 'ERROR'} "
            f"migration={transaction['migrationId']} phase={live['phase']} "
            f"state-sha256={digest}"
        )
        return 0 if report["passed"] else 2
    except (OSError, UnicodeError, ValueError, RuntimeError,
            json.JSONDecodeError) as error:
        print(
            f"PDR_REGISTRY_LEADER_BACKEND_MIGRATION_STATUS_ERROR: {error}",
            file=sys.stderr,
        )
        return 2


def resume_command(args: argparse.Namespace) -> int:
    try:
        store = _transaction_store(args)
        _store_distinct_artifact(store, args.output, "sync evidence")
        loaded = store.read(args.expected_transaction_sha256)
        if loaded is None:
            raise ValueError("backend migration transaction does not exist")
        transaction, transaction_sha = loaded
        _transaction_matches_args(transaction, args)
        artifact_store = _transaction_artifact_store(args, transaction)
        if transaction["status"] != "active":
            raise ValueError(
                "only an active migration transaction can resume"
            )
        previous_sync = _transaction_sync(transaction, artifact_store)
        sync_args = _sync_namespace(
            transaction, args.output,
            args.confirm_target_migration_scope,
            args,
        )
        report = _synchronize(
            sync_args,
            (
                previous_sync["sourceCapabilityManifestSha256"],
                previous_sync["targetCapabilityManifestSha256"],
            ),
        )
        output, output_sha = _write_sync(report, args.output)
        sync_reference = _put_json_evidence(artifact_store, output)
        updated = _advance_transaction(
            transaction, args.actor, transaction_sha,
            **_evidence_update(
                transaction, "lastSync", output, output_sha, sync_reference
            ),
        )
        state_sha = store.compare_and_swap(
            transaction_sha, updated, "resume", args.actor
        )
        print(
            "PDR_REGISTRY_LEADER_BACKEND_MIGRATION_RESUME_PASS "
            f"migration={transaction['migrationId']} "
            f"token={report['synchronizedThroughToken']} "
            f"state-sha256={state_sha}"
        )
        return 0
    except (OSError, UnicodeError, ValueError, RuntimeError,
            json.JSONDecodeError) as error:
        print(
            f"PDR_REGISTRY_LEADER_BACKEND_MIGRATION_RESUME_ERROR: {error}",
            file=sys.stderr,
        )
        return 2


def _verify_sync_checkpoint(sync: dict[str, Any], args: argparse.Namespace) -> None:
    source = _backend_from_descriptor(
        sync["sourceBackend"], sync["authorityId"], sync["registryId"],
        args, "source backend",
    )
    target = _backend_from_descriptor(
        sync["targetBackend"], sync["authorityId"], sync["registryId"],
        args, "target backend",
    )
    if (source.capability_manifest_sha256
            != sync["sourceCapabilityManifestSha256"]
            or target.capability_manifest_sha256
            != sync["targetCapabilityManifestSha256"]):
        raise ValueError("migration sync capability checkpoint changed")
    source_chain = _chain(source)
    target_chain = _chain(target)
    token = sync["synchronizedThroughToken"]
    common = _common_prefix(source_chain, target_chain)
    if (len(source_chain) < token or len(target_chain) < token
            or common < token
            or _chain_sha(source_chain[:token]) != sync["grantChainSha256"]
            or source_chain[token - 1][2]
                != sync["synchronizedGrantSha256"]):
        raise ValueError("migration sync checkpoint no longer matches live history")


def reconcile_command(args: argparse.Namespace) -> int:
    try:
        if bool(args.sync_evidence) == bool(args.migration_evidence):
            raise ValueError(
                "reconcile requires exactly one sync or migration evidence"
            )
        if args.sync_evidence and not args.expected_sync_evidence_sha256:
            raise ValueError("sync reconciliation requires pinned evidence SHA")
        if args.migration_evidence and (
                not args.expected_migration_evidence_sha256
                or not args.expected_transaction_sha256
                or not args.registry):
            raise ValueError(
                "completion reconciliation requires Registry and pinned evidence"
            )
        if args.migration_evidence:
            migration, migration_path, migration_sha = load_migration(
                args.migration_evidence,
                args.expected_migration_evidence_sha256,
            )
            store = _transaction_store(args)
            _store_distinct_artifact(
                store, args.migration_evidence, "migration evidence"
            )
            loaded = store.read(args.expected_transaction_sha256)
            if loaded is None:
                raise ValueError("backend migration transaction does not exist")
            transaction, transaction_sha = loaded
            _transaction_matches_args(transaction, args)
            artifact_store = _transaction_artifact_store(args, transaction)
            expected_migration_sha = (
                transaction["migrationEvidenceRef"]["sha256"]
                if transaction["schemaVersion"] >= 3
                else transaction["migrationEvidenceSha256"]
            )
            if (transaction["status"] != "prepared"
                    or any(transaction[name] != migration[name]
                           for name in (
                               "migrationId", "authorityId", "registryId",
                               "sourceBackend", "targetBackend",
                           ))
                    or expected_migration_sha != migration_sha):
                raise ValueError(
                    "cutover evidence does not match prepared transaction"
                )
            if (artifact_store is not None
                    and artifact_store.get(
                        transaction["migrationEvidenceRef"]
                    ) != migration_path.read_bytes()):
                raise ValueError("cutover artifact content changed")
            root = registry_tool.registry_root(args.registry)
            with registry_tool.RegistryLease(
                    root, "leader-backend-migration-reconcile",
                    args.actor) as registry_lease:
                live = _live_snapshot(transaction, args.registry, args)
                if (live["phase"] != "cutover-complete"
                        or live["binding"].get(
                            "backendMigrationEvidenceSha256"
                        ) != migration_sha):
                    raise ValueError(
                        "Registry binding has not completed this migration"
                    )
                updates: dict[str, Any] = {"status": "completed"}
                if transaction["schemaVersion"] < 3:
                    updates.update({
                        "migrationEvidencePath": str(migration_path),
                        "migrationEvidenceSha256": migration_sha,
                    })
                updated = _advance_transaction(
                    transaction, args.actor, transaction_sha, **updates
                )
                registry_lease.assert_current()
                state_sha = store.compare_and_swap(
                    transaction_sha, updated, "reconcile", args.actor
                )
            print(
                "PDR_REGISTRY_LEADER_BACKEND_MIGRATION_RECONCILE_PASS "
                f"migration={migration['migrationId']} completed=1 "
                f"state-sha256={state_sha}"
            )
            return 0
        sync, sync_path, sync_sha = load_sync(
            args.sync_evidence, args.expected_sync_evidence_sha256
        )
        store = _transaction_store(args)
        _store_distinct_artifact(store, args.sync_evidence, "sync evidence")
        _verify_sync_checkpoint(sync, args)
        current = store.read()
        if current is not None:
            if not args.expected_transaction_sha256:
                raise ValueError(
                    "existing transaction reconciliation requires pinned SHA"
                )
            transaction, transaction_sha = current
            if transaction_sha != args.expected_transaction_sha256:
                raise ValueError("backend migration transaction identity changed")
            _transaction_matches_args(transaction, args)
            artifact_store = _transaction_artifact_store(args, transaction)
            if (transaction["status"] != "active"
                    or any(transaction[name] != sync[name]
                           for name in (
                               "migrationId", "authorityId", "registryId",
                               "sourceBackend", "targetBackend",
                           ))):
                raise ValueError(
                    "sync evidence does not match active transaction"
                )
            sync_reference = _put_json_evidence(artifact_store, sync_path)
            updated = _advance_transaction(
                transaction, args.actor, transaction_sha,
                **_evidence_update(
                    transaction, "lastSync", sync_path, sync_sha,
                    sync_reference,
                ),
            )
            expected_sha = transaction_sha
        else:
            if (args.expected_transaction_sha256
                    or not args.confirm_adopt_orphaned_sync):
                raise ValueError(
                    "orphaned sync adoption requires explicit confirmation"
                )
            if any(getattr(args, attribute, None) is not None
                   and sync[field] != getattr(args, attribute)
                   for field, attribute in (
                       ("migrationId", "migration_id"),
                       ("registryId", "registry_id"),
                   )):
                raise ValueError("orphaned sync command identity changed")
            artifact_store = _artifact_store(args, sync["migrationId"])
            sync_reference = _put_json_evidence(artifact_store, sync_path)
            updated = _new_transaction(
                sync, sync_path, sync_sha, args.actor,
                store.backend_stored, artifact_store, sync_reference,
            )
            expected_sha = backend_tool.ZERO_SHA256
        state_sha = store.compare_and_swap(
            expected_sha, updated, "reconcile", args.actor
        )
        print(
            "PDR_REGISTRY_LEADER_BACKEND_MIGRATION_RECONCILE_PASS "
            f"migration={sync['migrationId']} token="
            f"{sync['synchronizedThroughToken']} state-sha256={state_sha}"
        )
        return 0
    except (OSError, UnicodeError, ValueError, RuntimeError,
            json.JSONDecodeError) as error:
        print(
            f"PDR_REGISTRY_LEADER_BACKEND_MIGRATION_RECONCILE_ERROR: {error}",
            file=sys.stderr,
        )
        return 2


def validate_abort(document: Any) -> None:
    fields = {
        "schemaVersion", "product", "passed", "migrationId",
        "authorityId", "registryId", "transactionStore",
        "transactionSha256", "sourceBackend", "targetBackend",
        "sourceCurrent", "targetCurrent", "bindingGrantSha256",
        "retainedTargetHistory", "operator", "reason", "abortedAt",
    }
    if (not isinstance(document, dict) or set(document) != fields
            or document.get("schemaVersion") not in {2, 3}
            or document.get("product") != ABORT_PRODUCT
            or document.get("passed") is not True
            or document.get("retainedTargetHistory") is not True
            or any(not package_tool.IDENTIFIER.fullmatch(
                str(document.get(name, "")))
                for name in (
                    "migrationId", "authorityId", "registryId", "operator"
                ))
            or not package_tool.SHA256.fullmatch(
                str(document.get("transactionSha256", "")))
            or not package_tool.SHA256.fullmatch(
                str(document.get("bindingGrantSha256", "")))
            or not isinstance(document.get("reason"), str)
            or not document["reason"].strip()):
        raise ValueError("backend migration abort evidence is malformed")
    descriptor(document.get("sourceBackend"), "abort source backend")
    descriptor(document.get("targetBackend"), "abort target backend")
    expected_kind = "backend-config-ref" \
        if document["schemaVersion"] == 3 else "external-command"
    if (document["sourceBackend"].get("kind") != expected_kind
            or document["targetBackend"].get("kind") != expected_kind):
        raise ValueError("backend migration abort descriptor version is malformed")
    transaction_store_descriptor(document.get("transactionStore"))
    if (not isinstance(document.get("sourceCurrent"), dict)
            or document["sourceCurrent"].get("purpose") != "leadership"):
        raise ValueError("backend migration abort source is not writable")
    package_tool.parse_time(document.get("abortedAt"), "abort abortedAt")


def abort_command(args: argparse.Namespace) -> int:
    try:
        store = _transaction_store(args)
        _store_distinct_artifact(store, args.output, "abort evidence")
        loaded = store.read(args.expected_transaction_sha256)
        if loaded is None:
            raise ValueError("backend migration transaction does not exist")
        transaction, transaction_sha = loaded
        _transaction_matches_args(transaction, args)
        artifact_store = _transaction_artifact_store(args, transaction)
        if transaction["status"] != "active":
            raise ValueError("only an active migration transaction can abort")
        root = registry_tool.registry_root(args.registry)
        with registry_tool.RegistryLease(
                root, "leader-backend-migration-abort",
                args.operator) as registry_lease:
            live = _live_snapshot(transaction, args.registry, args)
            if not live["safeToAbort"]:
                raise ValueError(
                    "migration cannot abort after fencing, divergence or cutover"
                )
            output_path = Path(args.output).resolve()
            leader_tool._outside(
                output_path, live["root"],
                "backend migration abort evidence"
            )
            report = {
                "schemaVersion": 3
                    if transaction["schemaVersion"] == 4 else 2,
                "product": ABORT_PRODUCT,
                "passed": True,
                "migrationId": transaction["migrationId"],
                "authorityId": transaction["authorityId"],
                "registryId": transaction["registryId"],
                "transactionStore": store.descriptor(),
                "transactionSha256": transaction_sha,
                "sourceBackend": transaction["sourceBackend"],
                "targetBackend": transaction["targetBackend"],
                "sourceCurrent": live["sourceCurrent"],
                "targetCurrent": live["targetCurrent"],
                "bindingGrantSha256": live["binding"]["grantSha256"],
                "retainedTargetHistory": True,
                "operator": args.operator, "reason": args.reason,
                "abortedAt": registry_tool.utc_time(None),
            }
            validate_abort(report)
            output = _exclusive_report(args.output, report)
            output_sha = package_tool.sha256_bytes(output.read_bytes())
            abort_reference = _put_json_evidence(artifact_store, output)
            updated = _advance_transaction(
                transaction, args.operator, transaction_sha,
                status="aborted", **_evidence_update(
                    transaction, "abort", output, output_sha, abort_reference
                ),
            )
            registry_lease.assert_current()
            store.compare_and_swap(
                transaction_sha, updated, "abort", args.operator
            )
        print(
            "PDR_REGISTRY_LEADER_BACKEND_MIGRATION_ABORT_PASS "
            f"migration={transaction['migrationId']} retained-target-history=1"
        )
        return 0
    except (OSError, UnicodeError, ValueError, RuntimeError,
            json.JSONDecodeError) as error:
        print(
            f"PDR_REGISTRY_LEADER_BACKEND_MIGRATION_ABORT_ERROR: {error}",
            file=sys.stderr,
        )
        return 2


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)

    def store_arguments(command: argparse.ArgumentParser,
                        add_identity: bool = False) -> None:
        command.add_argument("--transaction")
        command.add_argument("--transaction-backend-config")
        command.add_argument(
            "--expected-transaction-backend-config-sha256"
        )
        command.add_argument("--artifact-store-config")
        command.add_argument("--expected-artifact-store-config-sha256")
        command.add_argument("--backend-config-resolver-config")
        command.add_argument(
            "--expected-backend-config-resolver-config-sha256"
        )
        if add_identity:
            command.add_argument("--migration-id")
            command.add_argument("--registry-id")

    sync = commands.add_parser("sync")
    sync.add_argument("--migration-id", required=True)
    sync.add_argument("--authority-id", required=True)
    sync.add_argument("--registry-id", required=True)
    sync.add_argument("--source-backend-config")
    sync.add_argument("--expected-source-backend-config-sha256")
    sync.add_argument("--target-backend-config")
    sync.add_argument("--expected-target-backend-config-sha256")
    sync.add_argument("--source-backend-ref")
    sync.add_argument("--expected-source-backend-ref-sha256")
    sync.add_argument("--target-backend-ref")
    sync.add_argument("--expected-target-backend-ref-sha256")
    sync.add_argument("--confirm-target-migration-scope", action="store_true")
    store_arguments(sync)
    sync.add_argument("--actor")
    sync.add_argument("--output", required=True)
    sync.set_defaults(handler=sync_command)
    finalize = commands.add_parser("finalize")
    finalize.add_argument("--migration-id", required=True)
    finalize.add_argument("--registry", required=True)
    finalize.add_argument("--authority-id", required=True)
    finalize.add_argument("--registry-id", required=True)
    finalize.add_argument("--sync-evidence", required=True)
    finalize.add_argument("--expected-sync-evidence-sha256", required=True)
    finalize.add_argument("--expected-target-grant-sha256", required=True)
    finalize.add_argument("--leader-verification-time")
    finalize.add_argument("--trust-policy", required=True)
    finalize.add_argument("--expected-trust-policy-id", required=True)
    finalize.add_argument("--expected-trust-policy-sha256", required=True)
    finalize.add_argument("--verification-time")
    finalize.add_argument("--maximum-files", type=int, default=64)
    finalize.add_argument("--maximum-expanded-bytes", type=int,
                          default=16 * 1024 * 1024)
    store_arguments(finalize)
    finalize.add_argument("--expected-transaction-sha256")
    finalize.add_argument("--actor")
    finalize.add_argument("--output", required=True)
    finalize.set_defaults(handler=finalize_command)
    status = commands.add_parser("status")
    store_arguments(status, True)
    status.add_argument("--registry", required=True)
    status.add_argument("--report")
    status.set_defaults(handler=status_command)
    resume = commands.add_parser("resume")
    store_arguments(resume, True)
    resume.add_argument("--expected-transaction-sha256", required=True)
    resume.add_argument("--actor", required=True)
    resume.add_argument("--confirm-target-migration-scope", action="store_true")
    resume.add_argument("--output", required=True)
    resume.set_defaults(handler=resume_command)
    reconcile = commands.add_parser("reconcile")
    store_arguments(reconcile, True)
    reconcile.add_argument("--expected-transaction-sha256")
    reconcile.add_argument("--actor", required=True)
    reconcile.add_argument("--sync-evidence")
    reconcile.add_argument("--expected-sync-evidence-sha256")
    reconcile.add_argument("--migration-evidence")
    reconcile.add_argument("--expected-migration-evidence-sha256")
    reconcile.add_argument("--registry")
    reconcile.add_argument(
        "--confirm-adopt-orphaned-sync", action="store_true"
    )
    reconcile.set_defaults(handler=reconcile_command)
    abort = commands.add_parser("abort")
    store_arguments(abort, True)
    abort.add_argument("--expected-transaction-sha256", required=True)
    abort.add_argument("--registry", required=True)
    abort.add_argument("--operator", required=True)
    abort.add_argument("--reason", required=True)
    abort.add_argument("--output", required=True)
    abort.set_defaults(handler=abort_command)
    return result


def main() -> int:
    args = parser().parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
