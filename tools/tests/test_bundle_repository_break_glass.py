#!/usr/bin/env python3

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from typing import Iterator
import unittest


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, document: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8", newline="\n")


def invoke(command: list[str], environment: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(command, capture_output=True, text=True, check=False, env=environment)


@contextmanager
def hold_rollout_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        create_file = ctypes.windll.kernel32.CreateFileW
        create_file.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        create_file.restype = wintypes.HANDLE
        handle = create_file(str(path), 0xC0000000, 0, None, 4, 0x80, None)
        if handle == wintypes.HANDLE(-1).value:
            raise OSError("could not acquire test rollout lock")
        try:
            yield
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    else:
        import fcntl
        descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o660)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)


class BundleRepositoryBreakGlassIntegration(unittest.TestCase):
    python: Path
    tool: Path
    publisher: Path
    checker: Path
    verifier: Path

    def test_signed_offline_downgrade_is_exact_locked_audited_and_one_time(self) -> None:
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
            from cryptography.hazmat.primitives.serialization import (
                Encoding, NoEncryption, PrivateFormat, PublicFormat,
            )
        except ImportError as error:
            self.fail(f"release-host cryptography is required: {error}")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "target"
            live = root / "bundles"
            state = root / "state"
            evidence = root / "publisher-evidence"
            publisher_keys = root / "publisher-keys"
            approver_keys = root / "approver-keys"
            target.mkdir()
            live.mkdir()
            state.mkdir()
            publisher_keys.mkdir()
            approver_keys.mkdir()
            (target / "candidate.bndl").write_bytes(b"authorized-target-v4")
            (live / "current.bndl").write_bytes(b"current-v9")

            sbom = root / "runtime.spdx.json"
            sbom_document = {
                "spdxVersion": "SPDX-2.3", "dataLicense": "CC0-1.0",
                "SPDXID": "SPDXRef-DOCUMENT",
                "documentNamespace": "https://pocodds.local/spdx/break-glass-test",
                "packages": [{"name": "PocoDDSRuntime", "versionInfo": "0.4.0"}],
            }
            write_json(sbom, sbom_document)
            artifact = target / "candidate.bndl"
            entries = [{"path": "target/candidate.bndl", "size": artifact.stat().st_size,
                        "sha256": sha256(artifact)}]
            artifact_set = hashlib.sha256(json.dumps(
                entries, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            manifest = root / "SHA256SUMS.json"
            write_json(manifest, {
                "schemaVersion": 1, "product": "PocoDDSRuntime", "version": "0.4.0",
                "gitCommit": "4" * 40, "dirty": False,
                "generatedAt": datetime.now(timezone.utc).isoformat(), "files": entries,
                "sbom": {"path": sbom.name, "sha256": sha256(sbom),
                         "spdxVersion": "SPDX-2.3",
                         "documentNamespace": sbom_document["documentNamespace"]},
                "provenance": {"builderId": "integration-builder", "buildProfile": "server",
                               "artifactSetSha256": artifact_set,
                               "source": {"gitCommit": "4" * 40, "dirty": False}},
            })

            publisher_key = Ed25519PrivateKey.generate()
            publisher_private = root / "publisher-private.pem"
            publisher_public = publisher_keys / "publisher-2026.pem"
            publisher_private.write_bytes(publisher_key.private_bytes(
                Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()))
            publisher_public.write_bytes(publisher_key.public_key().public_bytes(
                Encoding.PEM, PublicFormat.SubjectPublicKeyInfo))
            publisher_policy = root / "publisher-policy.json"
            write_json(publisher_policy, {
                "schemaVersion": 1, "product": "PocoDDSBundleRepository",
                "policyId": "publisher-policy-v1",
                "allowedPublishers": [{
                    "publisherId": "release-team", "keyId": "publisher-2026",
                    "algorithm": "Ed25519", "publicKeySha256": sha256(publisher_public),
                    "repositoryPatterns": ["runtime-main"],
                }], "revokedKeys": [],
            })
            environment = dict(os.environ)
            environment["PDR_BREAK_GLASS_PUBLISHER_KEY"] = str(publisher_private)
            published = invoke([
                str(self.python), str(self.publisher), "sign",
                "--repository", str(target), "--fingerprint-executable", str(self.checker),
                "--repository-id", "runtime-main", "--rollout-sequence", "4",
                "--publisher-id", "release-team", "--key-id", "publisher-2026",
                "--private-key-path-environment", "PDR_BREAK_GLASS_PUBLISHER_KEY",
                "--output-directory", str(evidence), "--release-manifest", str(manifest),
                "--release-sbom", str(sbom), "--release-artifacts-root", str(root),
            ], environment)
            self.assertEqual(published.returncode, 0, published.stdout + published.stderr)
            target_digest = json.loads(published.stdout)["candidateDigest"]

            live_fingerprint = invoke([str(self.checker), "fingerprint", str(live)])
            self.assertEqual(live_fingerprint.returncode, 0,
                             live_fingerprint.stdout + live_fingerprint.stderr)
            current_digest = live_fingerprint.stdout.strip().split("sha256=", 1)[1]

            current = {
                "schemaVersion": "2", "repositoryId": "runtime-main", "rolloutSequence": "9",
                "candidateDigest": current_digest, "publisherId": "release-team",
                "signingKeyId": "publisher-2026", "trustPolicyId": "publisher-policy-v1",
                "trustPolicySha256": sha256(publisher_policy), "attestationSha256": "8" * 64,
                "releaseManifestSha256": "7" * 64, "sbomSha256": "6" * 64,
                "artifactSetSha256": "5" * 64, "releaseVersion": "0.9.0",
                "gitCommit": "9" * 40, "builderId": "integration-builder",
                "buildProfile": "server", "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            high_water = state / "repository-rollout-high-water.properties"
            high_water.write_text("".join(f"{key}={value}\n" for key, value in current.items()),
                                  encoding="utf-8", newline="\n")

            common_target = [
                "--target-repository", str(target),
                "--fingerprint-executable", str(self.checker), "--repository-id", "runtime-main",
                "--evidence-directory", str(evidence),
                "--publisher-trust-policy", str(publisher_policy),
                "--expected-publisher-trust-policy-id", "publisher-policy-v1",
                "--expected-publisher-trust-policy-sha256", sha256(publisher_policy),
                "--publisher-trusted-keys-directory", str(publisher_keys),
            ]
            authorization = invoke([str(self.checker), "authorize", str(target),
                                    "--repository-id", "runtime-main",
                                    "--evidence-directory", str(evidence),
                                    "--trust-policy-file", str(publisher_policy),
                                    "--expected-trust-policy-id", "publisher-policy-v1",
                                    "--expected-trust-policy-sha256", sha256(publisher_policy),
                                    "--trusted-keys-directory", str(publisher_keys)])
            self.assertEqual(authorization.returncode, 0,
                             authorization.stdout + authorization.stderr)
            self.assertEqual(json.loads(authorization.stdout)["candidateDigest"], target_digest)

            request = root / "downgrade-request.json"
            requested = invoke([
                str(self.python), str(self.tool), "request", "--state-dir", str(state),
                "--repository", str(live),
                *common_target, "--reason", "Production regression requires known-good rollback",
                "--ticket", "INC-2026-0042", "--valid-for-minutes", "30", "--output", str(request),
            ])
            self.assertEqual(requested.returncode, 0, requested.stdout + requested.stderr)

            approver_material: list[tuple[str, str, Path, Path]] = []
            for approver_id, key_id in (("recovery-officer", "recovery-officer-2026"),
                                        ("security-officer", "security-officer-2026")):
                key = Ed25519PrivateKey.generate()
                private = root / f"{key_id}-private.pem"
                public = approver_keys / f"{key_id}.pem"
                private.write_bytes(key.private_bytes(
                    Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()))
                public.write_bytes(key.public_key().public_bytes(
                    Encoding.PEM, PublicFormat.SubjectPublicKeyInfo))
                approver_material.append((approver_id, key_id, private, public))
            approver_policy = root / "approver-policy.json"
            write_json(approver_policy, {
                "schemaVersion": 1, "product": "PocoDDSBundleRepositoryBreakGlass",
                "policyId": "break-glass-policy-v1", "maxApprovalLifetimeSeconds": 3600,
                "minimumApprovals": 2,
                "allowedApprovers": [{
                    "approverId": approver_id, "keyId": key_id,
                    "algorithm": "Ed25519", "publicKeySha256": sha256(public),
                    "repositoryPatterns": ["runtime-main"], "actions": ["downgrade-high-water"],
                    "notBefore": (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(),
                    "notAfter": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
                } for approver_id, key_id, _, public in approver_material], "revokedKeys": [],
            })
            signatures: list[Path] = []
            for index, (approver_id, key_id, private, _) in enumerate(approver_material, start=1):
                environment_name = f"PDR_BREAK_GLASS_APPROVER_KEY_{index}"
                environment[environment_name] = str(private)
                signature = root / f"downgrade-request.{key_id}.sig.json"
                approved = invoke([
                    str(self.python), str(self.tool), "approve", "--request", str(request),
                    "--approver-id", approver_id, "--key-id", key_id,
                    "--private-key-path-environment", environment_name,
                    "--signature-output", str(signature),
                ], environment)
                self.assertEqual(approved.returncode, 0, approved.stdout + approved.stderr)
                signatures.append(signature)

            apply_command = [
                str(self.python), str(self.tool), "apply", "--state-dir", str(state),
                "--repository", str(live), *common_target, "--request", str(request),
                "--signature", str(signatures[0]), "--signature", str(signatures[1]),
                "--approver-trust-policy", str(approver_policy),
                "--expected-approver-trust-policy-id", "break-glass-policy-v1",
                "--expected-approver-trust-policy-sha256", sha256(approver_policy),
                "--approver-trusted-keys-directory", str(approver_keys),
                "--signature-check-executable", str(self.verifier),
            ]
            preflight_command = list(apply_command)
            preflight_command[2] = "preflight"
            preflight_report = root / "break-glass-preflight.json"
            preflight = invoke([*preflight_command, "--report", str(preflight_report)])
            self.assertEqual(preflight.returncode, 0, preflight.stdout + preflight.stderr)
            preflight_evidence = json.loads(preflight.stdout)
            self.assertEqual(preflight_evidence["result"], "BUNDLE_BREAK_GLASS_PREFLIGHT_PASS")
            self.assertFalse(preflight_evidence["applyReady"])
            self.assertFalse(preflight_evidence["repositorySwitchPerformed"])
            self.assertFalse(preflight_evidence["approvalConsumed"])
            self.assertTrue(preflight_evidence["temporaryStagingRemoved"])
            supplied_evidence_sha = preflight_evidence.pop("evidenceSha256")
            actual_evidence_sha = hashlib.sha256(json.dumps(
                preflight_evidence, ensure_ascii=False, sort_keys=True,
                separators=(",", ":")).encode()).hexdigest()
            self.assertEqual(supplied_evidence_sha, actual_evidence_sha)
            self.assertTrue(preflight_report.is_file())
            self.assertTrue((live / "current.bndl").is_file())
            self.assertFalse((root / "bundles.pdr-previous").exists())
            self.assertFalse((root / "bundles.pdr-break-glass-staging").exists())
            self.assertFalse((state / "break-glass-consumed").exists())

            offline_preflight = invoke([*preflight_command, "--runtime-stopped"])
            self.assertEqual(offline_preflight.returncode, 0,
                             offline_preflight.stdout + offline_preflight.stderr)
            self.assertTrue(json.loads(offline_preflight.stdout)["applyReady"])

            no_ack = invoke(apply_command)
            self.assertEqual(no_ack.returncode, 2)
            self.assertIn("--runtime-stopped", no_ack.stderr)
            self.assertTrue((live / "current.bndl").is_file())

            single_signature = list(apply_command)
            second_signature = len(single_signature) - 1 - single_signature[::-1].index("--signature")
            del single_signature[second_signature:second_signature + 2]
            quorum_rejected = invoke([*single_signature, "--runtime-stopped"])
            self.assertEqual(quorum_rejected.returncode, 2)
            self.assertIn("quorum not met: 1/2", quorum_rejected.stderr)

            duplicate_signature = list(apply_command)
            duplicate_signature[duplicate_signature.index(str(signatures[1]))] = str(signatures[0])
            duplicate_rejected = invoke([*duplicate_signature, "--runtime-stopped"])
            self.assertEqual(duplicate_rejected.returncode, 2)
            self.assertIn("duplicate break-glass signature", duplicate_rejected.stderr)

            copied_signature = root / "copied-recovery-officer.sig.json"
            shutil.copy2(signatures[0], copied_signature)
            duplicate_identity = list(apply_command)
            duplicate_identity[duplicate_identity.index(str(signatures[1]))] = str(copied_signature)
            identity_rejected = invoke([*duplicate_identity, "--runtime-stopped"])
            self.assertEqual(identity_rejected.returncode, 2)
            self.assertIn("distinct approvers and keys", identity_rejected.stderr)

            expired_request = root / "expired-request.json"
            expired_document = json.loads(request.read_text(encoding="utf-8"))
            expired_document["issuedAt"] = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
            expired_document["expiresAt"] = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
            write_json(expired_request, expired_document)
            expired_command = list(apply_command)
            expired_command[expired_command.index("--request") + 1] = str(expired_request)
            expired = invoke([*expired_command, "--runtime-stopped"])
            self.assertEqual(expired.returncode, 2)
            self.assertIn("expired", expired.stderr)

            tampered_request = root / "tampered-request.json"
            tampered_document = json.loads(request.read_text(encoding="utf-8"))
            tampered_document["reason"] += " unauthorized edit"
            write_json(tampered_request, tampered_document)
            tampered_command = list(apply_command)
            tampered_command[tampered_command.index("--request") + 1] = str(tampered_request)
            tampered = invoke([*tampered_command, "--runtime-stopped"])
            self.assertEqual(tampered.returncode, 2)
            self.assertIn("signature verification", tampered.stderr)
            self.assertTrue((live / "current.bndl").is_file())

            original_live = (live / "current.bndl").read_bytes()
            (live / "current.bndl").write_bytes(b"unapproved-current-drift")
            source_drift = invoke([*apply_command, "--runtime-stopped"])
            self.assertEqual(source_drift.returncode, 2)
            self.assertIn("current Bundle repository differs", source_drift.stderr)
            (live / "current.bndl").write_bytes(original_live)

            original_target = (target / "candidate.bndl").read_bytes()
            (target / "candidate.bndl").write_bytes(b"unapproved-target")
            wrong_target = invoke([*apply_command, "--runtime-stopped"])
            self.assertEqual(wrong_target.returncode, 2)
            self.assertIn("target Bundle authorization", wrong_target.stderr)
            self.assertTrue((live / "current.bndl").is_file())
            (target / "candidate.bndl").write_bytes(original_target)

            original_high_water = high_water.read_bytes()
            high_water.write_bytes(original_high_water + b"# drift\n")
            drift = invoke([*apply_command, "--runtime-stopped"])
            self.assertEqual(drift.returncode, 2)
            self.assertIn("high-water changed", drift.stderr)
            self.assertTrue((live / "current.bndl").is_file())
            high_water.write_bytes(original_high_water)

            with hold_rollout_lock(state / "repository-rollout-high-water.lock"):
                locked = invoke([*apply_command, "--runtime-stopped"])
            self.assertEqual(locked.returncode, 2)
            self.assertIn("lease is held", locked.stderr)
            self.assertTrue((live / "current.bndl").is_file())

            applied = invoke([*apply_command, "--runtime-stopped"])
            self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
            result = json.loads(applied.stdout)
            self.assertEqual(result["targetSequence"], 4)
            self.assertEqual(result["approvalCount"], 2)
            self.assertEqual(result["minimumApprovals"], 2)
            self.assertEqual(result["transactionState"], "completed")
            self.assertTrue((live / "candidate.bndl").is_file())
            self.assertTrue((root / "bundles.pdr-previous" / "current.bndl").is_file())
            self.assertIn("rolloutSequence=4\n", high_water.read_text(encoding="utf-8"))
            consumed = state / "break-glass-consumed" / f"{result['approvalId']}.json"
            self.assertTrue(consumed.is_file())
            audit_path = state / "break-glass-audit.jsonl"
            audit = audit_path.read_text(encoding="utf-8")
            self.assertIn("BUNDLE_BREAK_GLASS_AUTHORIZED", audit)
            self.assertIn("BUNDLE_BREAK_GLASS_APPLIED", audit)

            journal_path = Path(result["transactionJournal"])
            journal = json.loads(journal_path.read_text(encoding="utf-8"))
            self.assertEqual(journal["state"], "completed")

            # Simulate a process crash after the high-water commit but before consumption.
            authorized_line = audit.splitlines()[0]
            audit_path.write_text(authorized_line + "\n", encoding="utf-8", newline="\n")
            consumed.unlink()
            for field in ("consumptionSha256", "appliedAuditSha256", "recoveryResult"):
                journal.pop(field, None)
            journal["state"] = "activated"
            journal_without_hash = {key: value for key, value in journal.items()
                                    if key != "transactionSha256"}
            journal["transactionSha256"] = hashlib.sha256(json.dumps(
                journal_without_hash, ensure_ascii=False, sort_keys=True,
                separators=(",", ":")).encode()).hexdigest()
            write_json(journal_path, journal)
            recover_command = [
                str(self.python), str(self.tool), "recover", "--state-dir", str(state),
                "--repository", str(live), "--fingerprint-executable", str(self.checker),
                "--approval-id", result["approvalId"],
            ]
            recover_no_ack = invoke(recover_command)
            self.assertEqual(recover_no_ack.returncode, 2)
            self.assertIn("--runtime-stopped", recover_no_ack.stderr)
            recovered_forward = invoke([*recover_command, "--runtime-stopped"])
            self.assertEqual(recovered_forward.returncode, 0,
                             recovered_forward.stdout + recovered_forward.stderr)
            self.assertEqual(json.loads(recovered_forward.stdout)["result"],
                             "BUNDLE_BREAK_GLASS_RECOVERY_FORWARD_COMPLETED")
            self.assertTrue(consumed.is_file())
            journal = json.loads(journal_path.read_text(encoding="utf-8"))
            self.assertEqual(journal["state"], "completed")
            audit = audit_path.read_text(encoding="utf-8")
            self.assertIn("BUNDLE_BREAK_GLASS_APPLIED", audit)
            recovered_forward_again = invoke([*recover_command, "--runtime-stopped"])
            self.assertEqual(recovered_forward_again.returncode, 0,
                             recovered_forward_again.stdout + recovered_forward_again.stderr)
            self.assertEqual(json.loads(recovered_forward_again.stdout)["result"],
                             "BUNDLE_BREAK_GLASS_RECOVERY_ALREADY_COMPLETED")

            # Simulate a crash before high-water commit: source is still live and target is staged.
            rollback_root = root / "rollback-case"
            rollback_state = rollback_root / "state"
            rollback_live = rollback_root / "bundles"
            rollback_staging = rollback_root / "bundles.pdr-break-glass-staging"
            rollback_previous = rollback_root / "bundles.pdr-previous"
            rollback_state.mkdir(parents=True)
            shutil.copytree(root / "bundles.pdr-previous", rollback_previous)
            shutil.copytree(target, rollback_staging)
            rollback_high_water = rollback_state / "repository-rollout-high-water.properties"
            rollback_high_water.write_bytes(original_high_water)
            rollback_audit = rollback_state / "break-glass-audit.jsonl"
            rollback_audit.write_text(authorized_line + "\n", encoding="utf-8", newline="\n")
            rollback_journal = dict(journal)
            for field in ("consumptionSha256", "appliedAuditSha256", "recoveryResult"):
                rollback_journal.pop(field, None)
            rollback_journal.update({
                "state": "previousSaved", "repository": str(rollback_live.resolve()),
                "staging": str(rollback_staging.resolve()),
                "previous": str(rollback_previous.resolve()),
                "sourceStateSha256": hashlib.sha256(original_high_water).hexdigest(),
            })
            rollback_without_hash = {key: value for key, value in rollback_journal.items()
                                     if key != "transactionSha256"}
            rollback_journal["transactionSha256"] = hashlib.sha256(json.dumps(
                rollback_without_hash, ensure_ascii=False, sort_keys=True,
                separators=(",", ":")).encode()).hexdigest()
            rollback_journal_path = (rollback_state / "break-glass-transactions" /
                                     f"{result['approvalId']}.json")
            write_json(rollback_journal_path, rollback_journal)
            recovered_rollback = invoke([
                str(self.python), str(self.tool), "recover", "--state-dir", str(rollback_state),
                "--repository", str(rollback_live),
                "--fingerprint-executable", str(self.checker),
                "--approval-id", result["approvalId"], "--runtime-stopped",
            ])
            self.assertEqual(recovered_rollback.returncode, 0,
                             recovered_rollback.stdout + recovered_rollback.stderr)
            self.assertEqual(json.loads(recovered_rollback.stdout)["result"],
                             "BUNDLE_BREAK_GLASS_RECOVERY_ROLLED_BACK")
            self.assertTrue((rollback_live / "current.bndl").is_file())
            self.assertFalse(rollback_staging.exists())
            self.assertEqual(json.loads(rollback_journal_path.read_text(encoding="utf-8"))["state"],
                             "rolledBack")
            self.assertIn("BUNDLE_BREAK_GLASS_RECOVERED_ROLLBACK",
                          rollback_audit.read_text(encoding="utf-8"))
            recovered_rollback_again = invoke([
                str(self.python), str(self.tool), "recover", "--state-dir", str(rollback_state),
                "--repository", str(rollback_live),
                "--fingerprint-executable", str(self.checker),
                "--approval-id", result["approvalId"], "--runtime-stopped",
            ])
            self.assertEqual(recovered_rollback_again.returncode, 0,
                             recovered_rollback_again.stdout + recovered_rollback_again.stderr)
            self.assertEqual(json.loads(recovered_rollback_again.stdout)["result"],
                             "BUNDLE_BREAK_GLASS_RECOVERY_ALREADY_ROLLED_BACK")

            replay = invoke([*apply_command, "--runtime-stopped"])
            self.assertEqual(replay.returncode, 2)
            self.assertIn("already consumed", replay.stderr)
            audit_verified = invoke([
                str(self.python), str(self.tool), "verify-audit", "--state-dir", str(state)])
            self.assertEqual(audit_verified.returncode, 0,
                             audit_verified.stdout + audit_verified.stderr)
            audit_report = json.loads(audit_verified.stdout)
            self.assertEqual(audit_report["recordCount"], 2)
            records = [json.loads(line) for line in audit.splitlines()]
            self.assertEqual(records[1]["previousRecordSha256"], records[0]["recordSha256"])
            records[0]["ticket"] = "INC-TAMPERED"
            audit_path.write_text("\n".join(json.dumps(record, sort_keys=True)
                                            for record in records) + "\n", encoding="utf-8")
            audit_tampered = invoke([
                str(self.python), str(self.tool), "verify-audit", "--state-dir", str(state)])
            self.assertEqual(audit_tampered.returncode, 2)
            self.assertIn("hash mismatch", audit_tampered.stderr)
            print("BUNDLE_BREAK_GLASS_INTEGRATION_PASS approval=2-of-N target=authorized "
                  "preflight=no-mutation source-drift=rejected expired=rejected "
                  "tamper=rejected drift=rejected lock=exclusive "
                  "replay=rejected crash-before-commit=rolled-back "
                  "crash-after-commit=forward-completed audit=hash-chained "
                  "audit-tamper=rejected swap=atomic")


if __name__ == "__main__":
    options = argparse.ArgumentParser(add_help=False)
    options.add_argument("--python", type=Path, required=True)
    options.add_argument("--tool", type=Path, required=True)
    options.add_argument("--publisher", type=Path, required=True)
    options.add_argument("--checker", type=Path, required=True)
    options.add_argument("--verifier", type=Path, required=True)
    parsed, remaining = options.parse_known_args()
    BundleRepositoryBreakGlassIntegration.python = parsed.python.resolve()
    BundleRepositoryBreakGlassIntegration.tool = parsed.tool.resolve()
    BundleRepositoryBreakGlassIntegration.publisher = parsed.publisher.resolve()
    BundleRepositoryBreakGlassIntegration.checker = parsed.checker.resolve()
    BundleRepositoryBreakGlassIntegration.verifier = parsed.verifier.resolve()
    unittest.main(argv=[__file__, *remaining])
