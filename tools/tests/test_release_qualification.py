import importlib.util
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


TOOL = Path(__file__).resolve().parents[1] / "release_qualification.py"
SPEC = importlib.util.spec_from_file_location("release_qualification_under_test", TOOL)
assert SPEC and SPEC.loader
QUALIFICATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(QUALIFICATION)


class ReleaseQualificationTests(unittest.TestCase):
    @staticmethod
    def ctest_log(path: Path, second_status: str = "Passed") -> None:
        path.write_text("\n".join([
            "Start testing: Aug 02 02:00 UTC",
            "1/2 Test: contract-files", "Test Passed.",
            "2/2 Test: runtime-package-smoke", f"Test {second_status}.",
            "End testing: Aug 02 02:01 UTC",
        ]) + "\n", encoding="utf-8")

    def arguments(self, root: Path, *extra: str):
        return QUALIFICATION.parser().parse_args([
            "--source", str(root), "--build", str(root / "build"),
            "--version", "1.2.3", "--config", "Release",
            "--ctest-log", str(root / "LastTest.log"), "--expected-tests", "2",
            "--max-test-age-hours", "1", "--report", str(root / "report.json"), *extra,
        ])

    def test_local_pass_is_not_release_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.ctest_log(root / "LastTest.log")
            evidence = root / "security.json"
            evidence.write_text(json.dumps({"passed": True}), encoding="utf-8")
            args = self.arguments(root, "--evidence", f"security={evidence}",
                                  "--required-evidence", "security",
                                  "--required-external", "target-board")
            with mock.patch.object(QUALIFICATION, "git_state", return_value={
                    "available": True, "clean": False, "commit": "abc", "changeCount": 1}):
                report, result = QUALIFICATION.qualify(args)
            self.assertEqual(result, 0)
            self.assertEqual(report["verdict"], "LOCAL_VALIDATION_PASSED")
            self.assertTrue(report["passed"])
            self.assertFalse(report["releaseApproved"])
            self.assertIn("GIT_WORKTREE_NOT_CLEAN", report["releaseDenialReasons"])
            self.assertIn("EXTERNAL_ACCEPTANCE_INCOMPLETE", report["releaseDenialReasons"])

    def test_release_approval_requires_complete_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.ctest_log(root / "LastTest.log")
            manifest = root / "SHA256SUMS.json"
            external = root / "target.json"
            artifacts = root / "artifacts"
            artifacts.mkdir()
            binary = artifacts / "runtime.bin"
            binary.write_bytes(b"qualified-release")
            files = [{"path": "runtime.bin", "size": binary.stat().st_size,
                      "sha256": hashlib.sha256(binary.read_bytes()).hexdigest()}]
            artifact_set = hashlib.sha256(json.dumps(
                files, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")).hexdigest()
            sbom = root / "pocoddsruntime.spdx.json"
            sbom_document = {
                "spdxVersion": "SPDX-2.3",
                "documentNamespace": "https://pocodds.local/spdx/qualification",
                "packages": [{"name": "PocoDDSRuntime", "versionInfo": "1.2.3"}],
            }
            sbom.write_text(json.dumps(sbom_document), encoding="utf-8")
            manifest.write_text(json.dumps({
                "schemaVersion": 1, "product": "PocoDDSRuntime", "version": "1.2.3",
                "gitCommit": "abc", "dirty": False, "cleanRequired": True,
                "artifactRoot": str(artifacts), "files": files,
                "sbom": {"path": sbom.name,
                         "sha256": hashlib.sha256(sbom.read_bytes()).hexdigest(),
                         "spdxVersion": "SPDX-2.3",
                         "documentNamespace": sbom_document["documentNamespace"]},
                "provenance": {"builderId": "qualification-test",
                               "buildProfile": "server",
                               "artifactSetSha256": artifact_set,
                               "source": {"gitCommit": "abc", "dirty": False}},
            }), encoding="utf-8")
            external.write_text(json.dumps({"verdict": "APPROVED"}), encoding="utf-8")
            args = self.arguments(root, "--artifact-manifest", str(manifest),
                                  "--artifacts", str(artifacts),
                                  "--evidence", f"package={external}",
                                  "--required-evidence", "package",
                                  "--required-external", "target-board",
                                  "--external-evidence", f"target-board={external}",
                                  "--external-signature", f"target-board={external}",
                                  "--external-trust-policy", str(external),
                                  "--expected-external-trust-policy-id", "policy",
                                  "--expected-external-trust-policy-sha256", "0" * 64,
                                  "--signature-check-executable", str(external),
                                  "--require-release-approval")
            with mock.patch.object(QUALIFICATION, "git_state", return_value={
                    "available": True, "clean": True, "commit": "abc", "changeCount": 0}), \
                    mock.patch.object(QUALIFICATION, "verify_external_acceptance",
                                      return_value={"verified": True}):
                report, result = QUALIFICATION.qualify(args)
            self.assertEqual(result, 0)
            self.assertEqual(report["verdict"], "RELEASE_CANDIDATE_APPROVED")
            self.assertTrue(report["releaseApproved"])

    def test_failed_or_stale_ctest_evidence_is_denied(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "LastTest.log"
            self.ctest_log(log, "Failed")
            os.utime(log, (0, 0))
            args = self.arguments(root)
            with mock.patch.object(QUALIFICATION, "git_state", return_value={
                    "available": True, "clean": True, "commit": "abc", "changeCount": 0}):
                report, result = QUALIFICATION.qualify(args)
            self.assertEqual(result, 1)
            self.assertEqual(report["verdict"], "DENIED")
            self.assertIn("CTEST_NOT_ALL_PASSED", report["localFailureReasons"])
            self.assertIn("CTEST_EVIDENCE_STALE", report["localFailureReasons"])


if __name__ == "__main__":
    unittest.main()
