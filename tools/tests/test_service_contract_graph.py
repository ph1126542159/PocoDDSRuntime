import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


TOOLS = Path(__file__).resolve().parents[1]
TOOL = TOOLS / "service_contract_graph.py"


class ServiceContractGraphTests(unittest.TestCase):
    def run_tool(self, root: Path, command: str, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable, str(TOOL), command,
                "--root", str(root), "--scan-root", "services", *arguments,
            ],
            check=False, capture_output=True, text=True,
        )

    def write_bundle(self, root: Path, name: str, owner: str,
                     provides: list[dict], requires: list[dict],
                     bundle_version: str = "1.0.0", run_level: int = 100) -> Path:
        component = root / "services" / name
        bundle = component / "bundle"
        bundle.mkdir(parents=True)
        contract_path = bundle / "service-contracts.json"
        contract_path.write_text(json.dumps({
            "schemaVersion": 1,
            "provides": provides,
            "requires": requires,
        }, indent=2), encoding="utf-8")
        (component / f"{name}.bndlspec").write_text(
            f"""<?xml version="1.0"?>
<bundlespec>
  <manifest>
    <name>{name}</name>
    <symbolicName>{owner}</symbolicName>
    <version>{bundle_version}</version>
    <lazyStart>false</lazyStart>
    <runLevel>{run_level}</runLevel>
  </manifest>
  <files>bundle/*</files>
</bundlespec>
""",
            encoding="utf-8",
        )
        return contract_path

    def snapshot(self, root: Path) -> Path:
        baseline = root / "contracts/service-contract-baseline.json"
        baseline.parent.mkdir(parents=True)
        result = self.run_tool(root, "snapshot", "--output", str(baseline))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return baseline

    @staticmethod
    def provider(contract: str, version: str, service: str) -> dict:
        return {"contract": contract, "version": version, "serviceName": service}

    @staticmethod
    def requirement(contract: str, version_range: str, required: bool = True) -> dict:
        return {
            "contract": contract,
            "versionRange": version_range,
            "required": required,
            "minimumProviders": 1,
        }

    def test_graph_binds_all_inputs_and_recomputes_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_bundle(
                root, "Provider", "example.provider",
                [self.provider("example.orders", "1.0.0", "example.service.orders")],
                [],  run_level=10,
            )
            self.write_bundle(
                root, "Consumer", "example.consumer", [],
                [self.requirement("example.orders", "[1.0.0,2.0.0)")],
                run_level=20,
            )
            baseline = self.snapshot(root)
            report = root / "build/service-contract-graph.json"
            checked = self.run_tool(
                root, "check", "--baseline", str(baseline), "--report", str(report)
            )
            self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
            document = json.loads(report.read_text(encoding="utf-8"))
            self.assertTrue(document["passed"])
            self.assertEqual(document["bundleCount"], 2)
            self.assertEqual(document["requiredSatisfiedCount"], 1)
            self.assertEqual(len(document["inputs"]), 4)
            verified = self.run_tool(
                root, "verify", "--baseline", str(baseline), "--report", str(report)
            )
            self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)

            document["warnings"].append("forged")
            report.write_text(json.dumps(document), encoding="utf-8")
            tampered = self.run_tool(
                root, "verify", "--baseline", str(baseline), "--report", str(report)
            )
            self.assertEqual(tampered.returncode, 2)
            self.assertIn("differs from current bound inputs", tampered.stderr)

    def test_provider_rename_requires_major_bump_and_consumer_migration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            provider_path = self.write_bundle(
                root, "Provider", "example.provider",
                [self.provider("example.orders", "1.0.0", "example.service.orders")],
                [], run_level=10,
            )
            consumer_path = self.write_bundle(
                root, "Consumer", "example.consumer", [],
                [self.requirement("example.orders", "[1.0.0,2.0.0)")],
                run_level=20,
            )
            baseline = self.snapshot(root)
            provider = json.loads(provider_path.read_text(encoding="utf-8"))
            provider["provides"][0]["serviceName"] = "example.service.ordersV2"
            provider_path.write_text(json.dumps(provider), encoding="utf-8")
            report = root / "build/renamed.json"
            rejected = self.run_tool(
                root, "check", "--baseline", str(baseline), "--report", str(report)
            )
            self.assertEqual(rejected.returncode, 1)
            self.assertIn("without a major version bump", rejected.stderr)

            provider["provides"][0]["version"] = "2.0.0"
            provider_path.write_text(json.dumps(provider), encoding="utf-8")
            spec = root / "services/Provider/Provider.bndlspec"
            spec.write_text(
                spec.read_text(encoding="utf-8").replace(
                    "<version>1.0.0</version>", "<version>2.0.0</version>"
                ),
                encoding="utf-8",
            )
            still_rejected = self.run_tool(
                root, "check", "--baseline", str(baseline), "--report", str(report)
            )
            self.assertEqual(still_rejected.returncode, 1)
            self.assertIn("versionMismatch", still_rejected.stderr)

            consumer = json.loads(consumer_path.read_text(encoding="utf-8"))
            consumer["requires"][0]["versionRange"] = "[2.0.0,3.0.0)"
            consumer_path.write_text(json.dumps(consumer), encoding="utf-8")
            migrated = self.run_tool(
                root, "check", "--baseline", str(baseline), "--report", str(report)
            )
            self.assertEqual(migrated.returncode, 0, migrated.stdout + migrated.stderr)
            migrated_report = json.loads(report.read_text(encoding="utf-8"))
            self.assertIn("Provider major-version replacement", migrated_report["warnings"][0])

    def test_required_cycles_and_global_service_name_collisions_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            alpha_path = self.write_bundle(
                root, "Alpha", "example.alpha",
                [self.provider("example.alpha-api", "1.0.0", "example.service.alpha")],
                [], run_level=10,
            )
            beta_path = self.write_bundle(
                root, "Beta", "example.beta",
                [self.provider("example.beta-api", "1.0.0", "example.service.beta")],
                [], run_level=20,
            )
            baseline = self.snapshot(root)
            alpha = json.loads(alpha_path.read_text(encoding="utf-8"))
            beta = json.loads(beta_path.read_text(encoding="utf-8"))
            alpha["requires"] = [
                self.requirement("example.beta-api", "[1.0.0,2.0.0)")
            ]
            beta["requires"] = [
                self.requirement("example.alpha-api", "[1.0.0,2.0.0)")
            ]
            alpha_path.write_text(json.dumps(alpha), encoding="utf-8")
            beta_path.write_text(json.dumps(beta), encoding="utf-8")
            report = root / "build/cycle.json"
            cycle = self.run_tool(
                root, "check", "--baseline", str(baseline), "--report", str(report)
            )
            self.assertEqual(cycle.returncode, 1)
            self.assertIn("required service dependency cycle", cycle.stderr)

            beta["requires"] = []
            beta["provides"][0]["serviceName"] = "example.service.alpha"
            beta_path.write_text(json.dumps(beta), encoding="utf-8")
            collision = self.run_tool(
                root, "check", "--baseline", str(baseline), "--report", str(report)
            )
            self.assertEqual(collision.returncode, 1)
            self.assertIn("serviceName is declared by multiple owners", collision.stderr)


if __name__ == "__main__":
    unittest.main()
