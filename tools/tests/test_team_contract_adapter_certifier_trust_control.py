#!/usr/bin/env python3
"""Adapter certifier trust-control acceptance tests."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from argparse import Namespace
from copy import deepcopy
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import team_contract_adapter_certifier_trust_control as control


NOW = "2026-08-27T10:00:00+00:00"


def write_json(path: Path, document: dict) -> str:
    path.write_text(json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n",
                    encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def key_pair(directory: Path, identity: str) -> tuple[Path, str]:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import (
        Encoding, NoEncryption, PrivateFormat, PublicFormat,
    )
    key = Ed25519PrivateKey.generate()
    private = directory / f"{identity}.private.pem"
    public = directory / f"{identity}.pem"
    private.write_bytes(key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8,
                                          NoEncryption()))
    public.write_bytes(key.public_key().public_bytes(Encoding.PEM,
                                                     PublicFormat.SubjectPublicKeyInfo))
    return private, hashlib.sha256(public.read_bytes()).hexdigest()


def trust_policy(generation: int, revoked: list[dict] | None = None) -> dict:
    return {
        "schemaVersion": 1,
        "product": "PocoDDSRuntimeTeamContractAdapterConformanceTrustPolicy",
        "policyId": "production-certifiers",
        "generation": generation,
        "maximumAttestationLifetimeSeconds": 3600,
        "allowedCertifiers": [{
            "certifierId": "release-certifier", "keyId": "certifier-key-1",
            "algorithm": "Ed25519", "publicKey": "keys/certifier-key-1.pem",
            "publicKeySha256": "1" * 64,
            "adapterKinds": ["fleet-executor"], "adapterIds": ["fleet-prod"],
            "notBefore": "2026-01-01T00:00:00+00:00",
            "notAfter": "2027-01-01T00:00:00+00:00",
        }],
        "revokedKeys": revoked or [],
    }


class TrustControlTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.keys = self.root / "keys"
        self.keys.mkdir()
        self.private: dict[str, Path] = {}
        approvers = []
        for person, key_id, roles in (
                ("security-a", "approval-key-a", ["emergency-revocation", "standard"]),
                ("security-b", "approval-key-b", ["standard"]),
                ("incident-a", "approval-key-c", ["emergency-revocation"])):
            private, digest = key_pair(self.keys, key_id)
            self.private[person] = private
            approvers.append({
                "approverId": person, "keyId": key_id, "algorithm": "Ed25519",
                "publicKeySha256": digest, "roles": sorted(roles),
            })
        self.governance = self.root / "governance.json"
        self.governance_sha = write_json(self.governance, {
            "schemaVersion": 1, "product": control.GOVERNANCE_PRODUCT,
            "policyId": "certifier-governance", "standardMinimumApprovals": 2,
            "emergencyMinimumApprovals": 1, "maxStandardLifetimeSeconds": 7200,
            "maxEmergencyLifetimeSeconds": 900, "allowedApprovers": approvers,
            "activatorIds": ["release-operator"], "revokedKeys": [],
        })
        self.active = self.root / "active.json"
        self.active_sha = write_json(self.active, trust_policy(1))

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def propose(self, candidate: dict, mode: str = "standard",
                proposer: str = "release-author", lifetime: int | None = None) \
            -> tuple[Path, Path, str, str]:
        candidate_path = self.root / f"candidate-{mode}.json"
        candidate_sha = write_json(candidate_path, candidate)
        proposal = self.root / f"proposal-{mode}.json"
        code = control.propose_command(Namespace(
            active_policy=str(self.active), expected_current_policy_sha256=self.active_sha,
            candidate_policy=str(candidate_path),
            expected_candidate_policy_sha256=candidate_sha,
            governance_policy=str(self.governance),
            expected_governance_policy_id="certifier-governance",
            expected_governance_policy_sha256=self.governance_sha,
            mode=mode, proposer_id=proposer, ticket="SEC-1042",
            reason="rotate certifier trust", issued_at=NOW,
            lifetime_seconds=lifetime or (600 if mode == "emergency-revocation" else 3600),
            output=str(proposal),
        ))
        self.assertEqual(code, 0)
        return candidate_path, proposal, candidate_sha, hashlib.sha256(proposal.read_bytes()).hexdigest()

    def approve(self, proposal: Path, proposal_sha: str, person: str,
                suffix: str) -> Path:
        output = self.root / f"approval-{suffix}.json"
        old = os.environ.get("PDR_TEST_APPROVAL_KEY")
        os.environ["PDR_TEST_APPROVAL_KEY"] = str(self.private[person])
        try:
            code = control.approve_command(Namespace(
                proposal=str(proposal), expected_proposal_sha256=proposal_sha,
                approver_id=person,
                key_id={"security-a": "approval-key-a", "security-b": "approval-key-b",
                        "incident-a": "approval-key-c"}[person],
                private_key_environment="PDR_TEST_APPROVAL_KEY",
                verification_time=NOW, output=str(output),
            ))
        finally:
            if old is None:
                os.environ.pop("PDR_TEST_APPROVAL_KEY", None)
            else:
                os.environ["PDR_TEST_APPROVAL_KEY"] = old
        self.assertEqual(code, 0)
        return output

    def activate(self, candidate_path: Path, candidate_sha: str, proposal: Path,
                 proposal_sha: str, approvals: list[Path], active_sha: str | None = None,
                 activator: str = "release-operator",
                 verification_time: str = NOW) -> int:
        return control.activate_command(Namespace(
            active_policy=str(self.active),
            expected_current_policy_sha256=active_sha or self.active_sha,
            candidate_policy=str(candidate_path),
            expected_candidate_policy_sha256=candidate_sha,
            proposal=str(proposal), expected_proposal_sha256=proposal_sha,
            approval=[str(item) for item in approvals],
            governance_policy=str(self.governance),
            expected_governance_policy_id="certifier-governance",
            expected_governance_policy_sha256=self.governance_sha,
            trusted_keys_directory=str(self.keys), activator_id=activator,
            verification_time=verification_time,
            report=str(self.root / "activation.json"),
        ))

    def test_standard_requires_two_distinct_people_and_atomic_successor(self) -> None:
        candidate = trust_policy(2)
        candidate["allowedCertifiers"][0]["adapterIds"].append("fleet-staging")
        candidate["allowedCertifiers"][0]["adapterIds"].sort()
        candidate_path, proposal, candidate_sha, proposal_sha = self.propose(candidate)
        first = self.approve(proposal, proposal_sha, "security-a", "a")
        before = self.active.read_bytes()
        self.assertEqual(self.activate(candidate_path, candidate_sha, proposal,
                                       proposal_sha, [first]), 2)
        self.assertEqual(self.active.read_bytes(), before)
        second = self.approve(proposal, proposal_sha, "security-b", "b")
        self.assertEqual(self.activate(candidate_path, candidate_sha, proposal,
                                       proposal_sha, [first, second]), 0)
        self.assertEqual(json.loads(self.active.read_text(encoding="utf-8"))["generation"], 2)
        report = json.loads((self.root / "activation.json").read_text(encoding="utf-8"))
        self.assertEqual(len(report["approvals"]), 2)
        self.assertEqual(report["activatorId"], "release-operator")

    def test_emergency_is_short_lived_revocation_only_and_separated(self) -> None:
        widened = trust_policy(2)
        widened["allowedCertifiers"][0]["adapterIds"].append("fleet-staging")
        with self.assertRaises(AssertionError):
            self.propose(widened, "emergency-revocation")
        emergency = trust_policy(2, [{
            "keyId": "certifier-key-1", "revokedAt": NOW,
            "reason": "incident SEC-1042",
        }])
        candidate_path, proposal, candidate_sha, proposal_sha = self.propose(
            emergency, "emergency-revocation")
        approval = self.approve(proposal, proposal_sha, "incident-a", "incident")
        before = self.active.read_bytes()
        self.assertEqual(self.activate(
            candidate_path, candidate_sha, proposal, proposal_sha, [approval],
            verification_time="2026-08-27T10:10:01+00:00"), 2)
        self.assertEqual(self.active.read_bytes(), before)
        self.assertEqual(self.activate(candidate_path, candidate_sha, proposal,
                                       proposal_sha, [approval]), 0)
        report = json.loads((self.root / "activation.json").read_text(encoding="utf-8"))
        self.assertEqual(report["mode"], "emergency-revocation")
        self.assertEqual(report["emergencyRevokedKeyIds"], ["certifier-key-1"])

    def test_proposer_and_activator_cannot_approve(self) -> None:
        candidate_path, proposal, candidate_sha, proposal_sha = self.propose(
            trust_policy(2), proposer="security-a")
        bad = self.approve(proposal, proposal_sha, "security-a", "proposer")
        good = self.approve(proposal, proposal_sha, "security-b", "good")
        before = self.active.read_bytes()
        self.assertEqual(self.activate(candidate_path, candidate_sha, proposal,
                                       proposal_sha, [bad, good]), 2)
        self.assertEqual(self.active.read_bytes(), before)

    def test_duplicate_approval_and_stale_active_policy_fail_closed(self) -> None:
        candidate_path, proposal, candidate_sha, proposal_sha = self.propose(
            trust_policy(2))
        first = self.approve(proposal, proposal_sha, "security-a", "duplicate")
        before = self.active.read_bytes()
        self.assertEqual(self.activate(candidate_path, candidate_sha, proposal,
                                       proposal_sha, [first, first]), 2)
        self.assertEqual(self.active.read_bytes(), before)
        second = self.approve(proposal, proposal_sha, "security-b", "stale")
        self.assertEqual(self.activate(
            candidate_path, candidate_sha, proposal, proposal_sha, [first, second],
            active_sha="0" * 64), 2)
        self.assertEqual(self.active.read_bytes(), before)


if __name__ == "__main__":
    result = unittest.main(exit=False, verbosity=2).result
    if result.wasSuccessful():
        print("PDR_ADAPTER_CERTIFIER_TRUST_CONTROL_PASS standardQuorum=2 "
              "separation=1 staged=1 atomic=1 emergencyRevocationOnly=1 expiry=1")
    raise SystemExit(0 if result.wasSuccessful() else 1)
