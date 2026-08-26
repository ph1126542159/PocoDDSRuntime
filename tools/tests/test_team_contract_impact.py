#!/usr/bin/env python3

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


TOOLS = Path(__file__).resolve().parents[1]
PACKAGE_TOOL = TOOLS / "team_contract_package.py"
IMPACT_TOOL = TOOLS / "team_contract_impact.py"


class TeamContractImpactTests(unittest.TestCase):
    @staticmethod
    def run_tool(tool: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(tool), *arguments],
            check=False, capture_output=True, text=True,
        )

    @staticmethod
    def write_documents(root: Path, service_version: str = "1.4.0",
                        service_name: str = "pdr.service.scheduler",
                        participant_prefix: str = "pdr.scheduler") -> dict[str, Path]:
        root.mkdir(parents=True)
        documents = {
            "service-contract": {
                "schemaVersion": 1,
                "provides": [{
                    "contract": "pdr.scheduling", "version": service_version,
                    "serviceName": service_name,
                }],
                "requires": [],
            },
            "participant-declaration": {
                "schemaVersion": 1,
                "participants": [{
                    "id": "scheduler-configuration",
                    "serviceName": "pdr.configuration.participant.scheduler",
                    "ownedPrefixes": [participant_prefix], "after": [],
                }],
            },
            "key-lifecycle": {"schemaVersion": 1, "entries": []},
        }
        result = {}
        for role, document in documents.items():
            path = root / f"{role}.json"
            path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
            result[role] = path
        return result

    def package(self, root: Path, name: str, package_version: str,
                documents: dict[str, Path]) -> Path:
        output = root / f"{name}.pdrcontracts"
        command = [
            "pack", "--package-id", "team.scheduler", "--version", package_version,
            "--owner", "team.scheduling", "--source-date-epoch", "1700000000",
            "--output", str(output),
        ]
        for role, path in documents.items():
            command.extend(["--input", f"{role}={path}"])
        result = self.run_tool(PACKAGE_TOOL, *command)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return output

    def lock(self, root: Path, name: str, package: Path) -> Path:
        output = root / f"{name}.lock.json"
        result = self.run_tool(
            PACKAGE_TOOL, "lock", "--package", str(package), "--output", str(output)
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return output

    @staticmethod
    def catalog(root: Path) -> Path:
        output = root / "consumer-catalog.json"
        output.write_text(json.dumps({
            "schemaVersion": 1,
            "product": "PocoDDSRuntimeTeamContractConsumerCatalog",
            "consumers": [{
                "id": "team.workflow",
                "owner": "team.workflow",
                "dependencies": [{
                    "packageId": "team.scheduler", "roles": ["service-contract"],
                }],
                "requiredTestLabels": ["component", "service"],
            }],
        }, indent=2) + "\n", encoding="utf-8")
        return output

    def impact(self, root: Path, current_lock: Path, current_package: Path,
               candidate_lock: Path, candidate_package: Path,
               name: str = "impact") -> tuple[subprocess.CompletedProcess[str], Path]:
        report = root / f"{name}.json"
        result = self.run_tool(
            IMPACT_TOOL,
            "--current-lock", str(current_lock),
            "--current-package", str(current_package),
            "--candidate-lock", str(candidate_lock),
            "--candidate-package", str(candidate_package),
            "--consumer-catalog", str(self.catalog(root)),
            "--report", str(report),
        )
        return result, report

    def test_compatible_provider_upgrade_routes_only_declared_consumer_tests(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            current = self.package(
                root, "current", "1.0.0",
                self.write_documents(root / "current-docs", "1.4.0"),
            )
            candidate = self.package(
                root, "candidate", "1.1.0",
                self.write_documents(root / "candidate-docs", "1.5.0"),
            )
            result, report_path = self.impact(
                root, self.lock(root, "current", current), current,
                self.lock(root, "candidate", candidate), candidate,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertTrue(report["compatible"])
            self.assertEqual(report["breakingChangeCount"], 0)
            self.assertEqual(report["affectedConsumerCount"], 1)
            self.assertEqual(report["requiredTestLabels"], ["component", "service"])
            codes = {item["code"] for item in report["packages"][0]["changes"]}
            self.assertIn("provider-version-upgraded", codes)
            self.assertIn("package-version-upgraded", codes)

    def test_provider_rename_and_major_change_are_breaking(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            current = self.package(
                root, "current", "1.0.0",
                self.write_documents(root / "current-docs"),
            )
            candidate = self.package(
                root, "candidate", "2.0.0",
                self.write_documents(
                    root / "candidate-docs", "2.0.0", "pdr.service.scheduler.v2"
                ),
            )
            result, report_path = self.impact(
                root, self.lock(root, "current", current), current,
                self.lock(root, "candidate", candidate), candidate,
            )
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertFalse(report["compatible"])
            codes = {item["code"] for item in report["packages"][0]["changes"]}
            self.assertIn("provider-service-renamed", codes)
            self.assertEqual(report["affectedConsumers"][0]["severity"], "breaking")

    def test_same_version_contract_drift_is_breaking_even_when_semantically_additive(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            current = self.package(
                root, "current", "1.0.0",
                self.write_documents(root / "current-docs", "1.4.0"),
            )
            candidate = self.package(
                root, "candidate", "1.0.0",
                self.write_documents(root / "candidate-docs", "1.5.0"),
            )
            result, report_path = self.impact(
                root, self.lock(root, "current", current), current,
                self.lock(root, "candidate", candidate), candidate,
            )
            self.assertEqual(result.returncode, 1)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            codes = {item["code"] for item in report["packages"][0]["changes"]}
            self.assertIn("same-version-contract-drift", codes)

    def test_participant_prefix_narrowing_and_package_tamper_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            current = self.package(
                root, "current", "1.0.0",
                self.write_documents(root / "current-docs", participant_prefix="pdr.scheduler"),
            )
            candidate = self.package(
                root, "candidate", "1.1.0",
                self.write_documents(
                    root / "candidate-docs", participant_prefix="pdr.scheduler.interval"
                ),
            )
            current_lock = self.lock(root, "current", current)
            candidate_lock = self.lock(root, "candidate", candidate)
            result, report_path = self.impact(
                root, current_lock, current, candidate_lock, candidate,
            )
            self.assertEqual(result.returncode, 1)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            codes = {item["code"] for item in report["packages"][0]["changes"]}
            self.assertIn("participant-prefix-narrowed", codes)

            candidate.write_bytes(candidate.read_bytes() + b"tamper")
            invalid, _ = self.impact(
                root, current_lock, current, candidate_lock, candidate, "tampered-impact"
            )
            self.assertEqual(invalid.returncode, 2)


if __name__ == "__main__":
    unittest.main()
