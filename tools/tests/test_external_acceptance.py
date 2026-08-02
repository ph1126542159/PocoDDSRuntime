import argparse
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat


TOOL = Path(__file__).resolve().parents[1] / "external_acceptance.py"
SPEC = importlib.util.spec_from_file_location("external_acceptance_under_test", TOOL)
assert SPEC and SPEC.loader
EXTERNAL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EXTERNAL)


class ExternalAcceptanceTests(unittest.TestCase):
    verifier = (Path(__file__).resolve().parents[2] / "build/full/bin/pdr-signature-check.exe").resolve()

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


if __name__ == "__main__":
    arguments = argparse.ArgumentParser()
    arguments.add_argument("--verifier", type=Path, required=True)
    parsed, remaining = arguments.parse_known_args()
    ExternalAcceptanceTests.verifier = parsed.verifier.resolve()
    unittest.main(argv=[__file__, *remaining])
