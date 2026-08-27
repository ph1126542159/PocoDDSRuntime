#!/usr/bin/env python3
"""Governed one-way migration tests for Adapter certifier trust state."""

from __future__ import annotations

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
sys.path.insert(0, str(ROOT / "tools" / "tests"))

import team_contract_adapter_certifier_trust_control as control
import team_contract_adapter_certifier_trust_state_store as state_tool
import team_contract_package as package_tool
from test_team_contract_adapter_certifier_trust_state_store import (
    MemoryArtifactStore, MemoryBackend, NOW, RESOLVER_ADAPTER,
    RESOLVER_GENERATOR, activation, key_pair, policy, write_json,
)


class TrustStateMigrationTest(unittest.TestCase):
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
        os.environ.pop("PDR_MIGRATION_APPROVAL_KEY", None)
        self.artifact_patch.stop()
        self.backend_patch.stop()

    @staticmethod
    def direct_store(coordinator: str | None) \
            -> state_tool.RemoteCertifierTrustStateStore:
        return state_tool.RemoteCertifierTrustStateStore(
            state_backend_config="legacy-backend.json",
            state_backend_config_sha256="5" * 64,
            artifact_store_config="legacy-artifact.json",
            artifact_store_config_sha256="6" * 64,
            control_id="certifier-control",
            trust_policy_id="production-certifiers",
            expected_backend_id="certifier-state-backend",
            expected_artifact_store_id="certifier-artifacts",
            coordinator_id=coordinator,
        )

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

    def migration_args(self, resolver: Path, backend_ref: Path,
                       artifact_ref: Path) -> dict:
        return {
            "source_state_backend_config": "legacy-backend.json",
            "expected_source_state_backend_config_sha256": "5" * 64,
            "source_artifact_store_config": "legacy-artifact.json",
            "expected_source_artifact_store_config_sha256": "6" * 64,
            "expected_state_backend_id": "certifier-state-backend",
            "expected_artifact_store_id": "certifier-artifacts",
            "target_adapter_config_resolver_config": str(resolver),
            "expected_target_adapter_config_resolver_config_sha256":
                hashlib.sha256(resolver.read_bytes()).hexdigest(),
            "expected_target_adapter_config_resolver_id": "trust-config-resolver",
            "target_state_backend_config_ref": str(backend_ref),
            "expected_target_state_backend_config_ref_sha256":
                hashlib.sha256(backend_ref.read_bytes()).hexdigest(),
            "target_artifact_store_config_ref": str(artifact_ref),
            "expected_target_artifact_store_config_ref_sha256":
                hashlib.sha256(artifact_ref.read_bytes()).hexdigest(),
            "control_id": "certifier-control",
            "trust_policy_id": "production-certifiers",
        }

    def portable_args(self, resolver: Path, backend_ref: Path,
                      artifact_ref: Path, coordinator: str | None) -> Namespace:
        return Namespace(
            state_backend_config=None,
            expected_state_backend_config_sha256=None,
            artifact_store_config=None,
            expected_artifact_store_config_sha256=None,
            expected_state_backend_id="certifier-state-backend",
            expected_artifact_store_id="certifier-artifacts",
            adapter_config_resolver_config=str(resolver),
            expected_adapter_config_resolver_config_sha256=
                hashlib.sha256(resolver.read_bytes()).hexdigest(),
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

    def test_governed_atomic_v1_to_v2_migration_and_recovery(self) -> None:
        source = self.direct_store("host-a")
        first = source.initialize(
            package_tool.json_bytes(policy(1)), operation_id="legacy-bootstrap",
            actor="release-operator",
        )
        candidate = package_tool.json_bytes(
            policy(2, ["fleet-prod", "fleet-stage"])
        )
        candidate_sha = package_tool.sha256_bytes(candidate)
        second = source.activate(
            candidate,
            activation(first["policySha256"], candidate_sha, 1, 2,
                       "legacy-proposal-2"),
            expected_state_version=1,
            expected_current_policy_sha256=first["policySha256"],
            operation_id="legacy-activate-2", actor="release-operator",
        )
        stale_writer = self.direct_store("host-stale")
        self.assertIsNotNone(stale_writer.read())

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            resolver_b, backend_b, artifact_b = self.create_resolver_host(
                root, "host-b"
            )
            resolver_c, backend_c, artifact_c = self.create_resolver_host(
                root, "host-c"
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
            common = self.migration_args(resolver_b, backend_ref, artifact_ref)
            preflight_path = root / "preflight.json"
            self.assertEqual(state_tool.migration_preflight_command(Namespace(
                **common, expected_state_version=2,
                expected_current_policy_sha256=second["policySha256"],
                verification_time=NOW, report=str(preflight_path),
            )), 0)
            preflight = json.loads(preflight_path.read_bytes())
            state_tool.validate_migration_preflight(preflight)
            self.assertEqual(preflight["sourceStateVersion"], 2)
            self.assertEqual(preflight["targetStateVersion"], 3)

            keys = root / "keys"
            keys.mkdir()
            private_a, public_a = key_pair(keys, "approval-key-a")
            private_b, public_b = key_pair(keys, "approval-key-b")
            governance_path = root / "governance.json"
            governance_sha = write_json(governance_path, {
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
            proposal_path = root / "migration-proposal.json"
            self.assertEqual(state_tool.migration_propose_command(Namespace(
                **common, expected_state_version=2,
                expected_current_policy_sha256=second["policySha256"],
                governance_policy=str(governance_path),
                expected_governance_policy_id="certifier-governance",
                expected_governance_policy_sha256=governance_sha,
                proposer_id="release-author", ticket="SEC-MIGRATE-1",
                reason="remove host-local pins from the authority pointer",
                issued_at=NOW, verification_time=NOW, lifetime_seconds=3600,
                output=str(proposal_path),
            )), 0)
            proposal_sha = hashlib.sha256(proposal_path.read_bytes()).hexdigest()
            approvals: list[Path] = []
            for person, key_id, private in (
                    ("security-a", "approval-key-a", private_a),
                    ("security-b", "approval-key-b", private_b)):
                output = root / f"{person}.migration-approval.json"
                os.environ["PDR_MIGRATION_APPROVAL_KEY"] = str(private)
                self.assertEqual(state_tool.migration_approve_command(Namespace(
                    proposal=str(proposal_path),
                    expected_proposal_sha256=proposal_sha,
                    approver_id=person, key_id=key_id,
                    private_key_environment="PDR_MIGRATION_APPROVAL_KEY",
                    verification_time=NOW, output=str(output),
                )), 0)
                approvals.append(output)
            os.environ.pop("PDR_MIGRATION_APPROVAL_KEY", None)

            activate = dict(
                **common, coordinator_id="host-b", expected_state_version=2,
                expected_current_policy_sha256=second["policySha256"],
                proposal=str(proposal_path), expected_proposal_sha256=proposal_sha,
                governance_policy=str(governance_path),
                expected_governance_policy_id="certifier-governance",
                expected_governance_policy_sha256=governance_sha,
                trusted_keys_directory=str(keys), activator_id="release-operator",
                operation_id="migrate-pointer-v2", verification_time=NOW,
                report=str(root / "migration-report.json"),
                status_report=str(root / "migration-status.json"),
            )
            failed = dict(activate, approval=[str(approvals[0])])
            self.assertEqual(
                state_tool.migration_activate_command(Namespace(**failed)), 2
            )
            assert self.backend.value is not None
            self.assertEqual(self.backend.value[0]["schemaVersion"], 1)

            self.backend.uncertain_after_commit = True
            succeeded = dict(
                activate, approval=[str(path) for path in approvals]
            )
            self.assertEqual(
                state_tool.migration_activate_command(Namespace(**succeeded)), 0
            )
            migrated = json.loads((root / "migration-report.json").read_bytes())
            state_tool.validate_migration_report(migrated)
            self.assertEqual(migrated["policySha256"], second["policySha256"])
            self.assertEqual(self.backend.value[0]["schemaVersion"], 2)
            self.assertNotIn("stateBackendConfigSha256", self.backend.value[0])

            self.assertEqual(
                state_tool.migration_activate_command(Namespace(**succeeded)), 0
            )
            host_c = state_tool._store(
                self.portable_args(
                    resolver_c, backend_ref, artifact_ref, "host-c"
                ), True,
            )
            recovered = host_c.read()
            assert recovered is not None
            self.assertEqual(recovered["state"]["action"], "migrate")
            self.assertEqual(recovered["policy"]["generation"], 2)
            self.assertEqual(recovered["migration"]["proposalSha256"], proposal_sha)
            self.assertIn(backend_b.resolve(), self.backend_paths)
            self.assertIn(backend_c.resolve(), self.backend_paths)
            self.assertIn(artifact_b.resolve(), self.artifact_paths)
            self.assertIn(artifact_c.resolve(), self.artifact_paths)

            next_policy = package_tool.json_bytes(
                policy(3, ["fleet-prod", "fleet-stage", "fleet-west"])
            )
            next_activation = activation(
                recovered["policySha256"], package_tool.sha256_bytes(next_policy),
                2, 3, "post-migration-proposal",
            )
            post = host_c.activate(
                next_policy, next_activation, expected_state_version=3,
                expected_current_policy_sha256=recovered["policySha256"],
                operation_id="post-migration-activate", actor="release-operator",
            )
            self.assertEqual(post["policy"]["generation"], 3)
            self.assertEqual(host_c.read()["policy"]["generation"], 3)

            stale_policy = package_tool.json_bytes(
                policy(3, ["fleet-prod", "fleet-stale"])
            )
            with self.assertRaisesRegex(ValueError, "CAS conflict"):
                stale_writer.activate(
                    stale_policy,
                    activation(
                        second["policySha256"],
                        package_tool.sha256_bytes(stale_policy), 2, 3,
                        "stale-after-migration",
                    ),
                    expected_state_version=2,
                    expected_current_policy_sha256=second["policySha256"],
                    operation_id="stale-after-migration", actor="release-operator",
                )

            migration_digest = migrated["proposalSha256"]
            evidence_digest = recovered["state"]["migrationRef"]["sha256"]
            original = self.artifacts.values[evidence_digest]
            self.artifacts.values[evidence_digest] = b"{}\n"
            with self.assertRaisesRegex(ValueError, "migration evidence changed"):
                host_c.read()
            self.artifacts.values[evidence_digest] = original
            self.assertRegex(migration_digest, r"^[0-9a-f]{64}$")

    def test_public_cli_exposes_migration_operations(self) -> None:
        for operation in ("preflight", "propose", "approve", "activate"):
            completed = subprocess.run([
                sys.executable, str(ROOT / "tools" / "pdr.py"),
                "contract-package",
                f"adapter-certifier-trust-remote-migration-{operation}",
                "--help",
            ], capture_output=True, text=True, check=False)
            self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == "__main__":
    result = unittest.main(exit=False, verbosity=2).result
    if result.wasSuccessful():
        print("PDR_ADAPTER_CERTIFIER_TRUST_MIGRATION_PASS preflight=1 "
              "approvals=2 cas=1 uncertainCommit=1 idempotent=1 oneWay=1 "
              "history=1 noPolicyChange=1 failClosed=1 postActivation=1 "
              "crossHost=2 cli=4")
    raise SystemExit(0 if result.wasSuccessful() else 1)
