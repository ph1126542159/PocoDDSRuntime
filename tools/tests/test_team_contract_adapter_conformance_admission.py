#!/usr/bin/env python3

from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

import team_contract_adapter_conformance as conformance_tool
import team_contract_adapter_conformance_admission as admission_tool
import team_contract_adapter_certifier_signer as signer_tool
import team_contract_adapter_conformance_trust as trust_tool
import team_contract_adapter_catalog_fleet as fleet_tool
import team_contract_package as package_tool


IDS = {
    "adapter-config-resolver": ("resolverId", "resolver-a"),
    "artifact-store": ("storeId", "store-a"),
    "control-authorizer": ("authorizerId", "authorizer-a"),
    "fleet-executor": ("executorId", "executor-a"),
    "registry-leader-backend": ("backendId", "backend-a"),
    "wave-gate": ("gateId", "gate-a"),
}


class AdmissionTest(unittest.TestCase):
    @classmethod
    def tearDownClass(cls) -> None:
        print(
            "PDR_ADAPTER_CONFORMANCE_ADMISSION_PASS planV6=1 kinds=6 "
            "bundlePin=1 evidencePin=1 age=1 configDrift=1 capabilityDrift=1 "
            "scope=1 journal=1 hostVariance=1 noPaths=1 cli=1 planV7=1 "
            "signed=1 certifierScope=1 expiry=1 revocation=1 rotation=1 "
            "trustGeneration=1 externalSigner=1 signerCapability=1 "
            "signerPin=1 localFallback=1"
        )

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.policy = {
            "policyId": "fleet-production-v1",
            "certificationLevel": "integration-readiness",
            "checkSetVersion": "1.0.0",
            "maximumEvidenceAgeSeconds": 3600,
            "requiredAdapterKinds": admission_tool.REQUIRED_KINDS,
            "requiredChecks": admission_tool.REQUIRED_CHECKS,
        }
        self.configs: dict[str, dict] = {}
        self.capabilities: dict[str, str] = {}
        entries = []
        for kind in admission_tool.REQUIRED_KINDS:
            field, adapter_id = IDS[kind]
            config = {
                "schemaVersion": 1, field: adapter_id,
                "protocolMajor": 1, "minimumProtocolMinor": 0,
                "requiredCapabilities": ["stable-capability"],
            }
            config_sha = package_tool.sha256_bytes(
                package_tool.json_bytes(config)
            )
            capability_sha = package_tool.sha256_bytes(
                f"capability:{kind}".encode()
            )
            scope = {"primaryId": None, "secondaryId": None}
            if kind == "registry-leader-backend":
                scope = {"primaryId": "rollout-a", "secondaryId": "catalog-a"}
            elif kind == "artifact-store":
                scope = {"primaryId": "rollout-a", "secondaryId": None}
            binding = {
                "certificationLevel": "integration-readiness",
                "checkSetVersion": "1.0.0", "adapterKind": kind,
                "adapterId": adapter_id, "configSha256": config_sha,
                "scope": scope, "protocol": {"major": 1, "minimumMinor": 0},
                "requiredCapabilities": ["stable-capability"],
                "capabilityManifestSha256": capability_sha,
            }
            evidence = {
                "schemaVersion": 1,
                "product": conformance_tool.EVIDENCE_PRODUCT,
                "passed": True, **binding,
                "conformanceId": package_tool.sha256_bytes(
                    package_tool.json_bytes(binding)
                ),
                "configSchemaVersion": 1,
                "checks": [{
                    "checkId": check, "passed": True,
                    "evidenceSha256": package_tool.sha256_bytes(check.encode()),
                    "diagnostic": None,
                } for check in admission_tool.REQUIRED_CHECKS],
                "certifiedAt": datetime.now(timezone.utc).isoformat(),
                "reportSha256": "0" * 64,
            }
            evidence["reportSha256"] = conformance_tool._report_digest(evidence)
            evidence_path = self.root / f"{kind}.json"
            package_tool.write_json(evidence_path, evidence)
            entries.append({
                "adapterKind": kind, "evidencePath": str(evidence_path),
                "evidenceSha256": package_tool.sha256_file(evidence_path),
            })
            self.configs[kind] = config
            self.capabilities[kind] = capability_sha
        self.bundle = {
            "schemaVersion": 1, "product": admission_tool.BUNDLE_PRODUCT,
            "bundleId": "host-a", "rolloutId": "rollout-a",
            "catalogId": "catalog-a", "entries": entries,
        }
        self.bundle_path = self.root / "bundle.json"
        package_tool.write_json(self.bundle_path, self.bundle)
        self.bundle_sha = package_tool.sha256_file(self.bundle_path)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def admit(self) -> admission_tool.Admission:
        result = admission_tool.Admission(
            self.bundle_path, self.bundle_sha, self.policy,
            rollout_id="rollout-a", catalog_id="catalog-a",
        )
        for kind in admission_tool.REQUIRED_KINDS:
            _, adapter_id = IDS[kind]
            scope = {"primaryId": None, "secondaryId": None}
            if kind == "registry-leader-backend":
                scope = {"primaryId": "rollout-a", "secondaryId": "catalog-a"}
            elif kind == "artifact-store":
                scope = {"primaryId": "rollout-a", "secondaryId": None}
            result.precheck(
                kind, self.configs[kind],
                package_tool.sha256_bytes(package_tool.json_bytes(
                    self.configs[kind]
                )), adapter_id=adapter_id, scope=scope,
            )
            result.postcheck(kind, self.capabilities[kind])
        return result

    def test_complete_admission_is_portable_and_self_bound(self) -> None:
        summary = self.admit().summary("host-a-coordinator")
        admission_tool.validate_summary(summary)
        serialized = json.dumps(summary)
        self.assertNotIn(str(self.root), serialized)
        self.assertEqual(len(summary["entries"]), 6)
        self.assertEqual(summary["policyId"], "fleet-production-v1")

    def test_fail_closed_for_pins_age_config_capability_and_scope(self) -> None:
        admission = admission_tool.Admission(
            self.bundle_path, self.bundle_sha, self.policy,
            rollout_id="rollout-a", catalog_id="catalog-a",
        )
        with self.assertRaises(ValueError):
            admission_tool.Admission(
                self.bundle_path, "0" * 64, self.policy,
                rollout_id="rollout-a", catalog_id="catalog-a",
            )
        expired = copy.deepcopy(self.bundle)
        evidence_path = Path(expired["entries"][0]["evidencePath"])
        evidence = json.loads(evidence_path.read_bytes())
        evidence["certifiedAt"] = (
            datetime.now(timezone.utc) - timedelta(hours=2)
        ).isoformat()
        evidence["reportSha256"] = conformance_tool._report_digest(evidence)
        package_tool.write_json(evidence_path, evidence)
        expired["entries"][0]["evidenceSha256"] = \
            package_tool.sha256_file(evidence_path)
        expired_path = self.root / "expired-bundle.json"
        package_tool.write_json(expired_path, expired)
        with self.assertRaisesRegex(ValueError, "outside policy age"):
            admission_tool.Admission(
                expired_path, package_tool.sha256_file(expired_path),
                self.policy, rollout_id="rollout-a", catalog_id="catalog-a",
            )

        kind = "fleet-executor"
        _, adapter_id = IDS[kind]
        with self.assertRaisesRegex(ValueError, "active config"):
            admission.precheck(
                kind, self.configs[kind], "0" * 64,
                adapter_id=adapter_id,
                scope={"primaryId": None, "secondaryId": None},
            )
        config_sha = package_tool.sha256_bytes(
            package_tool.json_bytes(self.configs[kind])
        )
        admission.precheck(
            kind, self.configs[kind], config_sha, adapter_id=adapter_id,
            scope={"primaryId": None, "secondaryId": None},
        )
        with self.assertRaisesRegex(ValueError, "capability identity"):
            admission.postcheck(kind, "0" * 64)

    def test_fleet_v6_plan_and_journal_persist_only_portable_admission(self) -> None:
        references = {}
        field_names = {
            "fleet-executor": "executorConfigRef",
            "wave-gate": "gateConfigRef",
            "control-authorizer": "controlAuthorizerConfigRef",
            "registry-leader-backend": "stateBackendConfigRef",
            "artifact-store": "artifactStoreConfigRef",
        }
        for kind, field_name in field_names.items():
            _, adapter_id = IDS[kind]
            references[field_name] = {
                "kind": "adapter-config-ref", "resolverId": "resolver-a",
                "configId": f"config-{kind}", "adapterKind": kind,
                "adapterId": adapter_id, "revision": "r1",
            }
        plan = {
            "schemaVersion": 6,
            "product": fleet_tool.PLAN_PRODUCT,
            "rolloutId": "rollout-a", "catalogId": "catalog-a",
            "candidateCatalogGeneration": 2,
            "candidateCatalogSha256": "1" * 64,
            "maxParallelNodes": 1,
            "waves": [{
                "waveId": "canary", "mode": "canary", "maxFailures": 0,
                "gatePolicy": {"minimumObservationSeconds": 0,
                               "maxEvaluations": 1,
                               "rejectionAction": "pause"},
                "nodes": [{"nodeId": "node-a", "failureDomain": "fd-a",
                           "expectedActivationGeneration": 1}],
            }],
            "adapterConfigResolverId": "resolver-a", **references,
            "adapterConformancePolicy": self.policy,
        }
        fleet_tool.validate_plan(plan)
        summary = self.admit().summary("host-a-coordinator")
        plan_sha = package_tool.sha256_bytes(package_tool.json_bytes(plan))
        journal = fleet_tool.create_journal(plan, plan_sha, None, summary)
        journal["stateVersion"] = 1
        journal["lastCoordinatorId"] = "host-a-coordinator"
        journal["journalSha256"] = fleet_tool.self_digest(journal)
        fleet_tool.validate_journal(journal, plan)
        self.assertNotIn(str(self.root), json.dumps(journal))
        second = copy.deepcopy(summary)
        second["coordinatorId"] = "host-b-coordinator"
        binding = {key: second[key] for key in (
            "policyId", "coordinatorId", "bundleSha256", "entries"
        )}
        second["admissionId"] = package_tool.sha256_bytes(
            package_tool.json_bytes(binding)
        )
        self.assertTrue(fleet_tool.record_admission(journal, second))
        journal["journalSha256"] = fleet_tool.self_digest(journal)
        fleet_tool.validate_journal(journal, plan)
        self.assertEqual(len(journal["admissions"]), 2)

    def test_signed_admission_enforces_signature_revocation_and_rotation(self) -> None:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import \
            Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import (
            Encoding, NoEncryption, PrivateFormat, PublicFormat,
        )

        keys = self.root / "keys"
        keys.mkdir()
        private = Ed25519PrivateKey.generate()
        private_path = keys / "certifier-private.pem"
        public_path = keys / "certifier-public.pem"
        private_path.write_bytes(private.private_bytes(
            Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()
        ))
        public_path.write_bytes(private.public_key().public_bytes(
            Encoding.PEM, PublicFormat.SubjectPublicKeyInfo
        ))
        now = datetime.now(timezone.utc)
        policy = {
            "schemaVersion": 1, "product": trust_tool.POLICY_PRODUCT,
            "policyId": "adapter-certifiers", "generation": 1,
            "maximumAttestationLifetimeSeconds": 3600,
            "allowedCertifiers": [{
                "certifierId": "runtime-adapter-team", "keyId": "key-2026-a",
                "algorithm": "Ed25519",
                "publicKey": "keys/certifier-public.pem",
                "publicKeySha256": package_tool.sha256_file(public_path),
                "adapterKinds": admission_tool.REQUIRED_KINDS,
                "adapterIds": sorted(value[1] for value in IDS.values()),
                "notBefore": (now - timedelta(minutes=5)).isoformat(),
                "notAfter": (now + timedelta(days=1)).isoformat(),
            }],
            "revokedKeys": [],
        }
        policy_path = self.root / "trust-policy.json"
        package_tool.write_json(policy_path, policy)
        os.environ["PDR_TEST_ADAPTER_CERTIFIER_KEY"] = str(private_path)
        try:
            signed_entries = []
            for entry in self.bundle["entries"]:
                kind = entry["adapterKind"]
                attestation_path = self.root / f"{kind}.attestation.json"
                args = type("Args", (), {
                    "evidence": entry["evidencePath"],
                    "expected_evidence_sha256": entry["evidenceSha256"],
                    "certifier_id": "runtime-adapter-team",
                    "key_id": "key-2026-a",
                    "private_key_environment":
                        "PDR_TEST_ADAPTER_CERTIFIER_KEY",
                    "private_key_passphrase_environment": None,
                    "issued_at": None, "lifetime_seconds": 3600,
                    "report": str(attestation_path),
                })()
                self.assertEqual(trust_tool.attest_command(args), 0)
                signed_entries.append({
                    **entry, "attestationPath": str(attestation_path),
                    "attestationSha256":
                        package_tool.sha256_file(attestation_path),
                })
        finally:
            os.environ.pop("PDR_TEST_ADAPTER_CERTIFIER_KEY", None)
        bundle = {**self.bundle, "schemaVersion": 2,
                  "bundleId": "signed-host-a", "entries": signed_entries}
        bundle_path = self.root / "signed-bundle.json"
        package_tool.write_json(bundle_path, bundle)
        admission = admission_tool.Admission(
            bundle_path, package_tool.sha256_file(bundle_path), self.policy,
            rollout_id="rollout-a", catalog_id="catalog-a",
            trust_policy_path=policy_path,
            expected_trust_policy_sha256=package_tool.sha256_file(policy_path),
            expected_trust_policy_id="adapter-certifiers",
            minimum_trust_policy_generation=1,
        )
        for kind in admission_tool.REQUIRED_KINDS:
            _, adapter_id = IDS[kind]
            scope = {"primaryId": None, "secondaryId": None}
            if kind == "registry-leader-backend":
                scope = {"primaryId": "rollout-a", "secondaryId": "catalog-a"}
            elif kind == "artifact-store":
                scope = {"primaryId": "rollout-a", "secondaryId": None}
            admission.precheck(
                kind, self.configs[kind],
                package_tool.sha256_bytes(package_tool.json_bytes(
                    self.configs[kind]
                )), adapter_id=adapter_id, scope=scope,
            )
            admission.postcheck(kind, self.capabilities[kind])
        summary = admission.summary("signed-host-a")
        admission_tool.validate_summary(summary)
        self.assertEqual(summary["trustPolicyGeneration"], 1)
        self.assertEqual(
            {entry["keyId"] for entry in summary["entries"]},
            {"key-2026-a"},
        )
        self.assertNotIn(str(self.root), json.dumps(summary))
        field_names = {
            "fleet-executor": "executorConfigRef",
            "wave-gate": "gateConfigRef",
            "control-authorizer": "controlAuthorizerConfigRef",
            "registry-leader-backend": "stateBackendConfigRef",
            "artifact-store": "artifactStoreConfigRef",
        }
        references = {}
        for kind, field_name in field_names.items():
            references[field_name] = {
                "kind": "adapter-config-ref", "resolverId": "resolver-a",
                "configId": f"config-{kind}", "adapterKind": kind,
                "adapterId": IDS[kind][1], "revision": "r1",
            }
        plan = {
            "schemaVersion": 7, "product": fleet_tool.PLAN_PRODUCT,
            "rolloutId": "rollout-a", "catalogId": "catalog-a",
            "candidateCatalogGeneration": 2,
            "candidateCatalogSha256": "2" * 64,
            "maxParallelNodes": 1,
            "waves": [{
                "waveId": "canary", "mode": "canary", "maxFailures": 0,
                "gatePolicy": {"minimumObservationSeconds": 0,
                               "maxEvaluations": 1,
                               "rejectionAction": "pause"},
                "nodes": [{"nodeId": "node-a", "failureDomain": "fd-a",
                           "expectedActivationGeneration": 1}],
            }],
            "adapterConfigResolverId": "resolver-a", **references,
            "adapterConformancePolicy": self.policy,
            "adapterConformanceTrustPolicy": {
                "policyId": "adapter-certifiers", "minimumGeneration": 1,
            },
        }
        fleet_tool.validate_plan(plan)
        plan_sha = package_tool.sha256_bytes(package_tool.json_bytes(plan))
        journal = fleet_tool.create_journal(plan, plan_sha, None, summary)
        journal["stateVersion"] = 1
        journal["lastCoordinatorId"] = "signed-host-a"
        journal["journalSha256"] = fleet_tool.self_digest(journal)
        fleet_tool.validate_journal(journal, plan)

        revoked = copy.deepcopy(policy)
        revoked["generation"] = 2
        revoked["revokedKeys"] = [{
            "keyId": "key-2026-a", "revokedAt": now.isoformat(),
            "reason": "rotation completed",
        }]
        revoked_path = self.root / "revoked-policy.json"
        package_tool.write_json(revoked_path, revoked)
        with self.assertRaisesRegex(ValueError, "revoked"):
            admission_tool.Admission(
                bundle_path, package_tool.sha256_file(bundle_path), self.policy,
                rollout_id="rollout-a", catalog_id="catalog-a",
                trust_policy_path=revoked_path,
                expected_trust_policy_sha256=
                    package_tool.sha256_file(revoked_path),
                expected_trust_policy_id="adapter-certifiers",
                minimum_trust_policy_generation=2,
            )
        private_b = Ed25519PrivateKey.generate()
        private_b_path = keys / "certifier-private-b.pem"
        public_b_path = keys / "certifier-public-b.pem"
        private_b_path.write_bytes(private_b.private_bytes(
            Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()
        ))
        public_b_path.write_bytes(private_b.public_key().public_bytes(
            Encoding.PEM, PublicFormat.SubjectPublicKeyInfo
        ))
        rotated = copy.deepcopy(revoked)
        rotated["allowedCertifiers"].append({
            **rotated["allowedCertifiers"][0],
            "keyId": "key-2026-b",
            "publicKey": "keys/certifier-public-b.pem",
            "publicKeySha256": package_tool.sha256_file(public_b_path),
        })
        rotated_path = self.root / "rotated-policy.json"
        package_tool.write_json(rotated_path, rotated)
        signer_mapping_path = self.root / "signer-mapping.json"
        package_tool.write_json(signer_mapping_path, {
            "schemaVersion": 1,
            "product": "PocoDDSRuntimeTeamContractAdapterCertifierSignerLocalMapping",
            "signerId": "runtime-adapter-kms",
            "certifierId": "runtime-adapter-team",
            "keys": [{
                "keyId": "key-2026-b",
                "privateKeyEnvironment":
                    "PDR_TEST_ADAPTER_CERTIFIER_KEY_B",
            }],
        })
        signer_adapter = Path(__file__).resolve().parents[2] / \
            "examples/team-contract-adapter-certifier-signer-local" / \
            "local_ed25519_certifier_signer_adapter.py"
        signer_config_path = self.root / "signer-config.json"
        package_tool.write_json(signer_config_path, {
            "schemaVersion": 1, "product": signer_tool.CONFIG_PRODUCT,
            "signerId": "runtime-adapter-kms",
            "certifierId": "runtime-adapter-team",
            "kind": "external-command", "protocolMajor": 1,
            "minimumProtocolMinor": 0,
            "requiredCapabilities": signer_tool.REQUIRED_CAPABILITIES,
            "keys": [{
                "keyId": "key-2026-b", "algorithm": "Ed25519",
                "publicKey": str(public_b_path),
                "publicKeySha256": package_tool.sha256_file(public_b_path),
            }],
            "executable": str(Path(sys.executable).resolve()),
            "executableSha256": package_tool.sha256_file(
                Path(sys.executable).resolve()
            ),
            "arguments": [
                str(signer_adapter), "--mapping", str(signer_mapping_path),
            ],
            "artifactPins": [
                {"path": str(signer_adapter),
                 "sha256": package_tool.sha256_file(signer_adapter)},
                {"path": str(signer_mapping_path),
                 "sha256": package_tool.sha256_file(signer_mapping_path)},
            ],
            "environmentVariables": [],
            "optionalEnvironmentVariables": [
                "PDR_CERTIFIER_SIGNER_FAULT",
                "PDR_TEST_ADAPTER_CERTIFIER_KEY_B",
            ],
            "timeoutSeconds": 5, "maxResponseBytes": 16384,
            "maxPayloadBytes": 16384,
        })
        signer_config_sha = package_tool.sha256_file(signer_config_path)
        os.environ["PDR_TEST_ADAPTER_CERTIFIER_KEY_B"] = str(private_b_path)
        rotated_entries = []
        try:
            for entry in self.bundle["entries"]:
                kind = entry["adapterKind"]
                attestation_path = self.root / f"{kind}.rotated.json"
                args = type("Args", (), {
                    "evidence": entry["evidencePath"],
                    "expected_evidence_sha256": entry["evidenceSha256"],
                    "certifier_id": "runtime-adapter-team",
                    "key_id": "key-2026-b",
                    "private_key_environment": None,
                    "private_key_passphrase_environment": None,
                    "signer_config": str(signer_config_path),
                    "expected_signer_config_sha256": signer_config_sha,
                    "issued_at": None, "lifetime_seconds": 3600,
                    "report": str(attestation_path),
                })()
                self.assertEqual(trust_tool.attest_command(args), 0)
                rotated_entries.append({
                    **entry, "attestationPath": str(attestation_path),
                    "attestationSha256":
                        package_tool.sha256_file(attestation_path),
                })
        finally:
            os.environ.pop("PDR_TEST_ADAPTER_CERTIFIER_KEY_B", None)
        rotated_bundle = {
            **self.bundle, "schemaVersion": 2,
            "bundleId": "signed-host-b", "entries": rotated_entries,
        }
        rotated_bundle_path = self.root / "rotated-bundle.json"
        package_tool.write_json(rotated_bundle_path, rotated_bundle)
        rotated_admission = admission_tool.Admission(
            rotated_bundle_path,
            package_tool.sha256_file(rotated_bundle_path), self.policy,
            rollout_id="rollout-a", catalog_id="catalog-a",
            trust_policy_path=rotated_path,
            expected_trust_policy_sha256=
                package_tool.sha256_file(rotated_path),
            expected_trust_policy_id="adapter-certifiers",
            minimum_trust_policy_generation=2,
        )
        self.assertEqual(rotated_admission.trust_policy["generation"], 2)
        self.assertEqual(
            {item["keyId"] for item in rotated_admission._trust.values()},
            {"key-2026-b"},
        )
        self.assertEqual(
            {item["signerId"] for item in rotated_admission._trust.values()},
            {"runtime-adapter-kms"},
        )
        for kind in admission_tool.REQUIRED_KINDS:
            _, adapter_id = IDS[kind]
            scope = {"primaryId": None, "secondaryId": None}
            if kind == "registry-leader-backend":
                scope = {"primaryId": "rollout-a", "secondaryId": "catalog-a"}
            elif kind == "artifact-store":
                scope = {"primaryId": "rollout-a", "secondaryId": None}
            rotated_admission.precheck(
                kind, self.configs[kind],
                package_tool.sha256_bytes(package_tool.json_bytes(
                    self.configs[kind]
                )), adapter_id=adapter_id, scope=scope,
            )
            rotated_admission.postcheck(kind, self.capabilities[kind])
        rotated_summary = rotated_admission.summary("signed-host-b")
        admission_tool.validate_summary(rotated_summary)
        self.assertEqual(
            {item["signerId"] for item in rotated_summary["entries"]},
            {"runtime-adapter-kms"},
        )
        self.assertNotIn(str(self.root), json.dumps(rotated_summary))
        signer_audit = fleet_tool.signer_audit(rotated_summary)
        self.assertEqual(
            signer_audit["adapterConformanceSignerIds"],
            ["runtime-adapter-kms"],
        )
        self.assertEqual(
            len(signer_audit[
                "adapterConformanceSignerCapabilityManifestSha256s"
            ]), 1,
        )
        confined = copy.deepcopy(rotated)
        confined["allowedCertifiers"][1]["adapterIds"] = [
            value for value in confined["allowedCertifiers"][1]["adapterIds"]
            if value != IDS["fleet-executor"][1]
        ]
        confined_path = self.root / "confined-policy.json"
        package_tool.write_json(confined_path, confined)
        with self.assertRaisesRegex(ValueError, "scope"):
            admission_tool.Admission(
                rotated_bundle_path,
                package_tool.sha256_file(rotated_bundle_path), self.policy,
                rollout_id="rollout-a", catalog_id="catalog-a",
                trust_policy_path=confined_path,
                expected_trust_policy_sha256=
                    package_tool.sha256_file(confined_path),
                expected_trust_policy_id="adapter-certifiers",
                minimum_trust_policy_generation=2,
            )
        expired_attestation = self.root / "expired-attestation.json"
        first = self.bundle["entries"][0]
        os.environ["PDR_TEST_ADAPTER_CERTIFIER_KEY_B"] = str(private_b_path)
        try:
            args = type("Args", (), {
                "evidence": first["evidencePath"],
                "expected_evidence_sha256": first["evidenceSha256"],
                "certifier_id": "runtime-adapter-team",
                "key_id": "key-2026-b",
                "private_key_environment": None,
                "private_key_passphrase_environment": None,
                "signer_config": str(signer_config_path),
                "expected_signer_config_sha256": signer_config_sha,
                "issued_at": (now - timedelta(hours=2)).isoformat(),
                "lifetime_seconds": 60,
                "report": str(expired_attestation),
            })()
            self.assertEqual(trust_tool.attest_command(args), 0)
        finally:
            os.environ.pop("PDR_TEST_ADAPTER_CERTIFIER_KEY_B", None)
        expired_bundle = copy.deepcopy(rotated_bundle)
        expired_bundle["entries"][0]["attestationPath"] = \
            str(expired_attestation)
        expired_bundle["entries"][0]["attestationSha256"] = \
            package_tool.sha256_file(expired_attestation)
        expired_bundle_path = self.root / "expired-signed-bundle.json"
        package_tool.write_json(expired_bundle_path, expired_bundle)
        with self.assertRaisesRegex(ValueError, "expired"):
            admission_tool.Admission(
                expired_bundle_path,
                package_tool.sha256_file(expired_bundle_path), self.policy,
                rollout_id="rollout-a", catalog_id="catalog-a",
                trust_policy_path=rotated_path,
                expected_trust_policy_sha256=
                    package_tool.sha256_file(rotated_path),
                expected_trust_policy_id="adapter-certifiers",
                minimum_trust_policy_generation=2,
            )


if __name__ == "__main__":
    unittest.main()
