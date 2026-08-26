import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools/component_contract_test.py"


class ComponentContractTestTests(unittest.TestCase):
    def write_json(self, path: Path, document: dict) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(document), encoding="utf-8")
        return path

    def component(self, root: Path) -> Path:
        return self.write_json(root / "pdr-component.json", {
            "schemaVersion": 1,
            "id": "order-workflow",
            "name": "OrderWorkflow",
            "kind": "workflow",
            "plane": "management",
            "target": "order_workflow",
            "owner": "team/orders",
            "isolation": "in-process",
            "requires": [],
        })

    def contract(self, root: Path, *, required: bool = True,
                 minimum: int = 1, version_range: str = "[1.0.0,2.0.0)") -> Path:
        return self.write_json(root / "bundle/service-contracts.json", {
            "schemaVersion": 1,
            "provides": [{
                "contract": "example.orders",
                "version": "1.0.0",
                "serviceName": "example.service.orders",
            }],
            "requires": [{
                "contract": "pdr.scheduling",
                "versionRange": version_range,
                "required": required,
                "minimumProviders": minimum,
            }],
        })

    def provider(self, root: Path, version: str = "1.4.0",
                 service: str = "pdr.service.scheduler") -> Path:
        return self.write_json(root / f"{service}.json", {
            "schemaVersion": 1,
            "provides": [{
                "contract": "pdr.scheduling",
                "version": version,
                "serviceName": service,
            }],
            "requires": [],
        })

    def run_tool(self, component: Path, contract: Path, *providers: Path,
                 report: Path | None = None):
        command = [sys.executable, str(TOOL), str(component.parent),
                   "--service-contract", str(contract)]
        for provider in providers:
            command.extend(["--provider-contract", str(provider)])
        if report:
            command.extend(["--report", str(report)])
        return subprocess.run(command, check=False, capture_output=True, text=True)

    def test_required_contract_matches_explicit_provider_and_binds_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = root / "report.json"
            result = self.run_tool(
                self.component(root), self.contract(root), self.provider(root), report=report
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            evidence = json.loads(report.read_text(encoding="utf-8"))
            self.assertTrue(evidence["passed"])
            self.assertEqual(evidence["requiredSatisfiedCount"], 1)
            self.assertEqual(len(evidence["inputSetSha256"]), 64)
            self.assertEqual([item["role"] for item in evidence["inputs"]], [
                "component", "consumer-service-contract", "provider-service-contract"
            ])

    def test_version_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = self.run_tool(
                self.component(root), self.contract(root), self.provider(root, "2.0.0")
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("versionMismatch", result.stderr)

    def test_minimum_provider_count_is_enforced(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = self.run_tool(
                self.component(root), self.contract(root, minimum=2), self.provider(root)
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("insufficientProviders", result.stderr)

    def test_optional_gap_is_visible_but_does_not_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = root / "report.json"
            result = self.run_tool(
                self.component(root), self.contract(root, required=False), report=report
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            evidence = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(evidence["optionalUnsatisfiedCount"], 1)
            self.assertEqual(evidence["requirements"][0]["status"], "missing")

    def test_unknown_contract_field_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            contract = self.contract(root)
            document = json.loads(contract.read_text(encoding="utf-8"))
            document["owner"] = "forged-owner"
            self.write_json(contract, document)
            result = self.run_tool(self.component(root), contract)
            self.assertEqual(result.returncode, 2)
            self.assertIn("unknown=owner", result.stderr)

    def test_self_provider_can_satisfy_same_component_requirement(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            component = self.component(root)
            contract = self.contract(root)
            document = json.loads(contract.read_text(encoding="utf-8"))
            document["provides"].append({
                "contract": "pdr.scheduling",
                "version": "1.1.0",
                "serviceName": "example.service.local-scheduler",
            })
            self.write_json(contract, document)
            result = self.run_tool(component, contract)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_repeated_provider_input_cannot_fake_minimum_count(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            provider = self.provider(root)
            result = self.run_tool(
                self.component(root), self.contract(root, minimum=2), provider, provider
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("provider contract input is repeated", result.stderr)

    def test_input_set_digest_is_independent_of_checkout_path(self):
        with tempfile.TemporaryDirectory() as first_directory, tempfile.TemporaryDirectory() as second_directory:
            digests = []
            for directory in (first_directory, second_directory):
                root = Path(directory)
                report = root / "report.json"
                result = self.run_tool(
                    self.component(root), self.contract(root), self.provider(root), report=report
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                digests.append(json.loads(report.read_text(encoding="utf-8"))["inputSetSha256"])
            self.assertEqual(digests[0], digests[1])

    def test_report_verification_recomputes_valid_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = root / "report.json"
            generated = self.run_tool(
                self.component(root), self.contract(root), self.provider(root), report=report
            )
            self.assertEqual(generated.returncode, 0, generated.stdout + generated.stderr)
            verified = subprocess.run(
                [sys.executable, str(TOOL), "--verify-report", str(report)],
                check=False, capture_output=True, text=True,
            )
            self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)
            self.assertIn("COMPONENT_CONTRACT_EVIDENCE_PASS", verified.stdout)

    def test_report_verification_rejects_input_and_report_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            component = self.component(root)
            report = root / "report.json"
            generated = self.run_tool(
                component, self.contract(root), self.provider(root), report=report
            )
            self.assertEqual(generated.returncode, 0, generated.stdout + generated.stderr)
            original_component = component.read_bytes()
            component.write_bytes(original_component + b"\n")
            input_tampered = subprocess.run(
                [sys.executable, str(TOOL), "--verify-report", str(report)],
                check=False, capture_output=True, text=True,
            )
            self.assertEqual(input_tampered.returncode, 2)
            self.assertIn("digest mismatch", input_tampered.stderr)
            component.write_bytes(original_component)

            document = json.loads(report.read_text(encoding="utf-8"))
            document["optionalUnsatisfiedCount"] = 99
            report.write_text(json.dumps(document), encoding="utf-8")
            report_tampered = subprocess.run(
                [sys.executable, str(TOOL), "--verify-report", str(report)],
                check=False, capture_output=True, text=True,
            )
            self.assertEqual(report_tampered.returncode, 2)
            self.assertIn("does not match recomputed evidence", report_tampered.stderr)


if __name__ == "__main__":
    unittest.main()
