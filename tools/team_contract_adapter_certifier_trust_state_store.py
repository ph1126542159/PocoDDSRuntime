#!/usr/bin/env python3
"""CAS-fenced remote state for governed Adapter certifier trust policies."""

from __future__ import annotations

import argparse
import base64
import json
import sys
import tempfile
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any

import team_contract_adapter_certifier_trust_control as control_tool
import team_contract_adapter_conformance_trust as trust_tool
import team_contract_adapter_config_resolver as resolver_tool
import team_contract_adapter_runtime as adapter_runtime
import team_contract_artifact_store as artifact_store_tool
import team_contract_governance_approval as approval_tool
import team_contract_package as package_tool
import team_contract_registry as registry_tool
import team_contract_registry_leader_backend as backend_tool


POINTER_PRODUCT = "PocoDDSRuntimeTeamContractAdapterCertifierTrustStatePointer"
STATE_PRODUCT = "PocoDDSRuntimeTeamContractAdapterCertifierTrustState"
STATUS_PRODUCT = "PocoDDSRuntimeTeamContractAdapterCertifierTrustStateStatus"
POLICY_MEDIA_TYPE = "application/vnd.pocodds.adapter-certifier-trust-policy+json"
STATE_MEDIA_TYPE = "application/vnd.pocodds.adapter-certifier-trust-state+json"
ACTIVATION_MEDIA_TYPE = "application/vnd.pocodds.adapter-certifier-trust-activation+json"
MIGRATION_MEDIA_TYPE = "application/vnd.pocodds.adapter-certifier-trust-migration+json"
MIGRATION_PRODUCT = "PocoDDSRuntimeTeamContractAdapterCertifierTrustStateMigration"
MIGRATION_PREFLIGHT_PRODUCT = MIGRATION_PRODUCT + "Preflight"
MIGRATION_PROPOSAL_PRODUCT = MIGRATION_PRODUCT + "Proposal"
MIGRATION_APPROVAL_PRODUCT = MIGRATION_PRODUCT + "Approval"
MIGRATION_REPORT_PRODUCT = MIGRATION_PRODUCT + "Report"
MAX_STATES = 100000


def _approval_entry(document: Any) -> None:
    if (not isinstance(document, dict) or set(document) != {
            "approverId", "keyId", "approvalSha256"
            } or any(package_tool.IDENTIFIER.fullmatch(str(
                document.get(name, ""))) is None
                for name in ("approverId", "keyId"))
            or package_tool.SHA256.fullmatch(str(
                document.get("approvalSha256", ""))) is None):
        raise ValueError("Adapter certifier trust migration approval entry is malformed")


def _migration_identity(document: dict[str, Any]) -> None:
    for name in (
            "controlId", "trustPolicyId", "stateBackendId", "artifactStoreId",
            "targetAdapterConfigResolverId"):
        if package_tool.IDENTIFIER.fullmatch(str(document.get(name, ""))) is None:
            raise ValueError("Adapter certifier trust migration identity is malformed")
    for name in (
            "sourcePointerSha256", "sourceStateSha256", "policySha256",
            "sourceStateBackendConfigSha256", "sourceArtifactStoreConfigSha256"):
        if package_tool.SHA256.fullmatch(str(document.get(name, ""))) is None:
            raise ValueError("Adapter certifier trust migration digest is malformed")
    if (type(document.get("sourceStateVersion")) is not int
            or not 1 <= document["sourceStateVersion"] < MAX_STATES
            or type(document.get("targetStateVersion")) is not int
            or document["targetStateVersion"] != document["sourceStateVersion"] + 1
            or type(document.get("policyGeneration")) is not int
            or document["policyGeneration"] < 1):
        raise ValueError("Adapter certifier trust migration version is malformed")
    resolver_id = document["targetAdapterConfigResolverId"]
    backend_ref = resolver_tool.validate_reference(
        document.get("targetStateBackendConfigRef"), resolver_id=resolver_id,
        adapter_kind="registry-leader-backend",
    )
    artifact_ref = resolver_tool.validate_reference(
        document.get("targetArtifactStoreConfigRef"), resolver_id=resolver_id,
        adapter_kind="artifact-store",
    )
    if (backend_ref["adapterId"] != document["stateBackendId"]
            or artifact_ref["adapterId"] != document["artifactStoreId"]):
        raise ValueError("Adapter certifier trust migration Adapter identity changed")


def validate_migration_preflight(document: Any) -> None:
    fields = {
        "schemaVersion", "product", "passed", "controlId", "trustPolicyId",
        "sourcePointerSchemaVersion", "targetPointerSchemaVersion",
        "sourceStateVersion", "targetStateVersion", "sourcePointerSha256",
        "sourceStateSha256", "policyGeneration", "policySha256",
        "stateBackendId", "artifactStoreId", "sourceStateBackendConfigSha256",
        "sourceArtifactStoreConfigSha256", "targetAdapterConfigResolverId",
        "targetStateBackendConfigRef", "targetArtifactStoreConfigRef",
        "targetAdapterConfigResolverCapabilityManifestSha256", "checkedAt",
    }
    if (not isinstance(document, dict) or set(document) != fields
            or document.get("schemaVersion") != 1
            or document.get("product") != MIGRATION_PREFLIGHT_PRODUCT
            or document.get("passed") is not True
            or document.get("sourcePointerSchemaVersion") != 1
            or document.get("targetPointerSchemaVersion") != 2
            or package_tool.SHA256.fullmatch(str(document.get(
                "targetAdapterConfigResolverCapabilityManifestSha256", ""))) is None):
        raise ValueError("Adapter certifier trust migration preflight is malformed")
    _migration_identity(document)
    package_tool.parse_time(document["checkedAt"], "migration preflight checkedAt")


def validate_migration_proposal(document: Any) -> None:
    fields = {
        "schemaVersion", "product", "operation", "proposalId", "controlId",
        "trustPolicyId", "sourceStateVersion", "targetStateVersion",
        "sourcePointerSha256", "sourceStateSha256", "policyGeneration",
        "policySha256", "stateBackendId", "artifactStoreId",
        "sourceStateBackendConfigSha256", "sourceArtifactStoreConfigSha256",
        "targetAdapterConfigResolverId", "targetStateBackendConfigRef",
        "targetArtifactStoreConfigRef", "governancePolicyId",
        "governancePolicySha256", "proposerId", "ticket", "reason",
        "issuedAt", "expiresAt",
    }
    if (not isinstance(document, dict) or set(document) != fields
            or document.get("schemaVersion") != 1
            or document.get("product") != MIGRATION_PROPOSAL_PRODUCT
            or document.get("operation") != "adapter-certifier-trust-state-migrate"
            or any(package_tool.IDENTIFIER.fullmatch(str(document.get(name, ""))) is None
                   for name in ("proposalId", "governancePolicyId", "proposerId", "ticket"))
            or package_tool.SHA256.fullmatch(str(
                document.get("governancePolicySha256", ""))) is None
            or not isinstance(document.get("reason"), str)
            or not document["reason"].strip() or len(document["reason"]) > 512):
        raise ValueError("Adapter certifier trust migration proposal is malformed")
    _migration_identity(document)
    issued = package_tool.parse_time(document["issuedAt"], "migration proposal issuedAt")
    expires = package_tool.parse_time(document["expiresAt"], "migration proposal expiresAt")
    if issued >= expires:
        raise ValueError("Adapter certifier trust migration proposal lifetime is invalid")


def validate_migration_approval(document: Any) -> None:
    base_fields = {
            "schemaVersion", "product", "algorithm", "approverId", "keyId",
            "proposalSha256", "signature"
    }
    version = document.get("schemaVersion") if isinstance(document, dict) else None
    fields = base_fields | (
        approval_tool.SIGNER_DESCRIPTOR_FIELDS if version == 2 else
        approval_tool.SIGNER_DESCRIPTOR_FIELDS
        | approval_tool.SIGNER_ADMISSION_FIELDS
        if version == 3 else set()
    )
    if (not isinstance(document, dict) or set(document) != fields
            or version not in {1, 2, 3}
            or document.get("product") != MIGRATION_APPROVAL_PRODUCT
            or document.get("algorithm") != "Ed25519"
            or any(package_tool.IDENTIFIER.fullmatch(str(document.get(name, ""))) is None
                   for name in ("approverId", "keyId"))
            or package_tool.SHA256.fullmatch(str(
                document.get("proposalSha256", ""))) is None):
        raise ValueError("Adapter certifier trust migration approval is malformed")
    try:
        signature = base64.b64decode(document["signature"], validate=True)
    except (TypeError, ValueError) as error:
        raise ValueError("Adapter certifier trust migration approval is malformed") from error
    if len(signature) != 64:
        raise ValueError("Adapter certifier trust migration approval is malformed")
    if version in {2, 3}:
        approval_tool.validate_signer_descriptor(
            document, admitted=version == 3
        )


def validate_migration_report(document: Any) -> None:
    base_fields = {
        "schemaVersion", "product", "passed", "proposalId", "proposalSha256",
        "operationId", "controlId", "trustPolicyId", "sourceStateVersion",
        "targetStateVersion", "sourcePointerSha256", "sourceStateSha256",
        "policyGeneration", "policySha256", "stateBackendId", "artifactStoreId",
        "sourceStateBackendConfigSha256", "sourceArtifactStoreConfigSha256",
        "targetAdapterConfigResolverId", "targetStateBackendConfigRef",
        "targetArtifactStoreConfigRef", "governancePolicyId",
        "governancePolicySha256", "proposerId", "activatorId", "approvals",
        "migratedAt",
    }
    version = document.get("schemaVersion") if isinstance(document, dict) else None
    fields = base_fields | (
        {"signerReadmissionEvidenceSha256"} if version == 2 else set()
    )
    if (not isinstance(document, dict) or set(document) != fields
            or version not in {1, 2}
            or document.get("product") != MIGRATION_REPORT_PRODUCT
            or document.get("passed") is not True
            or any(package_tool.IDENTIFIER.fullmatch(str(document.get(name, ""))) is None
                   for name in ("proposalId", "operationId", "governancePolicyId",
                                "proposerId", "activatorId"))
            or any(package_tool.SHA256.fullmatch(str(document.get(name, ""))) is None
                   for name in ("proposalSha256", "governancePolicySha256"))
            or not isinstance(document.get("approvals"), list)
            or not 1 <= len(document["approvals"]) <= control_tool.MAX_APPROVERS):
        raise ValueError("Adapter certifier trust migration report is malformed")
    _migration_identity(document)
    people: set[str] = set()
    keys: set[str] = set()
    for approval in document["approvals"]:
        _approval_entry(approval)
        if approval["approverId"] in people or approval["keyId"] in keys:
            raise ValueError("Adapter certifier trust migration approval is duplicated")
        people.add(approval["approverId"])
        keys.add(approval["keyId"])
    if (document["proposerId"] in people or document["activatorId"] in people
            or document["proposerId"] == document["activatorId"]):
        raise ValueError("Adapter certifier trust migration duties are not separated")
    package_tool.parse_time(document["migratedAt"], "migration report migratedAt")
    if version == 2 and package_tool.SHA256.fullmatch(str(
            document.get("signerReadmissionEvidenceSha256", ""))) is None:
        raise ValueError(
            "Adapter certifier trust migration signer readmission is malformed"
        )


def validate_pointer(document: Any) -> None:
    base_fields = {
        "schemaVersion", "product", "controlId", "trustPolicyId",
        "stateBackendId", "artifactStoreId", "stateVersion", "fencingToken",
        "previousPointerSha256", "stateRef", "stateSha256", "operationId",
        "coordinatorId", "updatedAt",
    }
    version = document.get("schemaVersion") if isinstance(document, dict) else None
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
            or any(package_tool.IDENTIFIER.fullmatch(str(document.get(name, ""))) is None
                   for name in ("controlId", "trustPolicyId", "stateBackendId",
                                "artifactStoreId", "operationId", "coordinatorId"))
            or package_tool.SHA256.fullmatch(str(
                document.get("stateSha256", ""))) is None
            or type(document.get("stateVersion")) is not int
            or not 1 <= document["stateVersion"] <= MAX_STATES
            or document.get("fencingToken") != document["stateVersion"]
            or (document["stateVersion"] == 1
                and document.get("previousPointerSha256") is not None)
            or (document["stateVersion"] > 1
                and package_tool.SHA256.fullmatch(str(
                    document.get("previousPointerSha256", ""))) is None)):
        raise ValueError("Adapter certifier trust state pointer is malformed")
    if version == 1 and any(package_tool.SHA256.fullmatch(str(
            document.get(name, ""))) is None for name in (
                "stateBackendConfigSha256", "artifactStoreConfigSha256")):
        raise ValueError("Adapter certifier trust state config pins are malformed")
    if version == 2:
        resolver_id = str(document.get("adapterConfigResolverId", ""))
        if package_tool.IDENTIFIER.fullmatch(resolver_id) is None:
            raise ValueError("Adapter certifier trust Resolver identity is malformed")
        backend_ref = resolver_tool.validate_reference(
            document.get("stateBackendConfigRef"), resolver_id=resolver_id,
            adapter_kind="registry-leader-backend",
        )
        artifact_ref = resolver_tool.validate_reference(
            document.get("artifactStoreConfigRef"), resolver_id=resolver_id,
            adapter_kind="artifact-store",
        )
        if (backend_ref["adapterId"] != document["stateBackendId"]
                or artifact_ref["adapterId"] != document["artifactStoreId"]):
            raise ValueError("Adapter certifier trust portable Adapter identity changed")
    package_tool.parse_time(document["updatedAt"], "trust state updatedAt")
    artifact_store_tool.validate_reference(
        document["stateRef"], store_id=document["artifactStoreId"],
        namespace_id=document["controlId"],
    )
    if document["stateRef"]["mediaType"] != STATE_MEDIA_TYPE:
        raise ValueError("Adapter certifier trust state reference media type changed")


def validate_state(document: Any) -> None:
    common_fields = {
        "schemaVersion", "product", "controlId", "trustPolicyId",
        "stateVersion", "previousStateSha256", "action", "operationId",
        "actor", "mode", "policyGeneration", "policyRef", "policySha256",
        "occurredAt",
    }
    version = document.get("schemaVersion") if isinstance(document, dict) else None
    fields = common_fields | (
        {"activationRef", "activationSha256"} if version == 1 else
        {"migrationRef", "migrationSha256"} if version == 2 else set()
    )
    if (not isinstance(document, dict) or set(document) != fields
            or version not in {1, 2}
            or document.get("product") != STATE_PRODUCT
            or any(package_tool.IDENTIFIER.fullmatch(str(document.get(name, ""))) is None
                   for name in ("controlId", "trustPolicyId", "operationId", "actor"))
            or type(document.get("stateVersion")) is not int
            or not 1 <= document["stateVersion"] <= MAX_STATES
            or type(document.get("policyGeneration")) is not int
            or document["policyGeneration"] < 1
            or package_tool.SHA256.fullmatch(str(document.get("policySha256", ""))) is None
            or document.get("action") not in {"initialize", "activate", "migrate"}
            or document.get("mode") not in {
                "initialize", "standard", "emergency-revocation",
                "portable-config-migration",
            }):
        raise ValueError("Adapter certifier trust remote state is malformed")
    package_tool.parse_time(document["occurredAt"], "trust state occurredAt")
    artifact_store_tool.validate_reference(
        document["policyRef"], namespace_id=document["controlId"]
    )
    if document["policyRef"]["mediaType"] != POLICY_MEDIA_TYPE:
        raise ValueError("Adapter certifier trust policy reference media type changed")
    if version == 2:
        if (document["stateVersion"] < 2
                or document["action"] != "migrate"
                or document["mode"] != "portable-config-migration"
                or package_tool.SHA256.fullmatch(str(
                    document.get("previousStateSha256", ""))) is None
                or package_tool.SHA256.fullmatch(str(
                    document.get("migrationSha256", ""))) is None):
            raise ValueError("Adapter certifier trust migration state is malformed")
        artifact_store_tool.validate_reference(
            document["migrationRef"], namespace_id=document["controlId"]
        )
        if document["migrationRef"]["mediaType"] != MIGRATION_MEDIA_TYPE:
            raise ValueError("Adapter certifier trust migration reference changed")
    elif document["stateVersion"] == 1:
        if (document["action"] != "initialize" or document["mode"] != "initialize"
                or document["previousStateSha256"] is not None
                or document["activationRef"] is not None
                or document["activationSha256"] is not None):
            raise ValueError("Adapter certifier trust initial state is malformed")
    else:
        if (document["action"] != "activate" or document["mode"] == "initialize"
                or package_tool.SHA256.fullmatch(str(
                    document.get("previousStateSha256", ""))) is None
                or package_tool.SHA256.fullmatch(str(
                    document.get("activationSha256", ""))) is None):
            raise ValueError("Adapter certifier trust activation state is malformed")
        artifact_store_tool.validate_reference(
            document["activationRef"], namespace_id=document["controlId"]
        )
        if document["activationRef"]["mediaType"] != ACTIVATION_MEDIA_TYPE:
            raise ValueError("Adapter certifier trust activation reference changed")


def validate_status(document: Any) -> None:
    if (not isinstance(document, dict) or set(document) != {
            "schemaVersion", "product", "passed", "controlId",
            "trustPolicyId", "stateVersion", "fencingToken",
            "policyGeneration", "policySha256", "operationId",
            "coordinatorId", "actor", "mode", "activationProposalId",
            "pointerSchemaVersion", "adapterConfigResolverId",
            "stateBackendConfigRef", "artifactStoreConfigRef",
            "adapterConfigResolverCapabilityManifestSha256", "updatedAt",
            } or document.get("schemaVersion") != 1
            or document.get("product") != STATUS_PRODUCT
            or document.get("passed") is not True
            or any(package_tool.IDENTIFIER.fullmatch(str(document.get(name, ""))) is None
                   for name in ("controlId", "trustPolicyId", "operationId",
                                "coordinatorId", "actor"))
            or type(document.get("stateVersion")) is not int
            or not 1 <= document["stateVersion"] <= MAX_STATES
            or document.get("fencingToken") != document["stateVersion"]
            or type(document.get("policyGeneration")) is not int
            or document["policyGeneration"] < 1
            or package_tool.SHA256.fullmatch(str(
                document.get("policySha256", ""))) is None
            or document.get("mode") not in {
                "initialize", "standard", "emergency-revocation",
                "portable-config-migration"}
            or (document.get("activationProposalId") is not None
                and package_tool.IDENTIFIER.fullmatch(str(
                    document["activationProposalId"])) is None)
            or type(document.get("pointerSchemaVersion")) is not int
            or document["pointerSchemaVersion"] not in {1, 2}):
        raise ValueError("Adapter certifier trust remote status is malformed")
    portable_values = (
        document.get("adapterConfigResolverId"),
        document.get("stateBackendConfigRef"),
        document.get("artifactStoreConfigRef"),
        document.get("adapterConfigResolverCapabilityManifestSha256"),
    )
    if document["pointerSchemaVersion"] == 1:
        if any(value is not None for value in portable_values):
            raise ValueError("Adapter certifier trust v1 status contains portable identity")
    else:
        if any(value is None for value in portable_values):
            raise ValueError("Adapter certifier trust v2 status lacks portable identity")
        resolver_id = str(document["adapterConfigResolverId"])
        resolver_tool.validate_reference(
            document["stateBackendConfigRef"], resolver_id=resolver_id,
            adapter_kind="registry-leader-backend",
        )
        resolver_tool.validate_reference(
            document["artifactStoreConfigRef"], resolver_id=resolver_id,
            adapter_kind="artifact-store",
        )
        if package_tool.SHA256.fullmatch(str(
                document["adapterConfigResolverCapabilityManifestSha256"])) is None:
            raise ValueError("Adapter certifier trust v2 status capability is malformed")
    package_tool.parse_time(document["updatedAt"], "trust status updatedAt")


class RemoteCertifierTrustStateStore:
    """Stores immutable policy generations behind one linearizable CAS pointer."""

    def __init__(self, *, state_backend_config: str | Path,
                 state_backend_config_sha256: str,
                 artifact_store_config: str | Path,
                 artifact_store_config_sha256: str,
                 control_id: str, trust_policy_id: str,
                 expected_backend_id: str, expected_artifact_store_id: str,
                 coordinator_id: str | None,
                 adapter_config_resolver_id: str | None = None,
                 state_backend_config_ref: dict[str, Any] | None = None,
                 artifact_store_config_ref: dict[str, Any] | None = None,
                 adapter_config_resolver_capability_sha256: str | None = None) -> None:
        for label, value in (("control", control_id), ("trust policy", trust_policy_id)):
            if package_tool.IDENTIFIER.fullmatch(str(value)) is None:
                raise ValueError(f"Adapter certifier {label} identity is malformed")
        if (coordinator_id is not None
                and package_tool.IDENTIFIER.fullmatch(coordinator_id) is None):
            raise ValueError("Adapter certifier trust coordinator identity is malformed")
        self.backend = backend_tool.ExternalCommandBackend(
            state_backend_config, state_backend_config_sha256,
            control_id, trust_policy_id,
        )
        self.artifact_store = artifact_store_tool.ExternalCommandArtifactStore(
            artifact_store_config, artifact_store_config_sha256, control_id
        )
        if self.backend.backend_id != expected_backend_id:
            raise ValueError("Adapter certifier trust state Backend identity changed")
        if self.artifact_store.store_id != expected_artifact_store_id:
            raise ValueError("Adapter certifier trust Artifact Store identity changed")
        if self.backend.capability_manifest_sha256 is None:
            raise ValueError("Adapter certifier trust state Backend lacks capability negotiation")
        self.control_id = control_id
        self.trust_policy_id = trust_policy_id
        self.coordinator_id = coordinator_id
        self.backend_config_sha256 = state_backend_config_sha256
        self.artifact_store_config_sha256 = artifact_store_config_sha256
        portable = (
            adapter_config_resolver_id, state_backend_config_ref,
            artifact_store_config_ref,
        )
        if any(value is not None for value in portable) \
                and any(value is None for value in portable):
            raise ValueError("Adapter certifier trust portable state identity is incomplete")
        self.adapter_config_resolver_id = adapter_config_resolver_id
        self.state_backend_config_ref = state_backend_config_ref
        self.artifact_store_config_ref = artifact_store_config_ref
        self.adapter_config_resolver_capability_sha256 = \
            adapter_config_resolver_capability_sha256
        self.portable = adapter_config_resolver_id is not None
        if self.portable:
            assert adapter_config_resolver_id is not None
            assert state_backend_config_ref is not None
            assert artifact_store_config_ref is not None
            resolver_tool.validate_reference(
                state_backend_config_ref,
                resolver_id=adapter_config_resolver_id,
                adapter_kind="registry-leader-backend",
            )
            resolver_tool.validate_reference(
                artifact_store_config_ref,
                resolver_id=adapter_config_resolver_id,
                adapter_kind="artifact-store",
            )
            if (state_backend_config_ref["adapterId"] != expected_backend_id
                    or artifact_store_config_ref["adapterId"]
                    != expected_artifact_store_id):
                raise ValueError("Adapter certifier trust portable Adapter identity changed")
            if package_tool.SHA256.fullmatch(str(
                    adapter_config_resolver_capability_sha256 or "")) is None:
                raise ValueError("Adapter certifier trust Resolver capability changed")
        elif adapter_config_resolver_capability_sha256 is not None:
            raise ValueError("Adapter certifier trust direct mode rejects Resolver capability")
        self._token = 0
        self._pointer_sha256 = backend_tool.ZERO_SHA256
        self._state_sha256: str | None = None
        self._policy_sha256: str | None = None
        self._policy_generation: int | None = None

    @property
    def state_version(self) -> int:
        return self._token

    def _validate_base_scope(self, pointer: dict[str, Any]) -> None:
        if (pointer["controlId"] != self.control_id
                or pointer["trustPolicyId"] != self.trust_policy_id
                or pointer["stateBackendId"] != self.backend.backend_id
                or pointer["artifactStoreId"] != self.artifact_store.store_id):
            raise ValueError("Adapter certifier trust state pointer base scope changed")

    def _validate_scope(self, pointer: dict[str, Any]) -> None:
        self._validate_base_scope(pointer)
        changed = False
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
            raise ValueError("Adapter certifier trust state pointer scope changed")

    @staticmethod
    def _same_pointer_config(left: dict[str, Any], right: dict[str, Any]) -> bool:
        if left["schemaVersion"] != right["schemaVersion"]:
            return False
        if left["schemaVersion"] == 1:
            return all(left[name] == right[name] for name in (
                "stateBackendConfigSha256", "artifactStoreConfigSha256"
            ))
        return all(left[name] == right[name] for name in (
            "adapterConfigResolverId", "stateBackendConfigRef",
            "artifactStoreConfigRef",
        ))

    def _record(self, pointer: dict[str, Any]) -> tuple[
            dict[str, Any], dict[str, Any], bytes, str,
            dict[str, Any] | None, dict[str, Any] | None]:
        state_content = self.artifact_store.get(pointer["stateRef"])
        if package_tool.sha256_bytes(state_content) != pointer["stateSha256"]:
            raise ValueError("Adapter certifier trust remote state digest changed")
        try:
            state = json.loads(state_content)
        except (UnicodeError, json.JSONDecodeError) as error:
            raise ValueError("Adapter certifier trust remote state is invalid JSON") from error
        validate_state(state)
        if (state["controlId"] != self.control_id
                or state["trustPolicyId"] != self.trust_policy_id
                or state["stateVersion"] != pointer["stateVersion"]
                or state["operationId"] != pointer["operationId"]
                or state["policyRef"].get("storeId") != pointer["artifactStoreId"]):
            raise ValueError("Adapter certifier trust state chain changed")
        policy_content = self.artifact_store.get(state["policyRef"])
        policy_sha = package_tool.sha256_bytes(policy_content)
        if policy_sha != state["policySha256"]:
            raise ValueError("Adapter certifier trust policy artifact changed")
        try:
            policy = json.loads(policy_content)
        except (UnicodeError, json.JSONDecodeError) as error:
            raise ValueError("Adapter certifier trust policy artifact is invalid JSON") from error
        trust_tool.validate_policy(policy)
        if (policy["policyId"] != self.trust_policy_id
                or policy["generation"] != state["policyGeneration"]):
            raise ValueError("Adapter certifier trust policy state identity changed")
        activation = None
        migration = None
        if state["action"] == "activate":
            activation_content = self.artifact_store.get(state["activationRef"])
            if package_tool.sha256_bytes(activation_content) != state["activationSha256"]:
                raise ValueError("Adapter certifier trust activation evidence changed")
            try:
                activation = json.loads(activation_content)
            except (UnicodeError, json.JSONDecodeError) as error:
                raise ValueError(
                    "Adapter certifier trust activation evidence is invalid JSON"
                ) from error
            control_tool.validate_activation_report(activation)
            if (activation["policySha256"] != policy_sha
                    or activation["generation"] != policy["generation"]
                    or activation["mode"] != state["mode"]):
                raise ValueError("Adapter certifier trust activation evidence identity changed")
        elif state["action"] == "migrate":
            migration_content = self.artifact_store.get(state["migrationRef"])
            if package_tool.sha256_bytes(migration_content) != state["migrationSha256"]:
                raise ValueError("Adapter certifier trust migration evidence changed")
            try:
                migration = json.loads(migration_content)
            except (UnicodeError, json.JSONDecodeError) as error:
                raise ValueError(
                    "Adapter certifier trust migration evidence is invalid JSON"
                ) from error
            validate_migration_report(migration)
            if (migration["policySha256"] != policy_sha
                    or migration["policyGeneration"] != policy["generation"]
                    or migration["operationId"] != state["operationId"]):
                raise ValueError("Adapter certifier trust migration evidence identity changed")
        return state, policy, policy_content, policy_sha, activation, migration

    def read(self) -> dict[str, Any] | None:
        loaded = self.backend.current()
        if loaded is None:
            self._token = 0
            self._pointer_sha256 = backend_tool.ZERO_SHA256
            self._state_sha256 = None
            self._policy_sha256 = None
            self._policy_generation = None
            return None
        pointer, _, pointer_sha = loaded
        validate_pointer(pointer)
        self._validate_scope(pointer)
        state, policy, policy_content, policy_sha, activation, migration = \
            self._record(pointer)
        self._verify_history(pointer, state, activation, migration)
        self._token = pointer["stateVersion"]
        self._pointer_sha256 = pointer_sha
        self._state_sha256 = pointer["stateSha256"]
        self._policy_sha256 = policy_sha
        self._policy_generation = policy["generation"]
        return {
            "pointer": pointer, "state": state, "policy": policy,
            "policyBytes": policy_content, "policySha256": policy_sha,
            "activation": activation, "migration": migration,
            "adapterConfigResolverCapabilityManifestSha256":
                self.adapter_config_resolver_capability_sha256,
        }

    def read_legacy_for_migration(
            self, *, source_backend_config_sha256: str,
            source_artifact_store_config_sha256: str) -> dict[str, Any]:
        """Verify one v1 chain through the target portable Adapters."""
        if not self.portable:
            raise ValueError("Adapter certifier trust migration target must be portable")
        loaded = self.backend.current()
        if loaded is None:
            raise ValueError("Adapter certifier trust migration source is uninitialized")
        pointer, _, pointer_sha = loaded
        validate_pointer(pointer)
        self._validate_base_scope(pointer)
        if (pointer["schemaVersion"] != 1
                or pointer["stateBackendConfigSha256"]
                    != source_backend_config_sha256
                or pointer["artifactStoreConfigSha256"]
                    != source_artifact_store_config_sha256):
            raise ValueError("Adapter certifier trust migration source scope changed")
        state, policy, policy_content, policy_sha, activation, migration = \
            self._record(pointer)
        self._verify_history(pointer, state, activation, migration)
        self._token = pointer["stateVersion"]
        self._pointer_sha256 = pointer_sha
        self._state_sha256 = pointer["stateSha256"]
        self._policy_sha256 = policy_sha
        self._policy_generation = policy["generation"]
        return {
            "pointer": pointer, "state": state, "policy": policy,
            "policyBytes": policy_content, "policySha256": policy_sha,
            "activation": activation, "migration": migration,
            "adapterConfigResolverCapabilityManifestSha256":
                self.adapter_config_resolver_capability_sha256,
        }

    def _previous_pointer(self, pointer: dict[str, Any]) \
            -> dict[str, Any] | None:
        if pointer["stateVersion"] == 1:
            return None
        previous = self.backend.grant(
            pointer["stateVersion"] - 1, pointer["previousPointerSha256"]
        )[0]
        validate_pointer(previous)
        self._validate_base_scope(previous)
        if previous["stateVersion"] != pointer["stateVersion"] - 1:
            raise ValueError("Adapter certifier trust pointer history changed")
        return previous

    def _historical_record(self, pointer: dict[str, Any]) \
            -> tuple[dict[str, Any], dict[str, Any], dict[str, Any] | None,
                     dict[str, Any] | None]:
        state, policy, _, _, activation, migration = self._record(pointer)
        return state, policy, activation, migration

    def _verify_history(self, pointer: dict[str, Any], state: dict[str, Any],
                        activation: dict[str, Any] | None,
                        migration: dict[str, Any] | None) -> None:
        child_pointer = pointer
        child_state = state
        child_activation = activation
        child_migration = migration
        visited = 1
        migration_count = 0
        legacy_pins: tuple[str, str] | None = None
        while child_pointer["stateVersion"] > 1:
            if visited > MAX_STATES:
                raise ValueError("Adapter certifier trust state history is too long")
            previous_pointer = self._previous_pointer(child_pointer)
            assert previous_pointer is not None
            previous_state, _, previous_activation, previous_migration = self._historical_record(
                previous_pointer
            )
            if child_state["previousStateSha256"] != previous_pointer["stateSha256"]:
                raise ValueError("Adapter certifier trust state history chain changed")
            if child_state["action"] == "activate":
                if (not self._same_pointer_config(child_pointer, previous_pointer)
                        or child_state["policyGeneration"]
                        != previous_state["policyGeneration"] + 1
                        or child_activation is None or child_migration is not None
                        or child_activation["previousPolicySha256"]
                        != previous_state["policySha256"]
                        or child_activation["previousGeneration"]
                        != previous_state["policyGeneration"]):
                    raise ValueError("Adapter certifier trust activation history changed")
            elif child_state["action"] == "migrate":
                migration_count += 1
                if (migration_count != 1 or child_migration is None
                        or child_activation is not None
                        or child_pointer["schemaVersion"] != 2
                        or previous_pointer["schemaVersion"] != 1
                        or child_state["policyGeneration"]
                        != previous_state["policyGeneration"]
                        or child_state["policySha256"] != previous_state["policySha256"]):
                    raise ValueError("Adapter certifier trust migration boundary changed")
                expected = {
                    "controlId": self.control_id,
                    "trustPolicyId": self.trust_policy_id,
                    "sourceStateVersion": previous_pointer["stateVersion"],
                    "targetStateVersion": child_pointer["stateVersion"],
                    "sourcePointerSha256": child_pointer["previousPointerSha256"],
                    "sourceStateSha256": previous_pointer["stateSha256"],
                    "policyGeneration": previous_state["policyGeneration"],
                    "policySha256": previous_state["policySha256"],
                    "stateBackendId": child_pointer["stateBackendId"],
                    "artifactStoreId": child_pointer["artifactStoreId"],
                    "sourceStateBackendConfigSha256":
                        previous_pointer["stateBackendConfigSha256"],
                    "sourceArtifactStoreConfigSha256":
                        previous_pointer["artifactStoreConfigSha256"],
                    "targetAdapterConfigResolverId":
                        child_pointer["adapterConfigResolverId"],
                    "targetStateBackendConfigRef":
                        child_pointer["stateBackendConfigRef"],
                    "targetArtifactStoreConfigRef":
                        child_pointer["artifactStoreConfigRef"],
                    "operationId": child_pointer["operationId"],
                }
                if any(child_migration[name] != value
                       for name, value in expected.items()):
                    raise ValueError("Adapter certifier trust migration evidence changed")
                legacy_pins = (
                    previous_pointer["stateBackendConfigSha256"],
                    previous_pointer["artifactStoreConfigSha256"],
                )
            else:
                raise ValueError("Adapter certifier trust history action changed")
            if legacy_pins is not None and previous_pointer["schemaVersion"] == 1:
                if (previous_pointer["stateBackendConfigSha256"],
                        previous_pointer["artifactStoreConfigSha256"]) != legacy_pins:
                    raise ValueError("Adapter certifier trust legacy migration scope changed")
            child_pointer = previous_pointer
            child_state = previous_state
            child_activation = previous_activation
            child_migration = previous_migration
            visited += 1
        if (child_state["stateVersion"] != 1
                or child_state["previousStateSha256"] is not None
                or child_activation is not None or child_migration is not None
                or child_state["action"] != "initialize"):
            raise ValueError("Adapter certifier trust state genesis changed")
        if pointer["schemaVersion"] == 2 and child_pointer["schemaVersion"] == 1 \
                and migration_count != 1:
            raise ValueError("Adapter certifier trust migration evidence is missing")

    def _commit(self, *, policy: dict[str, Any], policy_content: bytes,
                operation_id: str, actor: str, mode: str,
                activation: dict[str, Any] | None) -> dict[str, Any]:
        if self.coordinator_id is None:
            raise ValueError("Adapter certifier trust coordinator is required for state changes")
        if any(package_tool.IDENTIFIER.fullmatch(str(value)) is None
               for value in (operation_id, actor)):
            raise ValueError("Adapter certifier trust operation identity is malformed")
        next_token = self._token + 1
        action = "initialize" if next_token == 1 else "activate"
        if (action == "initialize") != (activation is None) or mode not in {
                "initialize", "standard", "emergency-revocation"}:
            raise ValueError("Adapter certifier trust state transition is malformed")
        policy_sha = package_tool.sha256_bytes(policy_content)
        policy_ref = self.artifact_store.put(policy_content, POLICY_MEDIA_TYPE)
        activation_ref = None
        activation_sha = None
        if activation is not None:
            control_tool.validate_activation_report(activation)
            activation_content = package_tool.json_bytes(activation)
            activation_sha = package_tool.sha256_bytes(activation_content)
            activation_ref = self.artifact_store.put(
                activation_content, ACTIVATION_MEDIA_TYPE
            )
        occurred_at = registry_tool.utc_time(None)
        state = {
            "schemaVersion": 1, "product": STATE_PRODUCT,
            "controlId": self.control_id, "trustPolicyId": self.trust_policy_id,
            "stateVersion": next_token, "previousStateSha256": self._state_sha256,
            "action": action, "operationId": operation_id, "actor": actor,
            "mode": mode, "policyGeneration": policy["generation"],
            "policyRef": policy_ref, "policySha256": policy_sha,
            "activationRef": activation_ref, "activationSha256": activation_sha,
            "occurredAt": occurred_at,
        }
        validate_state(state)
        state_content = package_tool.json_bytes(state)
        state_sha = package_tool.sha256_bytes(state_content)
        state_ref = self.artifact_store.put(state_content, STATE_MEDIA_TYPE)
        pointer = {
            "schemaVersion": 2 if self.portable else 1,
            "product": POINTER_PRODUCT,
            "controlId": self.control_id, "trustPolicyId": self.trust_policy_id,
            "stateBackendId": self.backend.backend_id,
            "artifactStoreId": self.artifact_store.store_id,
            "stateVersion": next_token, "fencingToken": next_token,
            "previousPointerSha256": None if self._token == 0 else self._pointer_sha256,
            "stateRef": state_ref, "stateSha256": state_sha,
            "operationId": operation_id, "coordinatorId": self.coordinator_id,
            "updatedAt": occurred_at,
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
                "artifactStoreConfigSha256": self.artifact_store_config_sha256,
            })
        validate_pointer(pointer)
        content = package_tool.json_bytes(pointer)
        digest = package_tool.sha256_bytes(content)
        try:
            self.backend.compare_and_swap(
                self._token, self._pointer_sha256, pointer, content, digest
            )
        except backend_tool.BackendCommitUncertainError:
            current = self.backend.current()
            if current is None:
                raise
            current_pointer, current_content, current_sha = current
            validate_pointer(current_pointer)
            self._validate_scope(current_pointer)
            if (current_pointer != pointer or current_content != content
                    or current_sha != digest):
                raise
        self._token = next_token
        self._pointer_sha256 = digest
        self._state_sha256 = state_sha
        self._policy_sha256 = policy_sha
        self._policy_generation = policy["generation"]
        return {"pointer": pointer, "state": state, "policy": policy,
                "policyBytes": policy_content, "policySha256": policy_sha,
                "activation": activation, "migration": None,
                "adapterConfigResolverCapabilityManifestSha256":
                    self.adapter_config_resolver_capability_sha256}

    def initialize(self, policy_content: bytes, *, operation_id: str,
                   actor: str) -> dict[str, Any]:
        if self._token != 0 or self.backend.current() is not None:
            raise ValueError("Adapter certifier trust remote state already exists")
        try:
            policy = json.loads(policy_content)
        except (UnicodeError, json.JSONDecodeError) as error:
            raise ValueError("initial Adapter certifier trust policy is invalid JSON") from error
        trust_tool.validate_policy(policy)
        if policy["policyId"] != self.trust_policy_id:
            raise ValueError("initial Adapter certifier trust policy identity changed")
        return self._commit(policy=policy, policy_content=policy_content,
                            operation_id=operation_id, actor=actor,
                            mode="initialize", activation=None)

    def activate(self, policy_content: bytes, activation: dict[str, Any], *,
                 expected_state_version: int, expected_current_policy_sha256: str,
                 operation_id: str, actor: str) -> dict[str, Any]:
        if (self._token != expected_state_version
                or self._policy_sha256 != expected_current_policy_sha256
                or self._policy_generation is None):
            raise ValueError("Adapter certifier trust remote state changed before activation")
        try:
            policy = json.loads(policy_content)
        except (UnicodeError, json.JSONDecodeError) as error:
            raise ValueError("candidate Adapter certifier trust policy is invalid JSON") from error
        trust_tool.validate_policy(policy)
        control_tool.validate_activation_report(activation)
        if (policy["policyId"] != self.trust_policy_id
                or policy["generation"] != self._policy_generation + 1
                or activation["previousPolicySha256"] != self._policy_sha256
                or activation["previousGeneration"] != self._policy_generation
                or activation["policySha256"] != package_tool.sha256_bytes(policy_content)
                or activation["generation"] != policy["generation"]
                or activation["activatorId"] != actor):
            raise ValueError("Adapter certifier trust remote activation evidence changed")
        return self._commit(policy=policy, policy_content=policy_content,
                            operation_id=operation_id, actor=actor,
                            mode=activation["mode"], activation=activation)

    def migrate(self, migration: dict[str, Any], *,
                expected_state_version: int,
                expected_source_pointer_sha256: str,
                expected_current_policy_sha256: str,
                operation_id: str, actor: str) -> dict[str, Any]:
        if not self.portable or self.coordinator_id is None:
            raise ValueError("Adapter certifier trust portable coordinator is required")
        validate_migration_report(migration)
        if (self._token != expected_state_version
                or self._pointer_sha256 != expected_source_pointer_sha256
                or self._policy_sha256 != expected_current_policy_sha256
                or self._policy_generation is None
                or migration["operationId"] != operation_id
                or migration["activatorId"] != actor):
            raise ValueError("Adapter certifier trust migration source changed")
        loaded = self.backend.current()
        if loaded is None:
            raise ValueError("Adapter certifier trust migration source disappeared")
        source_pointer, _, source_pointer_sha = loaded
        validate_pointer(source_pointer)
        self._validate_base_scope(source_pointer)
        expected = {
            "controlId": self.control_id,
            "trustPolicyId": self.trust_policy_id,
            "sourceStateVersion": self._token,
            "targetStateVersion": self._token + 1,
            "sourcePointerSha256": self._pointer_sha256,
            "sourceStateSha256": self._state_sha256,
            "policyGeneration": self._policy_generation,
            "policySha256": self._policy_sha256,
            "stateBackendId": self.backend.backend_id,
            "artifactStoreId": self.artifact_store.store_id,
            "sourceStateBackendConfigSha256":
                source_pointer.get("stateBackendConfigSha256"),
            "sourceArtifactStoreConfigSha256":
                source_pointer.get("artifactStoreConfigSha256"),
            "targetAdapterConfigResolverId": self.adapter_config_resolver_id,
            "targetStateBackendConfigRef": self.state_backend_config_ref,
            "targetArtifactStoreConfigRef": self.artifact_store_config_ref,
        }
        if (source_pointer["schemaVersion"] != 1
                or source_pointer_sha != self._pointer_sha256
                or any(migration[name] != value for name, value in expected.items())):
            raise ValueError("Adapter certifier trust migration evidence changed")
        policy_content = self.artifact_store.get(source_pointer["stateRef"])
        source_state = json.loads(policy_content)
        validate_state(source_state)
        policy_content = self.artifact_store.get(source_state["policyRef"])
        if package_tool.sha256_bytes(policy_content) != self._policy_sha256:
            raise ValueError("Adapter certifier trust migration policy changed")
        policy = json.loads(policy_content)
        trust_tool.validate_policy(policy)
        migration_content = package_tool.json_bytes(migration)
        migration_sha = package_tool.sha256_bytes(migration_content)
        migration_ref = self.artifact_store.put(
            migration_content, MIGRATION_MEDIA_TYPE
        )
        policy_ref = self.artifact_store.put(policy_content, POLICY_MEDIA_TYPE)
        state = {
            "schemaVersion": 2, "product": STATE_PRODUCT,
            "controlId": self.control_id, "trustPolicyId": self.trust_policy_id,
            "stateVersion": self._token + 1,
            "previousStateSha256": self._state_sha256,
            "action": "migrate", "operationId": operation_id, "actor": actor,
            "mode": "portable-config-migration",
            "policyGeneration": policy["generation"], "policyRef": policy_ref,
            "policySha256": self._policy_sha256,
            "migrationRef": migration_ref, "migrationSha256": migration_sha,
            "occurredAt": migration["migratedAt"],
        }
        validate_state(state)
        state_content = package_tool.json_bytes(state)
        state_sha = package_tool.sha256_bytes(state_content)
        state_ref = self.artifact_store.put(state_content, STATE_MEDIA_TYPE)
        pointer = {
            "schemaVersion": 2, "product": POINTER_PRODUCT,
            "controlId": self.control_id, "trustPolicyId": self.trust_policy_id,
            "stateBackendId": self.backend.backend_id,
            "artifactStoreId": self.artifact_store.store_id,
            "stateVersion": self._token + 1, "fencingToken": self._token + 1,
            "previousPointerSha256": self._pointer_sha256,
            "stateRef": state_ref, "stateSha256": state_sha,
            "operationId": operation_id, "coordinatorId": self.coordinator_id,
            "updatedAt": migration["migratedAt"],
            "adapterConfigResolverId": self.adapter_config_resolver_id,
            "stateBackendConfigRef": self.state_backend_config_ref,
            "artifactStoreConfigRef": self.artifact_store_config_ref,
        }
        validate_pointer(pointer)
        content = package_tool.json_bytes(pointer)
        digest = package_tool.sha256_bytes(content)
        try:
            self.backend.compare_and_swap(
                self._token, self._pointer_sha256, pointer, content, digest
            )
        except backend_tool.BackendCommitUncertainError:
            current = self.backend.current()
            if current is None:
                raise
            current_pointer, current_content, current_sha = current
            validate_pointer(current_pointer)
            self._validate_scope(current_pointer)
            if (current_pointer != pointer or current_content != content
                    or current_sha != digest):
                raise
        self._token = pointer["stateVersion"]
        self._pointer_sha256 = digest
        self._state_sha256 = state_sha
        return {
            "pointer": pointer, "state": state, "policy": policy,
            "policyBytes": policy_content, "policySha256": self._policy_sha256,
            "activation": None, "migration": migration,
            "adapterConfigResolverCapabilityManifestSha256":
                self.adapter_config_resolver_capability_sha256,
        }


def _reference(path_value: str, expected_sha: str, *, resolver_id: str,
               adapter_kind: str) -> dict[str, Any]:
    document, _, _ = adapter_runtime.load_pinned_json(
        path_value, expected_sha, f"{adapter_kind} logical config reference",
        lambda item: resolver_tool.validate_reference(
            item, resolver_id=resolver_id, adapter_kind=adapter_kind
        ),
    )
    return document


def _store(args: argparse.Namespace, coordinator: bool) -> RemoteCertifierTrustStateStore:
    direct = (
        getattr(args, "state_backend_config", None),
        getattr(args, "expected_state_backend_config_sha256", None),
        getattr(args, "artifact_store_config", None),
        getattr(args, "expected_artifact_store_config_sha256", None),
    )
    portable = (
        getattr(args, "adapter_config_resolver_config", None),
        getattr(args, "expected_adapter_config_resolver_config_sha256", None),
        getattr(args, "expected_adapter_config_resolver_id", None),
        getattr(args, "state_backend_config_ref", None),
        getattr(args, "expected_state_backend_config_ref_sha256", None),
        getattr(args, "artifact_store_config_ref", None),
        getattr(args, "expected_artifact_store_config_ref_sha256", None),
    )
    if any(value is not None for value in portable):
        if not all(value is not None for value in portable):
            raise ValueError("Adapter certifier trust portable config arguments are incomplete")
        if any(value is not None for value in direct):
            raise ValueError("Adapter certifier trust portable mode rejects direct configs")
        resolver_id = str(portable[2])
        backend_ref = _reference(
            str(portable[3]), str(portable[4]), resolver_id=resolver_id,
            adapter_kind="registry-leader-backend",
        )
        artifact_ref = _reference(
            str(portable[5]), str(portable[6]), resolver_id=resolver_id,
            adapter_kind="artifact-store",
        )
        resolver = resolver_tool.ExternalCommandAdapterConfigResolver(
            str(portable[0]), str(portable[1])
        )
        if resolver.resolver_id != resolver_id:
            raise ValueError("Adapter certifier trust Resolver identity changed")
        backend = resolver.resolve(
            backend_ref, consumer_type="adapter-certifier-trust-state",
            consumer_id=args.control_id, resource_id=args.trust_policy_id,
        )
        artifact = resolver.resolve(
            artifact_ref, consumer_type="adapter-certifier-trust-state",
            consumer_id=args.control_id, resource_id=args.trust_policy_id,
        )
        return RemoteCertifierTrustStateStore(
            state_backend_config=backend[1],
            state_backend_config_sha256=backend[2],
            artifact_store_config=artifact[1],
            artifact_store_config_sha256=artifact[2],
            control_id=args.control_id, trust_policy_id=args.trust_policy_id,
            expected_backend_id=args.expected_state_backend_id,
            expected_artifact_store_id=args.expected_artifact_store_id,
            coordinator_id=args.coordinator_id if coordinator else None,
            adapter_config_resolver_id=resolver.resolver_id,
            state_backend_config_ref=backend_ref,
            artifact_store_config_ref=artifact_ref,
            adapter_config_resolver_capability_sha256=
                resolver.capability_manifest_sha256,
        )
    if not all(value is not None for value in direct):
        raise ValueError("Adapter certifier trust direct config arguments are incomplete")
    return RemoteCertifierTrustStateStore(
        state_backend_config=str(direct[0]),
        state_backend_config_sha256=str(direct[1]),
        artifact_store_config=str(direct[2]),
        artifact_store_config_sha256=str(direct[3]),
        control_id=args.control_id, trust_policy_id=args.trust_policy_id,
        expected_backend_id=args.expected_state_backend_id,
        expected_artifact_store_id=args.expected_artifact_store_id,
        coordinator_id=args.coordinator_id if coordinator else None,
    )


def _pinned_document(path_value: str | Path, expected_sha256: str, label: str,
                     validator: Any) \
        -> tuple[dict[str, Any], Path, bytes, str]:
    path = package_tool.resolved_path(path_value, label)
    content = path.read_bytes()
    digest = package_tool.sha256_bytes(content)
    if (package_tool.SHA256.fullmatch(str(expected_sha256).lower()) is None
            or digest != str(expected_sha256).lower()):
        raise ValueError(f"{label} SHA changed")
    try:
        document = json.loads(content)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} is invalid JSON") from error
    validator(document)
    return document, path, content, digest


def _migration_stores(args: argparse.Namespace, coordinator: bool) -> tuple[
        RemoteCertifierTrustStateStore, RemoteCertifierTrustStateStore]:
    required = (
        "source_state_backend_config",
        "expected_source_state_backend_config_sha256",
        "source_artifact_store_config",
        "expected_source_artifact_store_config_sha256",
        "target_adapter_config_resolver_config",
        "expected_target_adapter_config_resolver_config_sha256",
        "expected_target_adapter_config_resolver_id",
        "target_state_backend_config_ref",
        "expected_target_state_backend_config_ref_sha256",
        "target_artifact_store_config_ref",
        "expected_target_artifact_store_config_ref_sha256",
    )
    if any(getattr(args, name, None) is None for name in required):
        raise ValueError("Adapter certifier trust migration configs are incomplete")
    source = RemoteCertifierTrustStateStore(
        state_backend_config=args.source_state_backend_config,
        state_backend_config_sha256=
            args.expected_source_state_backend_config_sha256,
        artifact_store_config=args.source_artifact_store_config,
        artifact_store_config_sha256=
            args.expected_source_artifact_store_config_sha256,
        control_id=args.control_id, trust_policy_id=args.trust_policy_id,
        expected_backend_id=args.expected_state_backend_id,
        expected_artifact_store_id=args.expected_artifact_store_id,
        coordinator_id=None,
    )
    resolver_id = args.expected_target_adapter_config_resolver_id
    backend_ref = _reference(
        args.target_state_backend_config_ref,
        args.expected_target_state_backend_config_ref_sha256,
        resolver_id=resolver_id, adapter_kind="registry-leader-backend",
    )
    artifact_ref = _reference(
        args.target_artifact_store_config_ref,
        args.expected_target_artifact_store_config_ref_sha256,
        resolver_id=resolver_id, adapter_kind="artifact-store",
    )
    resolver = resolver_tool.ExternalCommandAdapterConfigResolver(
        args.target_adapter_config_resolver_config,
        args.expected_target_adapter_config_resolver_config_sha256,
    )
    if resolver.resolver_id != resolver_id:
        raise ValueError("Adapter certifier trust migration Resolver identity changed")
    backend = resolver.resolve(
        backend_ref, consumer_type="adapter-certifier-trust-state",
        consumer_id=args.control_id, resource_id=args.trust_policy_id,
    )
    artifact = resolver.resolve(
        artifact_ref, consumer_type="adapter-certifier-trust-state",
        consumer_id=args.control_id, resource_id=args.trust_policy_id,
    )
    target = RemoteCertifierTrustStateStore(
        state_backend_config=backend[1], state_backend_config_sha256=backend[2],
        artifact_store_config=artifact[1], artifact_store_config_sha256=artifact[2],
        control_id=args.control_id, trust_policy_id=args.trust_policy_id,
        expected_backend_id=args.expected_state_backend_id,
        expected_artifact_store_id=args.expected_artifact_store_id,
        coordinator_id=args.coordinator_id if coordinator else None,
        adapter_config_resolver_id=resolver.resolver_id,
        state_backend_config_ref=backend_ref,
        artifact_store_config_ref=artifact_ref,
        adapter_config_resolver_capability_sha256=
            resolver.capability_manifest_sha256,
    )
    return source, target


def _migration_preflight(args: argparse.Namespace, *, coordinator: bool) -> tuple[
        dict[str, Any], RemoteCertifierTrustStateStore,
        RemoteCertifierTrustStateStore, dict[str, Any]]:
    source, target = _migration_stores(args, coordinator)
    source_current = source.read()
    if source_current is None:
        raise ValueError("Adapter certifier trust migration source is uninitialized")
    if source_current["pointer"]["schemaVersion"] != 1:
        raise ValueError("Adapter certifier trust migration source is not pointer v1")
    if (source.state_version != args.expected_state_version
            or source_current["policySha256"]
                != args.expected_current_policy_sha256):
        raise ValueError("Adapter certifier trust migration source changed before preflight")
    target_current = target.read_legacy_for_migration(
        source_backend_config_sha256=
            args.expected_source_state_backend_config_sha256,
        source_artifact_store_config_sha256=
            args.expected_source_artifact_store_config_sha256,
    )
    if (target_current["pointer"] != source_current["pointer"]
            or target_current["state"] != source_current["state"]
            or target_current["policy"] != source_current["policy"]
            or target_current["policySha256"] != source_current["policySha256"]
            or target._pointer_sha256 != source._pointer_sha256):
        raise ValueError("Adapter certifier trust source and target views differ")
    checked_at = package_tool.verification_time(
        getattr(args, "verification_time", None)
    ).isoformat()
    preflight = {
        "schemaVersion": 1, "product": MIGRATION_PREFLIGHT_PRODUCT,
        "passed": True, "controlId": args.control_id,
        "trustPolicyId": args.trust_policy_id,
        "sourcePointerSchemaVersion": 1, "targetPointerSchemaVersion": 2,
        "sourceStateVersion": source.state_version,
        "targetStateVersion": source.state_version + 1,
        "sourcePointerSha256": source._pointer_sha256,
        "sourceStateSha256": source_current["pointer"]["stateSha256"],
        "policyGeneration": source_current["policy"]["generation"],
        "policySha256": source_current["policySha256"],
        "stateBackendId": source_current["pointer"]["stateBackendId"],
        "artifactStoreId": source_current["pointer"]["artifactStoreId"],
        "sourceStateBackendConfigSha256":
            source_current["pointer"]["stateBackendConfigSha256"],
        "sourceArtifactStoreConfigSha256":
            source_current["pointer"]["artifactStoreConfigSha256"],
        "targetAdapterConfigResolverId": target.adapter_config_resolver_id,
        "targetStateBackendConfigRef": target.state_backend_config_ref,
        "targetArtifactStoreConfigRef": target.artifact_store_config_ref,
        "targetAdapterConfigResolverCapabilityManifestSha256":
            target.adapter_config_resolver_capability_sha256,
        "checkedAt": checked_at,
    }
    validate_migration_preflight(preflight)
    return preflight, source, target, source_current


def migration_preflight_command(args: argparse.Namespace) -> int:
    try:
        preflight, _, _, _ = _migration_preflight(args, coordinator=False)
        if args.report:
            package_tool.write_json(Path(args.report).resolve(), preflight)
        print("PDR_ADAPTER_CERTIFIER_TRUST_MIGRATION_PREFLIGHT_PASS "
              f"sourceVersion={preflight['sourceStateVersion']} "
              f"targetVersion={preflight['targetStateVersion']} portable=1")
        return 0
    except (OSError, UnicodeError, ValueError, RuntimeError,
            json.JSONDecodeError) as error:
        print(f"PDR_ADAPTER_CERTIFIER_TRUST_MIGRATION_ERROR: {error}", file=sys.stderr)
        return 2


def migration_propose_command(args: argparse.Namespace) -> int:
    try:
        preflight, _, _, _ = _migration_preflight(args, coordinator=False)
        governance = _pinned_document(
            args.governance_policy, args.expected_governance_policy_sha256,
            "Adapter certifier migration governance policy",
            control_tool.validate_governance,
        )
        if governance[0]["policyId"] != args.expected_governance_policy_id:
            raise ValueError("Adapter certifier migration governance identity changed")
        now = package_tool.verification_time(args.issued_at)
        maximum = governance[0]["maxStandardLifetimeSeconds"]
        if not 60 <= args.lifetime_seconds <= maximum:
            raise ValueError("Adapter certifier migration proposal lifetime exceeds governance")
        copied = {
            name: preflight[name] for name in (
                "controlId", "trustPolicyId", "sourceStateVersion",
                "targetStateVersion", "sourcePointerSha256", "sourceStateSha256",
                "policyGeneration", "policySha256", "stateBackendId",
                "artifactStoreId", "sourceStateBackendConfigSha256",
                "sourceArtifactStoreConfigSha256",
                "targetAdapterConfigResolverId", "targetStateBackendConfigRef",
                "targetArtifactStoreConfigRef",
            )
        }
        proposal = {
            "schemaVersion": 1, "product": MIGRATION_PROPOSAL_PRODUCT,
            "operation": "adapter-certifier-trust-state-migrate",
            "proposalId": str(uuid.uuid4()), **copied,
            "governancePolicyId": governance[0]["policyId"],
            "governancePolicySha256": governance[3],
            "proposerId": args.proposer_id, "ticket": args.ticket,
            "reason": args.reason.strip(), "issuedAt": now.isoformat(),
            "expiresAt": (now + timedelta(
                seconds=args.lifetime_seconds)).isoformat(),
        }
        validate_migration_proposal(proposal)
        registry_tool.exclusive_bytes(
            Path(args.output).resolve(), package_tool.json_bytes(proposal)
        )
        print("PDR_ADAPTER_CERTIFIER_TRUST_MIGRATION_PROPOSE_PASS "
              f"proposal={proposal['proposalId']} "
              f"sourceVersion={proposal['sourceStateVersion']}")
        return 0
    except (OSError, UnicodeError, ValueError, RuntimeError,
            json.JSONDecodeError) as error:
        print(f"PDR_ADAPTER_CERTIFIER_TRUST_MIGRATION_ERROR: {error}", file=sys.stderr)
        return 2


def migration_approve_command(args: argparse.Namespace) -> int:
    try:
        proposal = _pinned_document(
            args.proposal, args.expected_proposal_sha256,
            "Adapter certifier trust migration proposal",
            validate_migration_proposal,
        )
        now = package_tool.verification_time(args.verification_time)
        if now >= package_tool.parse_time(
                proposal[0]["expiresAt"], "migration proposal expiresAt"):
            raise ValueError("Adapter certifier trust migration proposal expired")
        approval = approval_tool.sign_governed_approval(
            proposal[2], proposal[3], approver_id=args.approver_id,
            key_id=args.key_id,
            product=MIGRATION_APPROVAL_PRODUCT,
            subject_sha_field="proposalSha256",
            purpose="adapter-certifier-trust-migration-approval",
            private_key_environment=getattr(
                args, "private_key_environment", None),
            signer_config=getattr(args, "signer_config", None),
            expected_signer_config_sha256=getattr(
                args, "expected_signer_config_sha256", None),
            signer_admission_config=getattr(
                args, "signer_admission_config", None),
            expected_signer_admission_config_sha256=getattr(
                args, "expected_signer_admission_config_sha256", None),
            verification_time=now,
        )
        validate_migration_approval(approval)
        registry_tool.exclusive_bytes(
            Path(args.output).resolve(), package_tool.json_bytes(approval)
        )
        print("PDR_ADAPTER_CERTIFIER_TRUST_MIGRATION_APPROVE_PASS "
              f"proposal={proposal[0]['proposalId']} approver={args.approver_id}")
        return 0
    except (OSError, UnicodeError, ValueError, RuntimeError,
            json.JSONDecodeError) as error:
        print(f"PDR_ADAPTER_CERTIFIER_TRUST_MIGRATION_ERROR: {error}", file=sys.stderr)
        return 2


def _verify_migration_approvals(
        proposal: tuple[dict[str, Any], Path, bytes, str],
        governance: dict[str, Any], key_directory: Path,
        paths: list[str], at: Any,
        executor_id: str, args: argparse.Namespace) \
        -> tuple[list[dict[str, str]], tuple[dict[str, Any], str] | None]:
    loaded: list[tuple[dict[str, Any], Path, bytes, str]] = []
    for value in paths:
        approval = _pinned_document(
            value, package_tool.sha256_bytes(Path(value).resolve().read_bytes()),
            "Adapter certifier trust migration approval",
            validate_migration_approval,
        )
        loaded.append(approval)
    verified = approval_tool.verify_ed25519_quorum(
        subject_content=proposal[2], subject_sha256=proposal[3],
        initiator_id=proposal[0]["proposerId"], executor_id=executor_id,
        required_role="standard",
        minimum_approvals=governance["standardMinimumApprovals"],
        allowed_approvers=governance["allowedApprovers"],
        allowed_executor_ids=governance["activatorIds"],
        revoked_keys=governance["revokedKeys"], approvals=loaded,
        approval_validator=validate_migration_approval,
        subject_sha_field="proposalSha256",
        trusted_keys_directory=key_directory, verification_time=at,
        external_signer_purpose=
            "adapter-certifier-trust-migration-approval",
    )
    import team_contract_governance_approval_signer_admission \
        as admission_tool
    readmission = admission_tool.enforce_readmission(
        loaded,
        bundle_path=getattr(args, "signer_readmission_bundle", None),
        expected_bundle_sha256=getattr(
            args, "expected_signer_readmission_bundle_sha256", None),
        report_path=getattr(args, "signer_readmission_report", None),
        purpose="adapter-certifier-trust-migration-approval",
        subject_sha256=proposal[3], executor_id=executor_id,
        verification_time=at,
    )
    return verified, readmission


def _verify_migration_activation(
        args: argparse.Namespace, preflight: dict[str, Any]) \
        -> tuple[tuple[dict[str, Any], Path, bytes, str], dict[str, Any]]:
    governance = _pinned_document(
        args.governance_policy, args.expected_governance_policy_sha256,
        "Adapter certifier migration governance policy",
        control_tool.validate_governance,
    )
    if governance[0]["policyId"] != args.expected_governance_policy_id:
        raise ValueError("Adapter certifier migration governance identity changed")
    proposal = _pinned_document(
        args.proposal, args.expected_proposal_sha256,
        "Adapter certifier trust migration proposal",
        validate_migration_proposal,
    )
    now = package_tool.verification_time(args.verification_time)
    issued = package_tool.parse_time(proposal[0]["issuedAt"], "migration issuedAt")
    expires = package_tool.parse_time(proposal[0]["expiresAt"], "migration expiresAt")
    if (issued > now + timedelta(minutes=5) or now >= expires
            or (expires - issued).total_seconds()
                > governance[0]["maxStandardLifetimeSeconds"]
            or proposal[0]["governancePolicyId"] != governance[0]["policyId"]
            or proposal[0]["governancePolicySha256"] != governance[3]):
        raise ValueError("Adapter certifier trust migration proposal is expired or stale")
    expected = {
        name: preflight[name] for name in (
            "controlId", "trustPolicyId", "sourceStateVersion",
            "targetStateVersion", "sourcePointerSha256", "sourceStateSha256",
            "policyGeneration", "policySha256", "stateBackendId",
            "artifactStoreId", "sourceStateBackendConfigSha256",
            "sourceArtifactStoreConfigSha256", "targetAdapterConfigResolverId",
            "targetStateBackendConfigRef", "targetArtifactStoreConfigRef",
        )
    }
    if any(proposal[0][name] != value for name, value in expected.items()):
        raise ValueError("Adapter certifier trust migration proposal inputs changed")
    approvals, readmission = _verify_migration_approvals(
        proposal, governance[0], Path(args.trusted_keys_directory).resolve(),
        args.approval, now, args.activator_id, args,
    )
    if (args.activator_id not in governance[0]["activatorIds"]
            or args.activator_id == proposal[0]["proposerId"]
            or args.activator_id in {item["approverId"] for item in approvals}):
        raise ValueError("Adapter certifier trust migration activator is not separated")
    report = {
        "schemaVersion": 2 if readmission else 1,
        "product": MIGRATION_REPORT_PRODUCT,
        "passed": True, "proposalId": proposal[0]["proposalId"],
        "proposalSha256": proposal[3], "operationId": args.operation_id,
        **expected,
        "governancePolicyId": governance[0]["policyId"],
        "governancePolicySha256": governance[3],
        "proposerId": proposal[0]["proposerId"],
        "activatorId": args.activator_id, "approvals": approvals,
        "migratedAt": now.isoformat(),
    }
    if readmission:
        report["signerReadmissionEvidenceSha256"] = readmission[1]
    validate_migration_report(report)
    return proposal, report


def migration_activate_command(args: argparse.Namespace) -> int:
    try:
        source, target = _migration_stores(args, True)
        raw = target.backend.current()
        if raw is not None and raw[0].get("schemaVersion") == 2:
            current = target.read()
            assert current is not None
            proposal = _pinned_document(
                args.proposal, args.expected_proposal_sha256,
                "Adapter certifier trust migration proposal",
                validate_migration_proposal,
            )
            evidence = current["migration"]
            if (current["state"]["action"] != "migrate" or evidence is None
                    or current["state"]["operationId"] != args.operation_id
                    or evidence["proposalSha256"] != proposal[3]
                    or evidence["activatorId"] != args.activator_id):
                raise ValueError("Adapter certifier trust migration already completed differently")
            if args.report:
                package_tool.write_json(Path(args.report).resolve(), evidence)
            _write_status(args.status_report, current)
            print("PDR_ADAPTER_CERTIFIER_TRUST_MIGRATION_ACTIVATE_PASS "
                  f"stateVersion={current['state']['stateVersion']} "
                  "pointerV2=1 idempotent=1")
            return 0
        preflight, source, target, _ = _migration_preflight(
            args, coordinator=True
        )
        _, report = _verify_migration_activation(args, preflight)
        committed = target.migrate(
            report, expected_state_version=preflight["sourceStateVersion"],
            expected_source_pointer_sha256=preflight["sourcePointerSha256"],
            expected_current_policy_sha256=preflight["policySha256"],
            operation_id=args.operation_id, actor=args.activator_id,
        )
        verified = target.read()
        if (verified is None or verified["pointer"] != committed["pointer"]
                or verified["migration"] != report):
            raise ValueError("Adapter certifier trust migration post-commit verification failed")
        if args.report:
            package_tool.write_json(Path(args.report).resolve(), report)
        _write_status(args.status_report, verified)
        print("PDR_ADAPTER_CERTIFIER_TRUST_MIGRATION_ACTIVATE_PASS "
              f"stateVersion={verified['state']['stateVersion']} "
              f"approvals={len(report['approvals'])} pointerV2=1 idempotent=0")
        return 0
    except (OSError, UnicodeError, ValueError, RuntimeError,
            json.JSONDecodeError) as error:
        print(f"PDR_ADAPTER_CERTIFIER_TRUST_MIGRATION_ERROR: {error}", file=sys.stderr)
        return 2


def initialize_command(args: argparse.Namespace) -> int:
    try:
        _, policy_path, _ = adapter_runtime.load_pinned_json(
            args.policy, args.expected_policy_sha256,
            "initial Adapter certifier trust policy", trust_tool.validate_policy,
        )
        store = _store(args, True)
        if store.read() is not None:
            raise ValueError("Adapter certifier trust remote state already exists")
        current = store.initialize(policy_path.read_bytes(), operation_id=args.operation_id,
                                   actor=args.actor)
        _write_status(args.report, current)
        print("PDR_ADAPTER_CERTIFIER_TRUST_REMOTE_INITIALIZE_PASS "
              f"stateVersion=1 generation={current['policy']['generation']}")
        return 0
    except (OSError, UnicodeError, ValueError, RuntimeError,
            json.JSONDecodeError) as error:
        print(f"PDR_ADAPTER_CERTIFIER_TRUST_STATE_ERROR: {error}", file=sys.stderr)
        return 2


def _write_status(path_value: str | None, current: dict[str, Any]) -> dict[str, Any]:
    status = {
        "schemaVersion": 1, "product": STATUS_PRODUCT, "passed": True,
        "controlId": current["state"]["controlId"],
        "trustPolicyId": current["policy"]["policyId"],
        "stateVersion": current["state"]["stateVersion"],
        "fencingToken": current["pointer"]["fencingToken"],
        "policyGeneration": current["policy"]["generation"],
        "policySha256": current["policySha256"],
        "operationId": current["state"]["operationId"],
        "coordinatorId": current["pointer"]["coordinatorId"],
        "actor": current["state"]["actor"], "mode": current["state"]["mode"],
        "activationProposalId": current["activation"]["proposalId"]
            if current["activation"] else None,
        "pointerSchemaVersion": current["pointer"]["schemaVersion"],
        "adapterConfigResolverId": current["pointer"].get(
            "adapterConfigResolverId"),
        "stateBackendConfigRef": current["pointer"].get(
            "stateBackendConfigRef"),
        "artifactStoreConfigRef": current["pointer"].get(
            "artifactStoreConfigRef"),
        "adapterConfigResolverCapabilityManifestSha256": current[
            "adapterConfigResolverCapabilityManifestSha256"],
        "updatedAt": current["pointer"]["updatedAt"],
    }
    validate_status(status)
    if path_value:
        package_tool.write_json(Path(path_value).resolve(), status)
    return status


def status_command(args: argparse.Namespace) -> int:
    try:
        store = _store(args, False)
        current = store.read()
        if current is None:
            raise ValueError("Adapter certifier trust remote state is uninitialized")
        if args.expected_state_version is not None \
                and store.state_version != args.expected_state_version:
            raise ValueError("Adapter certifier trust remote state version changed")
        if args.expected_policy_sha256 \
                and current["policySha256"] != args.expected_policy_sha256:
            raise ValueError("Adapter certifier trust remote policy SHA changed")
        if args.export_policy:
            output = Path(args.export_policy).resolve()
            if output.exists():
                raise ValueError("Adapter certifier trust policy export already exists")
            registry_tool.exclusive_bytes(output, current["policyBytes"])
        status = _write_status(args.report, current)
        print("PDR_ADAPTER_CERTIFIER_TRUST_REMOTE_STATUS_PASS "
              f"stateVersion={status['stateVersion']} "
              f"generation={status['policyGeneration']}")
        return 0
    except (OSError, UnicodeError, ValueError, RuntimeError,
            json.JSONDecodeError) as error:
        print(f"PDR_ADAPTER_CERTIFIER_TRUST_STATE_ERROR: {error}", file=sys.stderr)
        return 2


def propose_command(args: argparse.Namespace) -> int:
    try:
        store = _store(args, False)
        current = store.read()
        if current is None:
            raise ValueError("Adapter certifier trust remote state is uninitialized")
        if (store.state_version != args.expected_state_version
                or current["policySha256"] != args.expected_current_policy_sha256):
            raise ValueError("Adapter certifier trust remote state changed before proposal")
        with tempfile.TemporaryDirectory(prefix="pdr-certifier-trust-propose-") as directory:
            active = Path(directory) / "active-policy.json"
            active.write_bytes(current["policyBytes"])
            forwarded = argparse.Namespace(**vars(args))
            forwarded.active_policy = str(active)
            return control_tool.propose_command(forwarded)
    except (OSError, UnicodeError, ValueError, RuntimeError,
            json.JSONDecodeError) as error:
        print(f"PDR_ADAPTER_CERTIFIER_TRUST_STATE_ERROR: {error}", file=sys.stderr)
        return 2


def activate_command(args: argparse.Namespace) -> int:
    try:
        store = _store(args, True)
        current = store.read()
        if current is None:
            raise ValueError("Adapter certifier trust remote state is uninitialized")
        if (store.state_version != args.expected_state_version
                or current["policySha256"] != args.expected_current_policy_sha256):
            raise ValueError("Adapter certifier trust remote state changed before activation")
        with tempfile.TemporaryDirectory(prefix="pdr-certifier-trust-activate-") as directory:
            active = Path(directory) / "active-policy.json"
            active.write_bytes(current["policyBytes"])
            forwarded = argparse.Namespace(**vars(args))
            forwarded.active_policy = str(active)
            verified_current, candidate, activation = control_tool.verify_activation(forwarded)
            if (verified_current[3] != current["policySha256"]
                    or verified_current[0] != current["policy"]):
                raise ValueError("Adapter certifier trust remote verification input changed")
            committed = store.activate(
                candidate[2], activation,
                expected_state_version=args.expected_state_version,
                expected_current_policy_sha256=args.expected_current_policy_sha256,
                operation_id=args.operation_id, actor=args.activator_id,
            )
        if args.report:
            package_tool.write_json(Path(args.report).resolve(), activation)
        _write_status(args.status_report, committed)
        print("PDR_ADAPTER_CERTIFIER_TRUST_REMOTE_ACTIVATE_PASS "
              f"stateVersion={store.state_version} generation={activation['generation']} "
              f"coordinator={args.coordinator_id}")
        return 0
    except (OSError, UnicodeError, ValueError, RuntimeError,
            json.JSONDecodeError) as error:
        print(f"PDR_ADAPTER_CERTIFIER_TRUST_STATE_ERROR: {error}", file=sys.stderr)
        return 2


def add_store_arguments(command: argparse.ArgumentParser, *, coordinator: bool) -> None:
    command.add_argument("--state-backend-config")
    command.add_argument("--expected-state-backend-config-sha256")
    command.add_argument("--expected-state-backend-id", required=True)
    command.add_argument("--artifact-store-config")
    command.add_argument("--expected-artifact-store-config-sha256")
    command.add_argument("--expected-artifact-store-id", required=True)
    command.add_argument("--adapter-config-resolver-config")
    command.add_argument("--expected-adapter-config-resolver-config-sha256")
    command.add_argument("--expected-adapter-config-resolver-id")
    command.add_argument("--state-backend-config-ref")
    command.add_argument("--expected-state-backend-config-ref-sha256")
    command.add_argument("--artifact-store-config-ref")
    command.add_argument("--expected-artifact-store-config-ref-sha256")
    command.add_argument("--control-id", required=True)
    command.add_argument("--trust-policy-id", required=True)
    if coordinator:
        command.add_argument("--coordinator-id", required=True)


def add_migration_arguments(command: argparse.ArgumentParser, *,
                            coordinator: bool) -> None:
    command.add_argument("--source-state-backend-config", required=True)
    command.add_argument(
        "--expected-source-state-backend-config-sha256", required=True
    )
    command.add_argument("--source-artifact-store-config", required=True)
    command.add_argument(
        "--expected-source-artifact-store-config-sha256", required=True
    )
    command.add_argument("--expected-state-backend-id", required=True)
    command.add_argument("--expected-artifact-store-id", required=True)
    command.add_argument("--target-adapter-config-resolver-config", required=True)
    command.add_argument(
        "--expected-target-adapter-config-resolver-config-sha256", required=True
    )
    command.add_argument("--expected-target-adapter-config-resolver-id", required=True)
    command.add_argument("--target-state-backend-config-ref", required=True)
    command.add_argument(
        "--expected-target-state-backend-config-ref-sha256", required=True
    )
    command.add_argument("--target-artifact-store-config-ref", required=True)
    command.add_argument(
        "--expected-target-artifact-store-config-ref-sha256", required=True
    )
    command.add_argument("--control-id", required=True)
    command.add_argument("--trust-policy-id", required=True)
    command.add_argument("--expected-state-version", type=int, required=True)
    command.add_argument("--expected-current-policy-sha256", required=True)
    if coordinator:
        command.add_argument("--coordinator-id", required=True)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    initialize = commands.add_parser("initialize")
    add_store_arguments(initialize, coordinator=True)
    initialize.add_argument("--policy", required=True)
    initialize.add_argument("--expected-policy-sha256", required=True)
    initialize.add_argument("--operation-id", required=True)
    initialize.add_argument("--actor", required=True)
    initialize.add_argument("--report")
    initialize.set_defaults(handler=initialize_command)
    status = commands.add_parser("status")
    add_store_arguments(status, coordinator=False)
    status.add_argument("--expected-state-version", type=int)
    status.add_argument("--expected-policy-sha256")
    status.add_argument("--export-policy")
    status.add_argument("--report")
    status.set_defaults(handler=status_command)
    propose = commands.add_parser("propose")
    add_store_arguments(propose, coordinator=False)
    propose.add_argument("--expected-state-version", type=int, required=True)
    propose.add_argument("--expected-current-policy-sha256", required=True)
    propose.add_argument("--candidate-policy", required=True)
    propose.add_argument("--expected-candidate-policy-sha256", required=True)
    propose.add_argument("--governance-policy", required=True)
    propose.add_argument("--expected-governance-policy-id", required=True)
    propose.add_argument("--expected-governance-policy-sha256", required=True)
    propose.add_argument(
        "--mode", choices=("standard", "emergency-revocation"),
        default="standard",
    )
    propose.add_argument("--proposer-id", required=True)
    propose.add_argument("--ticket", required=True)
    propose.add_argument("--reason", required=True)
    propose.add_argument("--issued-at")
    propose.add_argument("--lifetime-seconds", type=int, default=3600)
    propose.add_argument("--output", required=True)
    propose.set_defaults(handler=propose_command)
    activate = commands.add_parser("activate")
    add_store_arguments(activate, coordinator=True)
    activate.add_argument("--expected-state-version", type=int, required=True)
    activate.add_argument("--expected-current-policy-sha256", required=True)
    activate.add_argument("--candidate-policy", required=True)
    activate.add_argument("--expected-candidate-policy-sha256", required=True)
    activate.add_argument("--proposal", required=True)
    activate.add_argument("--expected-proposal-sha256", required=True)
    activate.add_argument("--approval", action="append", required=True)
    activate.add_argument("--governance-policy", required=True)
    activate.add_argument("--expected-governance-policy-id", required=True)
    activate.add_argument("--expected-governance-policy-sha256", required=True)
    activate.add_argument("--trusted-keys-directory", required=True)
    activate.add_argument("--activator-id", required=True)
    activate.add_argument("--verification-time")
    activate.add_argument("--operation-id", required=True)
    activate.add_argument("--report")
    activate.add_argument("--status-report")
    activate.set_defaults(handler=activate_command)
    migration_preflight = commands.add_parser("migration-preflight")
    add_migration_arguments(migration_preflight, coordinator=False)
    migration_preflight.add_argument("--verification-time")
    migration_preflight.add_argument("--report")
    migration_preflight.set_defaults(handler=migration_preflight_command)
    migration_propose = commands.add_parser("migration-propose")
    add_migration_arguments(migration_propose, coordinator=False)
    migration_propose.add_argument("--governance-policy", required=True)
    migration_propose.add_argument("--expected-governance-policy-id", required=True)
    migration_propose.add_argument(
        "--expected-governance-policy-sha256", required=True
    )
    migration_propose.add_argument("--proposer-id", required=True)
    migration_propose.add_argument("--ticket", required=True)
    migration_propose.add_argument("--reason", required=True)
    migration_propose.add_argument("--issued-at")
    migration_propose.add_argument("--verification-time")
    migration_propose.add_argument("--lifetime-seconds", type=int, default=3600)
    migration_propose.add_argument("--output", required=True)
    migration_propose.set_defaults(handler=migration_propose_command)
    migration_approve = commands.add_parser("migration-approve")
    migration_approve.add_argument("--proposal", required=True)
    migration_approve.add_argument("--expected-proposal-sha256", required=True)
    migration_approve.add_argument("--approver-id", required=True)
    migration_approve.add_argument("--key-id", required=True)
    migration_approve.add_argument("--private-key-environment")
    migration_approve.add_argument("--signer-config")
    migration_approve.add_argument("--expected-signer-config-sha256")
    migration_approve.add_argument("--signer-admission-config")
    migration_approve.add_argument(
        "--expected-signer-admission-config-sha256"
    )
    migration_approve.add_argument("--verification-time")
    migration_approve.add_argument("--output", required=True)
    migration_approve.set_defaults(handler=migration_approve_command)
    migration_activate = commands.add_parser("migration-activate")
    add_migration_arguments(migration_activate, coordinator=True)
    migration_activate.add_argument("--proposal", required=True)
    migration_activate.add_argument("--expected-proposal-sha256", required=True)
    migration_activate.add_argument("--approval", action="append", required=True)
    migration_activate.add_argument("--governance-policy", required=True)
    migration_activate.add_argument("--expected-governance-policy-id", required=True)
    migration_activate.add_argument(
        "--expected-governance-policy-sha256", required=True
    )
    migration_activate.add_argument("--trusted-keys-directory", required=True)
    migration_activate.add_argument("--activator-id", required=True)
    migration_activate.add_argument("--operation-id", required=True)
    migration_activate.add_argument("--verification-time")
    migration_activate.add_argument("--signer-readmission-bundle")
    migration_activate.add_argument(
        "--expected-signer-readmission-bundle-sha256"
    )
    migration_activate.add_argument("--signer-readmission-report")
    migration_activate.add_argument("--report")
    migration_activate.add_argument("--status-report")
    migration_activate.set_defaults(handler=migration_activate_command)
    return result


def main() -> int:
    args = parser().parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
