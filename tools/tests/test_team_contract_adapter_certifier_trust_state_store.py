#!/usr/bin/env python3
"""Cross-Host recovery tests for Adapter certifier trust state."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import team_contract_adapter_certifier_trust_control as control
import team_contract_adapter_certifier_trust_state_store as state_tool
import team_contract_package as package_tool
import team_contract_registry_leader_backend as backend_tool


NOW = "2026-08-27T12:00:00+00:00"
RESOLVER_EXAMPLE = ROOT / "examples" / "team-contract-adapter-config-resolver-file"
RESOLVER_GENERATOR = RESOLVER_EXAMPLE / "create_resolver_config.py"
RESOLVER_ADAPTER = RESOLVER_EXAMPLE / "file_adapter_config_resolver_adapter.py"


class MemoryBackend:
    def __init__(self) -> None:
        self.backend_id = "certifier-state-backend"
        self.capability_manifest_sha256 = "b" * 64
        self.value: tuple[dict, bytes, str] | None = None
        self.history: dict[tuple[int, str], tuple[dict, bytes, str]] = {}
        self.uncertain_after_commit = False

    def current(self):
        if self.value is None:
            return None
        return copy.deepcopy(self.value[0]), self.value[1], self.value[2]

    def grant(self, token: int, digest: str):
        value = self.history.get((token, digest))
        if value is None:
            raise ValueError("simulated missing pointer history")
        return copy.deepcopy(value[0]), value[1], value[2]

    def compare_and_swap(self, expected_token, expected_sha256,
                         document, content, digest):
        actual_token = 0 if self.value is None else self.value[0]["fencingToken"]
        actual_sha = backend_tool.ZERO_SHA256 if self.value is None else self.value[2]
        if (expected_token, expected_sha256) != (actual_token, actual_sha):
            raise ValueError("simulated CAS conflict")
        self.value = (copy.deepcopy(document), content, digest)
        self.history[(document["fencingToken"], digest)] = self.value
        if self.uncertain_after_commit:
            self.uncertain_after_commit = False
            raise backend_tool.BackendCommitUncertainError("simulated lost CAS response")


class MemoryArtifactStore:
    def __init__(self) -> None:
        self.store_id = "certifier-artifacts"
        self.capability_manifest_sha256 = "a" * 64
        self.values: dict[str, bytes] = {}

    def put(self, content: bytes, media_type: str):
        digest = package_tool.sha256_bytes(content)
        self.values.setdefault(digest, content)
        return {
            "kind": "content-addressed", "storeId": self.store_id,
            "namespaceId": "certifier-control", "sha256": digest,
            "sizeBytes": len(content), "mediaType": media_type,
        }

    def get(self, reference):
        if (reference.get("storeId") != self.store_id
                or reference.get("namespaceId") != "certifier-control"):
            raise ValueError("simulated artifact scope mismatch")
        content = self.values.get(reference["sha256"])
        if content is None:
            raise ValueError("simulated missing artifact")
        return content


def write_json(path: Path, document: dict) -> str:
    path.write_bytes(package_tool.json_bytes(document))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def key_pair(directory: Path, identity: str) -> tuple[Path, str]:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import (
        Encoding, NoEncryption, PrivateFormat, PublicFormat,
    )
    key = Ed25519PrivateKey.generate()
    private = directory / f"{identity}.private.pem"
    public = directory / f"{identity}.pem"
    private.write_bytes(key.private_bytes(
        Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()
    ))
    public.write_bytes(key.public_key().public_bytes(
        Encoding.PEM, PublicFormat.SubjectPublicKeyInfo
    ))
    return private, hashlib.sha256(public.read_bytes()).hexdigest()


def policy(generation: int, adapter_ids: list[str] | None = None) -> dict:
    return {
        "schemaVersion": 1,
        "product": "PocoDDSRuntimeTeamContractAdapterConformanceTrustPolicy",
        "policyId": "production-certifiers", "generation": generation,
        "maximumAttestationLifetimeSeconds": 3600,
        "allowedCertifiers": [{
            "certifierId": "release-certifier", "keyId": "certifier-key-1",
            "algorithm": "Ed25519", "publicKey": "keys/certifier-key-1.pem",
            "publicKeySha256": "1" * 64,
            "adapterKinds": ["fleet-executor"],
            "adapterIds": sorted(adapter_ids or ["fleet-prod"]),
            "notBefore": "2026-01-01T00:00:00+00:00",
            "notAfter": "2027-01-01T00:00:00+00:00",
        }], "revokedKeys": [],
    }


def activation(previous_sha: str, candidate_sha: str,
               previous_generation: int, generation: int,
               proposal_id: str) -> dict:
    result = {
        "schemaVersion": 1, "product": control.PRODUCT + "ActivationReport",
        "passed": True, "proposalId": proposal_id, "mode": "standard",
        "trustPolicyId": "production-certifiers",
        "previousGeneration": previous_generation,
        "previousPolicySha256": previous_sha, "generation": generation,
        "policySha256": candidate_sha,
        "governancePolicyId": "certifier-governance",
        "governancePolicySha256": "2" * 64,
        "proposerId": "release-author", "activatorId": "release-operator",
        "approvals": [
            {"approverId": "security-a", "keyId": "approval-key-a",
             "approvalSha256": "3" * 64},
            {"approverId": "security-b", "keyId": "approval-key-b",
             "approvalSha256": "4" * 64},
        ], "emergencyRevokedKeyIds": [], "activatedAt": NOW,
    }
    control.validate_activation_report(result)
    return result


class TrustStateStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.backend = MemoryBackend()
        self.artifacts = MemoryArtifactStore()
        self.backend_paths: list[Path] = []
        self.artifact_paths: list[Path] = []

        def backend_factory(*args):
            self.backend_paths.append(Path(args[0]).resolve())
            return self.backend

        def artifact_factory(*args):
            self.artifact_paths.append(Path(args[0]).resolve())
            return self.artifacts

        self.backend_patch = mock.patch.object(
            state_tool.backend_tool, "ExternalCommandBackend",
            side_effect=backend_factory,
        )
        self.artifact_patch = mock.patch.object(
            state_tool.artifact_store_tool, "ExternalCommandArtifactStore",
            side_effect=artifact_factory,
        )
        self.backend_patch.start()
        self.artifact_patch.start()

    def tearDown(self) -> None:
        self.artifact_patch.stop()
        self.backend_patch.stop()

    def store(self, coordinator: str | None) -> state_tool.RemoteCertifierTrustStateStore:
        return state_tool.RemoteCertifierTrustStateStore(
            state_backend_config="backend.json",
            state_backend_config_sha256="5" * 64,
            artifact_store_config="artifact.json",
            artifact_store_config_sha256="6" * 64,
            control_id="certifier-control", trust_policy_id="production-certifiers",
            expected_backend_id="certifier-state-backend",
            expected_artifact_store_id="certifier-artifacts",
            coordinator_id=coordinator,
        )

    def create_resolver_host(self, root: Path, host: str) \
            -> tuple[Path, Path, Path]:
        directory = root / host
        directory.mkdir()
        backend = directory / "backend.json"
        artifact = directory / "artifact.json"
        write_json(backend, {
            "schemaVersion": 2,
            "product": "PocoDDSRuntimeTeamContractRegistryLeaderBackendConfig",
            "backendId": "certifier-state-backend", "hostMarker": host,
        })
        write_json(artifact, {
            "schemaVersion": 1,
            "product": "PocoDDSRuntimeTeamContractArtifactStoreConfig",
            "storeId": "certifier-artifacts", "hostMarker": host,
        })
        mapping = directory / "mapping.json"
        config = directory / "resolver.json"
        completed = subprocess.run([
            sys.executable, str(RESOLVER_GENERATOR),
            "--python", str(Path(sys.executable).resolve()),
            "--adapter", str(RESOLVER_ADAPTER.resolve()),
            "--resolver-id", "trust-config-resolver",
            "--scope", "adapter-certifier-trust-state",
            "certifier-control", "production-certifiers",
            "--entry", "trust.backend", "rev-1",
            "registry-leader-backend", str(backend.resolve()),
            "--entry", "trust.artifacts", "rev-1",
            "artifact-store", str(artifact.resolve()),
            "--mapping-output", str(mapping.resolve()),
            "--output", str(config.resolve()),
        ], capture_output=True, text=True, check=False)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        return config, backend, artifact

    @staticmethod
    def portable_reference(kind: str) -> dict:
        return {
            "kind": "adapter-config-ref", "resolverId": "trust-config-resolver",
            "configId": "trust.backend" if kind == "registry-leader-backend"
                else "trust.artifacts",
            "adapterKind": kind,
            "adapterId": "certifier-state-backend"
                if kind == "registry-leader-backend" else "certifier-artifacts",
            "revision": "rev-1",
        }

    def portable_args(self, resolver_config: Path, backend_ref: Path,
                      artifact_ref: Path, coordinator: str | None) -> Namespace:
        return Namespace(
            state_backend_config=None,
            expected_state_backend_config_sha256=None,
            artifact_store_config=None,
            expected_artifact_store_config_sha256=None,
            expected_state_backend_id="certifier-state-backend",
            expected_artifact_store_id="certifier-artifacts",
            adapter_config_resolver_config=str(resolver_config),
            expected_adapter_config_resolver_config_sha256=
                hashlib.sha256(resolver_config.read_bytes()).hexdigest(),
            expected_adapter_config_resolver_id="trust-config-resolver",
            state_backend_config_ref=str(backend_ref),
            expected_state_backend_config_ref_sha256=
                hashlib.sha256(backend_ref.read_bytes()).hexdigest(),
            artifact_store_config_ref=str(artifact_ref),
            expected_artifact_store_config_ref_sha256=
                hashlib.sha256(artifact_ref.read_bytes()).hexdigest(),
            control_id="certifier-control",
            trust_policy_id="production-certifiers",
            coordinator_id=coordinator,
        )

    def test_cross_host_takeover_fencing_and_ambiguous_commit(self) -> None:
        host_a = self.store("host-a")
        host_b = self.store("host-b")
        self.assertIsNone(host_a.read())
        initial_bytes = package_tool.json_bytes(policy(1))
        first = host_a.initialize(initial_bytes, operation_id="bootstrap-1",
                                  actor="release-operator")
        self.assertEqual(first["state"]["stateVersion"], 1)

        loaded = host_b.read()
        assert loaded is not None
        candidate_bytes = package_tool.json_bytes(policy(2, ["fleet-prod", "fleet-stage"]))
        candidate_sha = package_tool.sha256_bytes(candidate_bytes)
        evidence = activation(loaded["policySha256"], candidate_sha, 1, 2, "proposal-2")
        second = host_b.activate(
            candidate_bytes, evidence, expected_state_version=1,
            expected_current_policy_sha256=loaded["policySha256"],
            operation_id="activate-2", actor="release-operator",
        )
        self.assertEqual(second["policy"]["generation"], 2)

        stale_candidate = package_tool.json_bytes(policy(2, ["fleet-prod", "fleet-old"]))
        stale_evidence = activation(
            first["policySha256"], package_tool.sha256_bytes(stale_candidate),
            1, 2, "proposal-stale",
        )
        with self.assertRaisesRegex(ValueError, "CAS conflict"):
            host_a.activate(
                stale_candidate, stale_evidence, expected_state_version=1,
                expected_current_policy_sha256=first["policySha256"],
                operation_id="activate-stale", actor="release-operator",
            )

        host_c = self.store("host-c")
        current = host_c.read()
        assert current is not None
        candidate_three = package_tool.json_bytes(
            policy(3, ["fleet-prod", "fleet-stage", "fleet-west"])
        )
        evidence_three = activation(
            current["policySha256"], package_tool.sha256_bytes(candidate_three),
            2, 3, "proposal-3",
        )
        self.backend.uncertain_after_commit = True
        host_c.activate(
            candidate_three, evidence_three, expected_state_version=2,
            expected_current_policy_sha256=current["policySha256"],
            operation_id="activate-3", actor="release-operator",
        )
        recovered = self.store(None).read()
        assert recovered is not None
        self.assertEqual(recovered["policy"]["generation"], 3)
        self.assertEqual(recovered["state"]["previousStateSha256"],
                         second["pointer"]["stateSha256"])

    def test_artifact_tamper_fails_closed(self) -> None:
        writer = self.store("host-a")
        committed = writer.initialize(
            package_tool.json_bytes(policy(1)), operation_id="bootstrap-tamper",
            actor="release-operator",
        )
        digest = committed["state"]["policyRef"]["sha256"]
        self.artifacts.values[digest] = b"{}\n"
        with self.assertRaisesRegex(ValueError, "policy artifact changed"):
            self.store(None).read()

    def test_missing_history_and_activation_tamper_fail_closed(self) -> None:
        host_a = self.store("host-a")
        first = host_a.initialize(
            package_tool.json_bytes(policy(1)), operation_id="bootstrap-history",
            actor="release-operator",
        )
        host_b = self.store("host-b")
        current = host_b.read()
        assert current is not None
        candidate = package_tool.json_bytes(
            policy(2, ["fleet-prod", "fleet-stage"])
        )
        evidence = activation(
            current["policySha256"], package_tool.sha256_bytes(candidate),
            1, 2, "proposal-history",
        )
        committed = host_b.activate(
            candidate, evidence, expected_state_version=1,
            expected_current_policy_sha256=current["policySha256"],
            operation_id="activate-history", actor="release-operator",
        )
        activation_digest = committed["state"]["activationRef"]["sha256"]
        original_activation = self.artifacts.values[activation_digest]
        self.artifacts.values[activation_digest] = b"{}\n"
        with self.assertRaisesRegex(ValueError, "activation evidence changed"):
            self.store(None).read()
        self.artifacts.values[activation_digest] = original_activation
        first_pointer_sha = package_tool.sha256_bytes(
            package_tool.json_bytes(first["pointer"])
        )
        self.backend.history.pop((1, first_pointer_sha))
        with self.assertRaisesRegex(ValueError, "missing pointer history"):
            self.store(None).read()

    def test_remote_commands_verify_real_two_person_approvals(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            keys = work / "keys"
            keys.mkdir()
            private_a, public_a = key_pair(keys, "approval-key-a")
            private_b, public_b = key_pair(keys, "approval-key-b")
            governance = work / "governance.json"
            governance_sha = write_json(governance, {
                "schemaVersion": 1, "product": control.GOVERNANCE_PRODUCT,
                "policyId": "certifier-governance",
                "standardMinimumApprovals": 2,
                "emergencyMinimumApprovals": 1,
                "maxStandardLifetimeSeconds": 7200,
                "maxEmergencyLifetimeSeconds": 900,
                "allowedApprovers": [
                    {"approverId": "security-a", "keyId": "approval-key-a",
                     "algorithm": "Ed25519", "publicKeySha256": public_a,
                     "roles": ["emergency-revocation", "standard"]},
                    {"approverId": "security-b", "keyId": "approval-key-b",
                     "algorithm": "Ed25519", "publicKeySha256": public_b,
                     "roles": ["standard"]},
                ], "activatorIds": ["release-operator"], "revokedKeys": [],
            })
            initial_path = work / "initial.json"
            initial_sha = write_json(initial_path, policy(1))
            common = {
                "state_backend_config": "backend.json",
                "expected_state_backend_config_sha256": "5" * 64,
                "expected_state_backend_id": "certifier-state-backend",
                "artifact_store_config": "artifact.json",
                "expected_artifact_store_config_sha256": "6" * 64,
                "expected_artifact_store_id": "certifier-artifacts",
                "control_id": "certifier-control",
                "trust_policy_id": "production-certifiers",
            }
            self.assertEqual(state_tool.initialize_command(Namespace(
                **common, coordinator_id="host-a", policy=str(initial_path),
                expected_policy_sha256=initial_sha,
                operation_id="bootstrap-command", actor="release-operator",
                report=str(work / "initial-status.json"),
            )), 0)
            candidate_path = work / "candidate.json"
            candidate_sha = write_json(
                candidate_path, policy(2, ["fleet-prod", "fleet-stage"])
            )
            proposal_path = work / "proposal.json"
            self.assertEqual(state_tool.propose_command(Namespace(
                **common, expected_state_version=1,
                expected_current_policy_sha256=initial_sha,
                candidate_policy=str(candidate_path),
                expected_candidate_policy_sha256=candidate_sha,
                governance_policy=str(governance),
                expected_governance_policy_id="certifier-governance",
                expected_governance_policy_sha256=governance_sha,
                mode="standard", proposer_id="release-author",
                ticket="SEC-REMOTE-1", reason="remote key rotation",
                issued_at=NOW, lifetime_seconds=3600,
                output=str(proposal_path),
            )), 0)
            proposal_sha = hashlib.sha256(proposal_path.read_bytes()).hexdigest()
            approvals: list[Path] = []
            for person, key_id, private in (
                    ("security-a", "approval-key-a", private_a),
                    ("security-b", "approval-key-b", private_b)):
                output = work / f"{person}.approval.json"
                os.environ["PDR_REMOTE_APPROVAL_KEY"] = str(private)
                self.assertEqual(control.approve_command(Namespace(
                    proposal=str(proposal_path),
                    expected_proposal_sha256=proposal_sha,
                    approver_id=person, key_id=key_id,
                    private_key_environment="PDR_REMOTE_APPROVAL_KEY",
                    verification_time=NOW, output=str(output),
                )), 0)
                approvals.append(output)
            os.environ.pop("PDR_REMOTE_APPROVAL_KEY", None)
            activation_report = work / "activation.json"
            status_report = work / "status.json"
            self.assertEqual(state_tool.activate_command(Namespace(
                **common, coordinator_id="host-b", expected_state_version=1,
                expected_current_policy_sha256=initial_sha,
                candidate_policy=str(candidate_path),
                expected_candidate_policy_sha256=candidate_sha,
                proposal=str(proposal_path), expected_proposal_sha256=proposal_sha,
                approval=[str(path) for path in approvals],
                governance_policy=str(governance),
                expected_governance_policy_id="certifier-governance",
                expected_governance_policy_sha256=governance_sha,
                trusted_keys_directory=str(keys), activator_id="release-operator",
                verification_time=NOW, operation_id="remote-activate-2",
                report=str(activation_report), status_report=str(status_report),
            )), 0)
            status = json.loads(status_report.read_bytes())
            self.assertEqual(status["stateVersion"], 2)
            self.assertEqual(status["policyGeneration"], 2)
            self.assertEqual(status["coordinatorId"], "host-b")
            self.assertIsNotNone(status["activationProposalId"])

    def test_public_cli_exposes_all_remote_operations(self) -> None:
        for operation in ("initialize", "propose", "activate", "status"):
            completed = subprocess.run(
                [sys.executable, str(ROOT / "tools/pdr.py"), "contract-package",
                 f"adapter-certifier-trust-remote-{operation}", "--help"],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_pointer_v2_resolves_same_refs_to_different_host_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            resolver_a, backend_a, artifact_a = self.create_resolver_host(
                root, "host-a"
            )
            resolver_b, backend_b, artifact_b = self.create_resolver_host(
                root, "host-b"
            )
            resolver_c, backend_c, artifact_c = self.create_resolver_host(
                root, "host-c"
            )
            self.assertNotEqual(
                hashlib.sha256(resolver_a.read_bytes()).hexdigest(),
                hashlib.sha256(resolver_b.read_bytes()).hexdigest(),
            )
            backend_ref = root / "backend-ref.json"
            artifact_ref = root / "artifact-ref.json"
            write_json(
                backend_ref,
                self.portable_reference("registry-leader-backend"),
            )
            write_json(
                artifact_ref, self.portable_reference("artifact-store")
            )
            host_a = state_tool._store(
                self.portable_args(
                    resolver_a, backend_ref, artifact_ref, "host-a"
                ), True,
            )
            first = host_a.initialize(
                package_tool.json_bytes(policy(1)),
                operation_id="portable-bootstrap", actor="release-operator",
            )
            self.assertEqual(first["pointer"]["schemaVersion"], 2)
            self.assertNotIn("stateBackendConfigSha256", first["pointer"])
            self.assertNotIn("artifactStoreConfigSha256", first["pointer"])
            self.assertEqual(
                first["pointer"]["stateBackendConfigRef"],
                self.portable_reference("registry-leader-backend"),
            )

            host_b = state_tool._store(
                self.portable_args(
                    resolver_b, backend_ref, artifact_ref, "host-b"
                ), True,
            )
            current = host_b.read()
            assert current is not None
            candidate = package_tool.json_bytes(
                policy(2, ["fleet-prod", "fleet-stage"])
            )
            evidence = activation(
                current["policySha256"], package_tool.sha256_bytes(candidate),
                1, 2, "portable-proposal",
            )
            host_b.activate(
                candidate, evidence, expected_state_version=1,
                expected_current_policy_sha256=current["policySha256"],
                operation_id="portable-activate", actor="release-operator",
            )
            host_c = state_tool._store(
                self.portable_args(
                    resolver_c, backend_ref, artifact_ref, None
                ), False,
            )
            recovered = host_c.read()
            assert recovered is not None
            self.assertEqual(recovered["policy"]["generation"], 2)
            self.assertEqual(recovered["pointer"]["schemaVersion"], 2)
            self.assertEqual(
                recovered["pointer"]["adapterConfigResolverId"],
                "trust-config-resolver",
            )
            portable_status = state_tool._write_status(None, recovered)
            self.assertEqual(portable_status["pointerSchemaVersion"], 2)
            self.assertEqual(
                portable_status["stateBackendConfigRef"],
                self.portable_reference("registry-leader-backend"),
            )
            self.assertRegex(
                portable_status[
                    "adapterConfigResolverCapabilityManifestSha256"
                ], r"^[0-9a-f]{64}$",
            )
            self.assertEqual(
                self.backend_paths[-3:],
                [backend_a.resolve(), backend_b.resolve(), backend_c.resolve()],
            )
            self.assertEqual(
                self.artifact_paths[-3:],
                [artifact_a.resolve(), artifact_b.resolve(), artifact_c.resolve()],
            )

            wrong_ref = root / "wrong-backend-ref.json"
            write_json(wrong_ref, dict(
                self.portable_reference("registry-leader-backend"),
                revision="rev-other",
            ))
            with self.assertRaisesRegex(RuntimeError, "identity changed"):
                state_tool._store(
                    self.portable_args(
                        resolver_c, wrong_ref, artifact_ref, None
                    ), False,
                )
            wrong_scope = self.portable_args(
                resolver_c, backend_ref, artifact_ref, None
            )
            wrong_scope.control_id = "other-control"
            with self.assertRaisesRegex(RuntimeError, "scope"):
                state_tool._store(wrong_scope, False)


if __name__ == "__main__":
    result = unittest.main(exit=False, verbosity=2).result
    if result.wasSuccessful():
        print("PDR_ADAPTER_CERTIFIER_TRUST_STATE_STORE_PASS remote=1 cas=1 "
              "fencing=1 takeover=1 immutable=1 stateChain=1 ambiguousCommit=1 "
              "tamper=1 crossHost=1 approvals=2 cli=1 pointerV2=1 "
              "logicalRefs=1 hostPaths=3 resolverPin=1 revision=1 scope=1 "
              "v1Compatible=1")
    raise SystemExit(0 if result.wasSuccessful() else 1)
