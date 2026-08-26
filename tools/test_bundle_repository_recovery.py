#!/usr/bin/env python3

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
import zipfile

import bundle_repository_recovery as recovery


def write_bundle(path: Path, symbolic_name: str) -> None:
    manifest = (
        "Manifest-Version: 1.0\n"
        f"Bundle-SymbolicName: {symbolic_name}\n"
        "Bundle-Version: 1.0.0\n"
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("META-INF/manifest.mf", manifest)


class BundleRepositoryRecoveryTest(unittest.TestCase):
    def test_status_and_offline_restore(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = root / "state"
            backup = state / "last-known-good"
            repository = root / "bundles"
            backup.mkdir(parents=True)
            repository.mkdir()
            write_bundle(backup / "0000_pdr.test_1.0.0.bndl", "pdr.test")
            write_bundle(repository / "broken-current.bndl", "pdr.current")
            (state / "transaction.properties").write_text(
                "transactionId=test\nstate=restartRequired\nbundleCount=1\n", encoding="utf-8"
            )

            before = recovery.status(state, repository)
            self.assertTrue(before["restartRequired"])
            self.assertTrue(before["backupAvailable"])
            self.assertEqual(before["backupBundleCount"], 1)

            result = recovery.restore(state, repository, runtime_stopped=True)
            self.assertEqual(result["result"], "RESTORED")
            self.assertTrue((repository / "pdr.test_1.0.0.bndl").is_file())
            self.assertTrue((root / "bundles.pdr-previous" / "broken-current.bndl").is_file())
            self.assertTrue((state / "recovery-audit.jsonl").is_file())

    def test_restore_requires_stopped_acknowledgement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(ValueError, "--runtime-stopped"):
                recovery.restore(root / "state", root / "bundles", runtime_stopped=False)

    def test_authorized_exact_snapshot_preserves_digest_and_sequence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = root / "state"
            backup = state / "last-known-good"
            repository = root / "bundles"
            backup.mkdir(parents=True)
            repository.mkdir()
            write_bundle(backup / "pdr.test_1.0.0.bndl", "pdr.test")
            (repository / "broken-current.bndl").write_text("broken", encoding="utf-8")
            digest = recovery.repository_fingerprint(backup)
            provenance = (
                f"releaseManifestSha256={'d' * 64}\nsbomSha256={'e' * 64}\n"
                f"artifactSetSha256={'f' * 64}\nreleaseVersion=0.1.0\n"
                f"gitCommit={'1' * 40}\nbuilderId=test-builder\nbuildProfile=server\n"
            )
            (state / "repository-rollout-high-water.properties").write_text(
                "schemaVersion=2\nrepositoryId=runtime-main\nrolloutSequence=7\n"
                f"candidateDigest={digest}\npublisherId=vendor\nsigningKeyId=key\n"
                f"trustPolicyId=policy\ntrustPolicySha256={'a' * 64}\n"
                f"attestationSha256={'b' * 64}\n{provenance}",
                encoding="utf-8",
            )
            (state / "last-known-good.properties").write_text(
                "schemaVersion=2\nauthorizationVerified=true\nrepositoryId=runtime-main\n"
                f"rolloutSequence=7\ncandidateDigest={digest}\n{provenance}",
                encoding="utf-8",
            )

            before = recovery.status(state, repository)
            self.assertTrue(before["rolloutProtection"]["safe"])
            result = recovery.restore(state, repository, runtime_stopped=True)
            self.assertEqual(result["rolloutProtection"]["rolloutSequence"], 7)
            self.assertEqual(result["rolloutProtection"]["provenance"]["buildProfile"],
                             "server")
            self.assertEqual(recovery.repository_fingerprint(repository), digest)
            self.assertTrue((repository / "pdr.test_1.0.0.bndl").is_file())

    def test_authorized_stale_lkg_is_rejected_before_repository_change(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = root / "state"
            backup = state / "last-known-good"
            repository = root / "bundles"
            backup.mkdir(parents=True)
            repository.mkdir()
            write_bundle(backup / "pdr.old_1.0.0.bndl", "pdr.old")
            marker = repository / "keep.txt"
            marker.write_text("keep", encoding="utf-8")
            digest = recovery.repository_fingerprint(backup)
            (state / "repository-rollout-high-water.properties").write_text(
                "schemaVersion=1\nrepositoryId=runtime-main\nrolloutSequence=8\n"
                f"candidateDigest={'c' * 64}\n",
                encoding="utf-8",
            )
            (state / "last-known-good.properties").write_text(
                "schemaVersion=1\nauthorizationVerified=true\nrepositoryId=runtime-main\n"
                f"rolloutSequence=7\ncandidateDigest={digest}\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "authorized Bundle recovery rejected"):
                recovery.restore(state, repository, runtime_stopped=True)
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep")

    def test_invalid_backup_is_rejected_before_repository_change(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            backup = root / "state" / "last-known-good"
            repository = root / "bundles"
            backup.mkdir(parents=True)
            repository.mkdir()
            (backup / "0000_broken.bndl").write_text("not zip", encoding="utf-8")
            marker = repository / "keep.txt"
            marker.write_text("keep", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "invalid Bundle archive"):
                recovery.restore(root / "state", repository, runtime_stopped=True)
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep")


if __name__ == "__main__":
    unittest.main()
