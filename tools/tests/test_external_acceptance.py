import argparse
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from types import SimpleNamespace

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat


TOOL = Path(__file__).resolve().parents[1] / "external_acceptance.py"
SPEC = importlib.util.spec_from_file_location("external_acceptance_under_test", TOOL)
assert SPEC and SPEC.loader
EXTERNAL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EXTERNAL)
PIPELINE_SPEC = importlib.util.spec_from_file_location(
    "project_pipeline_external_test", Path(__file__).resolve().parents[1] / "project_pipeline.py"
)
assert PIPELINE_SPEC and PIPELINE_SPEC.loader
PROJECT_PIPELINE = importlib.util.module_from_spec(PIPELINE_SPEC)
PIPELINE_SPEC.loader.exec_module(PROJECT_PIPELINE)
PDR_SPEC = importlib.util.spec_from_file_location(
    "pdr_external_types_test", Path(__file__).resolve().parents[1] / "pdr.py"
)
assert PDR_SPEC and PDR_SPEC.loader
PDR = importlib.util.module_from_spec(PDR_SPEC)
PDR_SPEC.loader.exec_module(PDR)


class ExternalAcceptanceTests(unittest.TestCase):
    verifier = (Path(__file__).resolve().parents[2] / "build/bin/pdr-signature-check.exe").resolve()

    def test_cli_and_external_tool_acceptance_types_are_identical(self):
        self.assertEqual(set(PDR.EXTERNAL_ACCEPTANCE_TYPES), set(EXTERNAL.ACCEPTANCE_CHECKS))

    @staticmethod
    def signing_key(root: Path) -> tuple[Path, Path]:
        key = Ed25519PrivateKey.generate()
        private = root / "private.pem"
        public = root / "public.pem"
        private.write_bytes(key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()))
        public.write_bytes(key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo))
        return private, public

    def test_template_approval_verification_and_tamper_rejection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "SHA256SUMS.json"
            manifest.write_text("{}\n", encoding="utf-8")
            template = root / "template.json"
            template_args = EXTERNAL.parser().parse_args([
                "template", "--type", "petalinux-target", "--version", "1.2.3",
                "--git-commit", "abc", "--artifact-manifest", str(manifest),
                "--output", str(template),
            ])
            self.assertEqual(EXTERNAL.create_template(template_args), 0)
            check_ids = EXTERNAL.ACCEPTANCE_CHECKS["petalinux-target"]
            evidence_args = []
            for check in check_ids:
                attachment = root / f"{check}.txt"
                attachment.write_text(f"evidence for {check}\n", encoding="utf-8")
                evidence_args += ["--evidence", f"{check}={attachment}"]
            report = root / "approved.json"
            signature = root / "approved.sig.json"
            private, public = self.signing_key(root)
            approval_args = EXTERNAL.parser().parse_args([
                "approve", "--template", str(template), *evidence_args,
                "--approver-id", "qa-team", "--approval-record", "CHANGE-42",
                "--confirm-all-checks-passed", "--output", str(report),
                "--signature-output", str(signature), "--key-id", "qa-key",
                "--private-key-path-environment", "PDR_TEST_EXTERNAL_PRIVATE_KEY",
            ])
            with mock.patch.dict(os.environ, {"PDR_TEST_EXTERNAL_PRIVATE_KEY": str(private)}):
                self.assertEqual(EXTERNAL.approve(approval_args), 0)
            verified = EXTERNAL.verify_report(
                report, "petalinux-target", "1.2.3", "abc", EXTERNAL.digest(manifest))
            self.assertTrue(verified["verified"])
            self.assertEqual(verified["attachmentCount"], len(check_ids))
            policy = root / "trust-policy.json"
            policy.write_text(json.dumps({
                "schemaVersion": 1, "product": "PocoDDSRuntimeExternalAcceptance",
                "policyId": "qa-policy", "allowedApprovers": [{
                    "approverId": "qa-team", "keyId": "qa-key", "algorithm": "Ed25519",
                    "publicKeyPath": public.name, "publicKeySha256": EXTERNAL.digest(public),
                    "acceptanceTypes": ["petalinux-target"],
                }], "revokedKeys": [],
            }), encoding="utf-8")
            signed = EXTERNAL.verify_signed_report(
                report, signature, policy, "qa-policy", EXTERNAL.digest(policy), self.verifier,
                "petalinux-target", "1.2.3", "abc", EXTERNAL.digest(manifest))
            self.assertTrue(signed["signatureVerified"])
            revoked = json.loads(policy.read_text(encoding="utf-8"))
            revoked["revokedKeys"] = [{
                "keyId": "qa-key", "revokedAt": "2026-01-01T00:00:00+00:00",
                "reason": "test revocation",
            }]
            policy.write_text(json.dumps(revoked), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "key is revoked"):
                EXTERNAL.verify_signed_report(
                    report, signature, policy, "qa-policy", EXTERNAL.digest(policy), self.verifier,
                    "petalinux-target", "1.2.3", "abc", EXTERNAL.digest(manifest))

            document = json.loads(report.read_text(encoding="utf-8"))
            document["approval"]["record"] = "CHANGED"
            report.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "content digest mismatch"):
                EXTERNAL.verify_report(report, "petalinux-target", "1.2.3", "abc",
                                       EXTERNAL.digest(manifest))

    def test_approval_requires_every_check_and_confirmation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "manifest.json"
            manifest.write_text("{}", encoding="utf-8")
            template = root / "template.json"
            args = EXTERNAL.parser().parse_args([
                "template", "--type", "soak-24h", "--version", "1", "--git-commit", "abc",
                "--artifact-manifest", str(manifest), "--output", str(template),
            ])
            EXTERNAL.create_template(args)
            approval = EXTERNAL.parser().parse_args([
                "approve", "--template", str(template), "--approver-id", "qa",
                "--approval-record", "TICKET", "--output", str(root / "approved.json"),
                "--signature-output", str(root / "approved.sig.json"), "--key-id", "qa-key",
                "--private-key-path-environment", "PDR_TEST_EXTERNAL_PRIVATE_KEY",
            ])
            with self.assertRaisesRegex(ValueError, "confirm-all-checks-passed"):
                EXTERNAL.approve(approval)

    def test_project_soak_requirement_is_content_bound(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            attachment = root / "soak.log"
            attachment.write_text("72 hour evidence\n", encoding="utf-8")
            evidence = {
                "path": attachment.name,
                "size": attachment.stat().st_size,
                "sha256": EXTERNAL.digest(attachment),
            }
            report = root / "soak-approved.json"
            document = {
                "schemaVersion": 1,
                "operation": "external-acceptance",
                "passed": True,
                "verdict": "APPROVED",
                "acceptanceType": "project-soak",
                "approvedAt": "2026-08-22T00:00:00+00:00",
                "candidate": {
                    "version": "1.2.3", "gitCommit": "abc",
                    "artifactManifestSha256": "a" * 64,
                },
                "requirements": {"minimumHours": "72"},
                "checks": [
                    {"id": check, "status": "PASSED", "evidence": [evidence]}
                    for check in EXTERNAL.ACCEPTANCE_CHECKS["project-soak"]
                ],
                "approval": {"approverId": "soak-lab", "record": "SOAK-72"},
            }
            document["contentSha256"] = EXTERNAL.content_digest(document)
            report.write_text(json.dumps(document), encoding="utf-8")
            verified = EXTERNAL.verify_report(
                report, "project-soak", "1.2.3", "abc", "a" * 64,
                {"minimumHours": "72"},
            )
            self.assertTrue(verified["verified"])
            with self.assertRaisesRegex(ValueError, "requirements mismatch"):
                EXTERNAL.verify_report(
                    report, "project-soak", "1.2.3", "abc", "a" * 64,
                    {"minimumHours": "24"},
                )

    def test_signed_project_hil_evidence_closes_only_the_matching_candidate_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, build = root / "source", root / "build"
            source.mkdir()
            build.mkdir()
            lock = build / "pdr-project.lock.json"
            lock.write_text('{"candidate":"one"}\n', encoding="utf-8")
            plan = build / "plan.json"
            plan.write_text(json.dumps({
                "schemaVersion": 1,
                "pipelineId": "project-hil-test",
                "sourceRoot": str(source),
                "buildRoot": str(build),
                "metadata": {
                    "planType": "pdr-project-qualification",
                    "project": "robot-product",
                    "candidateVersion": "1.2.3",
                    "externalGates": [{"id": "hil", "status": "REQUIRED"}],
                },
                "stages": [{"id": "automated", "command": ["unused"]}],
            }), encoding="utf-8")
            state = build / "state.json"
            state.write_text(json.dumps({
                "schemaVersion": 1,
                "operation": "release-pipeline",
                "pipelineId": "project-hil-test",
                "status": "complete",
                "planSha256": hashlib.sha256(plan.read_bytes()).hexdigest(),
                "source": {"commit": "candidate-commit", "worktreeSha256": "a" * 64,
                           "changeCount": 0},
                "stages": [{"id": "automated", "status": "passed"}],
            }), encoding="utf-8")

            template = root / "hil-template.json"
            template_args = EXTERNAL.parser().parse_args([
                "template", "--type", "project-hil", "--version", "1.2.3",
                "--git-commit", "candidate-commit", "--artifact-manifest", str(lock),
                "--output", str(template),
            ])
            self.assertEqual(EXTERNAL.create_template(template_args), 0)
            evidence_args = []
            for check in EXTERNAL.ACCEPTANCE_CHECKS["project-hil"]:
                attachment = root / f"{check}.txt"
                attachment.write_text(f"evidence for {check}\n", encoding="utf-8")
                evidence_args += ["--evidence", f"{check}={attachment}"]
            report = root / "hil-approved.json"
            signature = root / "hil-approved.sig.json"
            private, public = self.signing_key(root)
            approve_args = EXTERNAL.parser().parse_args([
                "approve", "--template", str(template), *evidence_args,
                "--approver-id", "hil-lab", "--approval-record", "HIL-42",
                "--confirm-all-checks-passed", "--output", str(report),
                "--signature-output", str(signature), "--key-id", "hil-key",
                "--private-key-path-environment", "PDR_TEST_PROJECT_HIL_KEY",
            ])
            with mock.patch.dict(os.environ, {"PDR_TEST_PROJECT_HIL_KEY": str(private)}):
                self.assertEqual(EXTERNAL.approve(approve_args), 0)
            policy = root / "trust-policy.json"
            policy.write_text(json.dumps({
                "schemaVersion": 1,
                "product": "PocoDDSRuntimeExternalAcceptance",
                "policyId": "project-qa",
                "allowedApprovers": [{
                    "approverId": "hil-lab", "keyId": "hil-key", "algorithm": "Ed25519",
                    "publicKeyPath": public.name,
                    "publicKeySha256": EXTERNAL.digest(public),
                    "acceptanceTypes": ["project-hil"],
                }],
                "revokedKeys": [],
            }), encoding="utf-8")
            status_args = SimpleNamespace(
                plan=plan, state=state,
                external_evidence=[("hil", report)],
                external_signature=[("hil", signature)],
                trust_policy=policy,
                expected_trust_policy_id="project-qa",
                expected_trust_policy_sha256=EXTERNAL.digest(policy),
                signature_check_executable=self.verifier,
            )
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(PROJECT_PIPELINE.status(status_args), 0)
            status = json.loads(output.getvalue())
            self.assertTrue(status["releaseReady"])
            self.assertEqual(status["externalGates"][0]["status"], "APPROVED")

            lock.write_text('{"candidate":"different"}\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "candidate artifact manifest mismatch"):
                PROJECT_PIPELINE.status(status_args)


if __name__ == "__main__":
    arguments = argparse.ArgumentParser()
    arguments.add_argument("--verifier", type=Path, required=True)
    parsed, remaining = arguments.parse_known_args()
    ExternalAcceptanceTests.verifier = parsed.verifier.resolve()
    unittest.main(argv=[__file__, *remaining])
