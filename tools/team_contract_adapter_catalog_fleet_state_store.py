#!/usr/bin/env python3
"""CAS-fenced remote journal storage for Adapter Catalog Fleet coordinators."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import team_contract_artifact_store as artifact_store_tool
import team_contract_adapter_config_resolver as adapter_config_resolver_tool
import team_contract_package as package_tool
import team_contract_registry as registry_tool
import team_contract_registry_leader_backend as backend_tool


POINTER_PRODUCT = "PocoDDSRuntimeTeamContractAdapterCatalogFleetStatePointer"
POINTER_SCHEMA_VERSION = 2
JOURNAL_MEDIA_TYPE = "application/json"


def _journal_digest(document: dict[str, Any]) -> str:
    return package_tool.sha256_bytes(package_tool.json_bytes({
        key: value for key, value in document.items()
        if key != "journalSha256"
    }))


def validate_pointer(document: Any) -> None:
    base_fields = {
        "schemaVersion", "product", "rolloutId", "catalogId",
        "planSha256", "stateBackendId", "artifactStoreId", "stateVersion",
        "fencingToken", "previousGrantSha256", "journalRef",
        "journalSha256", "coordinatorId", "updatedAt",
    }
    version = document.get("schemaVersion") if isinstance(document, dict) \
        else None
    fields = base_fields | (
        {"stateBackendConfigSha256", "artifactStoreConfigSha256"}
        if version == 1 else {
            "adapterConfigResolverId", "stateBackendConfigRef",
            "artifactStoreConfigRef",
        } if version == 2 else set()
    )
    if (not isinstance(document, dict) or set(document) != fields
            or version not in {1, 2}
            or document.get("product") != POINTER_PRODUCT
            or any(package_tool.IDENTIFIER.fullmatch(
                str(document.get(name, ""))) is None
                for name in (
                    "rolloutId", "catalogId", "stateBackendId",
                    "artifactStoreId", "coordinatorId",
                ))
            or any(package_tool.SHA256.fullmatch(str(
                document.get(name, ""))) is None
                for name in ("planSha256", "journalSha256"))
            or type(document.get("stateVersion")) is not int
            or document["stateVersion"] < 1
            or document.get("fencingToken") != document["stateVersion"]
            or (document["stateVersion"] == 1
                and document.get("previousGrantSha256") is not None)
            or (document["stateVersion"] > 1
                and package_tool.SHA256.fullmatch(str(
                    document.get("previousGrantSha256", ""))) is None)):
        raise ValueError("Adapter Catalog Fleet state pointer is malformed")
    if version == 1 and any(package_tool.SHA256.fullmatch(str(
            document.get(name, ""))) is None for name in (
                "stateBackendConfigSha256", "artifactStoreConfigSha256"
            )):
        raise ValueError("Fleet state pointer config pins are malformed")
    if version == 2:
        resolver_id = str(document.get("adapterConfigResolverId", ""))
        if package_tool.IDENTIFIER.fullmatch(resolver_id) is None:
            raise ValueError("Fleet state pointer Resolver identity is malformed")
        backend_ref = adapter_config_resolver_tool.validate_reference(
            document.get("stateBackendConfigRef"), resolver_id=resolver_id,
            adapter_kind="registry-leader-backend",
        )
        artifact_ref = adapter_config_resolver_tool.validate_reference(
            document.get("artifactStoreConfigRef"), resolver_id=resolver_id,
            adapter_kind="artifact-store",
        )
        if (backend_ref["adapterId"] != document["stateBackendId"]
                or artifact_ref["adapterId"] != document["artifactStoreId"]):
            raise ValueError("Fleet state pointer Adapter identity changed")
    package_tool.parse_time(
        document.get("updatedAt"), "Fleet state pointer updatedAt"
    )
    artifact_store_tool.validate_reference(
        document["journalRef"], store_id=document["artifactStoreId"],
        namespace_id=document["rolloutId"],
    )
    if document["journalRef"]["mediaType"] != JOURNAL_MEDIA_TYPE:
        raise ValueError("Fleet state pointer journal identity changed")


class RemoteFleetStateStore:
    """Publishes immutable Fleet journals behind one linearizable CAS pointer."""

    def __init__(
            self, *, state_backend_config: str | Path,
            state_backend_config_sha256: str,
            artifact_store_config: str | Path,
            artifact_store_config_sha256: str,
            rollout_id: str, catalog_id: str, plan_sha256: str,
            expected_backend_id: str, expected_artifact_store_id: str,
            coordinator_id: str | None,
            adapter_config_resolver_id: str | None = None,
            state_backend_config_ref: dict[str, Any] | None = None,
            artifact_store_config_ref: dict[str, Any] | None = None) -> None:
        if (coordinator_id is not None
                and package_tool.IDENTIFIER.fullmatch(coordinator_id) is None):
            raise ValueError("Fleet coordinator ID is malformed")
        self.backend = backend_tool.ExternalCommandBackend(
            state_backend_config, state_backend_config_sha256,
            rollout_id, catalog_id,
        )
        self.artifact_store = artifact_store_tool.ExternalCommandArtifactStore(
            artifact_store_config, artifact_store_config_sha256, rollout_id
        )
        if self.backend.backend_id != expected_backend_id:
            raise ValueError("Fleet state Backend identity changed")
        if self.artifact_store.store_id != expected_artifact_store_id:
            raise ValueError("Fleet state Artifact Store identity changed")
        if self.backend.capability_manifest_sha256 is None:
            raise ValueError("Fleet state Backend lacks capability negotiation")
        self.rollout_id = rollout_id
        self.catalog_id = catalog_id
        self.plan_sha256 = plan_sha256
        self.coordinator_id = coordinator_id
        self.backend_config_sha256 = state_backend_config_sha256
        self.artifact_store_config_sha256 = artifact_store_config_sha256
        portable_values = (
            adapter_config_resolver_id, state_backend_config_ref,
            artifact_store_config_ref,
        )
        if any(value is not None for value in portable_values) \
                and any(value is None for value in portable_values):
            raise ValueError("Fleet portable state identity is incomplete")
        self.adapter_config_resolver_id = adapter_config_resolver_id
        self.state_backend_config_ref = state_backend_config_ref
        self.artifact_store_config_ref = artifact_store_config_ref
        self.portable = adapter_config_resolver_id is not None
        if self.portable:
            assert adapter_config_resolver_id is not None
            assert state_backend_config_ref is not None
            assert artifact_store_config_ref is not None
            adapter_config_resolver_tool.validate_reference(
                state_backend_config_ref,
                resolver_id=adapter_config_resolver_id,
                adapter_kind="registry-leader-backend",
            )
            adapter_config_resolver_tool.validate_reference(
                artifact_store_config_ref,
                resolver_id=adapter_config_resolver_id,
                adapter_kind="artifact-store",
            )
        self._token = 0
        self._pointer_sha256 = backend_tool.ZERO_SHA256
        self._journal_sha256: str | None = None

    @property
    def state_version(self) -> int:
        return self._token

    @property
    def backend_capability_manifest_sha256(self) -> str:
        value = self.backend.capability_manifest_sha256
        assert value is not None
        return value

    @property
    def artifact_store_capability_manifest_sha256(self) -> str:
        return self.artifact_store.capability_manifest_sha256

    def _validate_scope(self, pointer: dict[str, Any]) -> None:
        changed = (pointer["rolloutId"] != self.rollout_id
                or pointer["catalogId"] != self.catalog_id
                or pointer["planSha256"] != self.plan_sha256
                or pointer["stateBackendId"] != self.backend.backend_id
                or pointer["artifactStoreId"]
                    != self.artifact_store.store_id)
        if self.portable:
            changed = changed or (
                pointer["schemaVersion"] != 2
                or pointer["adapterConfigResolverId"]
                    != self.adapter_config_resolver_id
                or pointer["stateBackendConfigRef"]
                    != self.state_backend_config_ref
                or pointer["artifactStoreConfigRef"]
                    != self.artifact_store_config_ref
            )
        else:
            changed = changed or (
                pointer["schemaVersion"] != 1
                or pointer["stateBackendConfigSha256"]
                    != self.backend_config_sha256
                or pointer["artifactStoreConfigSha256"]
                    != self.artifact_store_config_sha256
            )
        if changed:
            raise ValueError("Adapter Catalog Fleet state pointer scope changed")

    def _journal_scope_changed(self, journal: dict[str, Any]) -> bool:
        changed = (
            journal.get("rolloutId") != self.rollout_id
            or journal.get("catalogId") != self.catalog_id
            or journal.get("planSha256") != self.plan_sha256
        )
        if self.portable:
            return changed or (
                journal.get("adapterConfigResolverId")
                    != self.adapter_config_resolver_id
                or journal.get("stateBackendConfigRef")
                    != self.state_backend_config_ref
                or journal.get("artifactStoreConfigRef")
                    != self.artifact_store_config_ref
            )
        return changed or (
            journal.get("stateBackendConfigSha256")
                != self.backend_config_sha256
            or journal.get("artifactStoreConfigSha256")
                != self.artifact_store_config_sha256
        )

    def read(self) -> dict[str, Any] | None:
        loaded = self.backend.current()
        if loaded is None:
            self._token = 0
            self._pointer_sha256 = backend_tool.ZERO_SHA256
            self._journal_sha256 = None
            return None
        pointer, _, pointer_sha256 = loaded
        validate_pointer(pointer)
        self._validate_scope(pointer)
        content = self.artifact_store.get(pointer["journalRef"])
        try:
            journal = json.loads(content)
        except (UnicodeError, json.JSONDecodeError) as error:
            raise ValueError("Fleet remote journal is invalid JSON") from error
        if (not isinstance(journal, dict)
                or journal.get("stateVersion") != pointer["stateVersion"]
                or journal.get("journalSha256") != pointer["journalSha256"]
                or self._journal_scope_changed(journal)
                or _journal_digest(journal) != pointer["journalSha256"]):
            raise ValueError("Fleet remote journal identity changed")
        self._token = pointer["stateVersion"]
        self._pointer_sha256 = pointer_sha256
        self._journal_sha256 = pointer["journalSha256"]
        return journal

    def write(self, journal: dict[str, Any]) -> None:
        if self.coordinator_id is None:
            raise ValueError("Fleet coordinator ID is required for state changes")
        if (not isinstance(journal, dict)
                or self._journal_scope_changed(journal)):
            raise ValueError("Fleet remote journal scope changed")
        next_token = self._token + 1
        journal["stateVersion"] = next_token
        journal["previousJournalSha256"] = self._journal_sha256
        journal["lastCoordinatorId"] = self.coordinator_id
        journal["updatedAt"] = registry_tool.utc_time(None)
        journal["journalSha256"] = _journal_digest(journal)
        content = package_tool.json_bytes(journal)
        reference = self.artifact_store.put(content, JOURNAL_MEDIA_TYPE)
        pointer = {
            "schemaVersion": 2 if self.portable else 1,
            "product": POINTER_PRODUCT,
            "rolloutId": self.rollout_id,
            "catalogId": self.catalog_id,
            "planSha256": self.plan_sha256,
            "stateBackendId": self.backend.backend_id,
            "artifactStoreId": self.artifact_store.store_id,
            "stateVersion": next_token,
            "fencingToken": next_token,
            "previousGrantSha256": (
                None if self._token == 0 else self._pointer_sha256
            ),
            "journalRef": reference,
            "journalSha256": journal["journalSha256"],
            "coordinatorId": self.coordinator_id,
            "updatedAt": journal["updatedAt"],
        }
        if self.portable:
            pointer.update({
                "adapterConfigResolverId": self.adapter_config_resolver_id,
                "stateBackendConfigRef": self.state_backend_config_ref,
                "artifactStoreConfigRef": self.artifact_store_config_ref,
            })
        else:
            pointer.update({
                "stateBackendConfigSha256": self.backend_config_sha256,
                "artifactStoreConfigSha256":
                    self.artifact_store_config_sha256,
            })
        validate_pointer(pointer)
        pointer_content = package_tool.json_bytes(pointer)
        pointer_sha256 = package_tool.sha256_bytes(pointer_content)
        try:
            self.backend.compare_and_swap(
                self._token, self._pointer_sha256, pointer,
                pointer_content, pointer_sha256,
            )
        except backend_tool.BackendCommitUncertainError:
            current = self.backend.current()
            if current is None:
                raise
            current_pointer, _, current_sha256 = current
            validate_pointer(current_pointer)
            self._validate_scope(current_pointer)
            if (current_pointer["stateVersion"] != next_token
                    or current_pointer["journalSha256"]
                        != journal["journalSha256"]
                    or current_pointer["coordinatorId"]
                        != self.coordinator_id):
                raise
            pointer_sha256 = current_sha256
        self._token = next_token
        self._pointer_sha256 = pointer_sha256
        self._journal_sha256 = journal["journalSha256"]


def parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        description=(
            "Fleet remote state SPI library; use pdr.py contract-package "
            "adapter-catalog-fleet-status to inspect a rollout"
        )
    )


def main() -> int:
    parser().parse_args()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
