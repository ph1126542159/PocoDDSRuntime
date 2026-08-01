import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


TOOL = Path(__file__).resolve().parents[1] / "pdr.py"


class PdrToolTests(unittest.TestCase):
    @staticmethod
    def create_doctor_layout(root: Path, prefix: Path) -> None:
        (root / "application").mkdir(parents=True)
        (root / "CMakeLists.txt").write_text("cmake_minimum_required(VERSION 3.24)\n")
        package = prefix / "lib" / "cmake" / "PocoDDSRuntime"
        package.mkdir(parents=True)
        (package / "PocoDDSRuntimeConfig.cmake").write_text("# test package\n")
        (package / "PocoDDSRuntimeTargets.cmake").write_text(
            "add_library(PocoDDS::SDK INTERFACE IMPORTED)\n"
        )
        (prefix / "cmake").mkdir(parents=True)
        (prefix / "cmake" / "PocoConfig.cmake").write_text("# test Poco\n")

    def test_generates_all_supported_module_kinds(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for kind in ("service", "device", "workflow"):
                name = kind.title() + "Example"
                result = subprocess.run(
                    [sys.executable, str(TOOL), "new", kind, name, "--output", str(root)],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                module = root / name
                self.assertTrue((module / "CMakeLists.txt").is_file())
                self.assertTrue((module / f"src/{name}.cpp").is_file())
                self.assertTrue((module / f"tests/{name}Smoke.cpp").is_file())
                if kind == "device":
                    header = (module / f"include/PocoDDS/Generated/{name}/{name}.h").read_text(
                        encoding="utf-8"
                    )
                    source = (module / f"src/{name}.cpp").read_text(encoding="utf-8")
                    readme = (module / "README.md").read_text(encoding="utf-8")
                    self.assertIn("public PocoDDS::Devices::Device", header)
                    self.assertIn("public PocoDDS::Devices::DiagnosticDevice", header)
                    self.assertIn("DeviceSnapshot", header)
                    self.assertIn('operation != "ping"', source)
                    self.assertIn("successfulOperations", source)
                    self.assertIn(f"pdr.{name.lower()}.count = 1", readme)

    def test_rejects_invalid_name(self):
        result = subprocess.run(
            [sys.executable, str(TOOL), "new", "service", "bad-name"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)

    def test_verify_records_missing_module_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "report.json"
            result = subprocess.run(
                [sys.executable, str(TOOL), "verify", str(Path(directory) / "missing"),
                 "--report", str(report)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 2)
            evidence = json.loads(report.read_text(encoding="utf-8"))
            self.assertFalse(evidence["passed"])
            self.assertIn("CMakeLists.txt not found", evidence["error"])
            self.assertEqual(evidence["stages"], [])

    def test_verify_records_failed_stage(self):
        with tempfile.TemporaryDirectory() as directory:
            module = Path(directory) / "module"
            module.mkdir()
            (module / "CMakeLists.txt").write_text(
                "cmake_minimum_required(VERSION 3.24)\n", encoding="utf-8"
            )
            report = Path(directory) / "report.json"
            result = subprocess.run(
                [sys.executable, str(TOOL), "verify", str(module),
                 "--cmake", sys.executable, "--ctest", sys.executable,
                 "--report", str(report)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 2)
            evidence = json.loads(report.read_text(encoding="utf-8"))
            self.assertFalse(evidence["passed"])
            self.assertEqual(len(evidence["stages"]), 1)
            self.assertEqual(evidence["stages"][0]["name"], "configure")
            self.assertFalse(evidence["stages"][0]["passed"])

    def test_doctor_validates_selected_install_prefix(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "source"
            prefix = Path(directory) / "install"
            self.create_doctor_layout(root, prefix)
            report = Path(directory) / "doctor.json"
            result = subprocess.run(
                [sys.executable, str(TOOL), "doctor", "--root", str(root),
                 "--prefix", str(prefix), "--report", str(report)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            evidence = json.loads(report.read_text(encoding="utf-8"))
            self.assertTrue(evidence["passed"])
            self.assertEqual({item["id"] for item in evidence["checks"]}, {
                "layout", "python", "cmake", "ctest", "sdk-package",
                "sdk-target", "poco-package",
            })

    def test_installed_doctor_auto_detects_its_prefix(self):
        with tempfile.TemporaryDirectory() as directory:
            prefix = Path(directory) / "package"
            self.create_doctor_layout(Path(directory) / "unused-source", prefix)
            bin_dir = prefix / "bin"
            bin_dir.mkdir()
            installed_tool = bin_dir / "pdr.py"
            installed_tool.write_text(TOOL.read_text(encoding="utf-8"), encoding="utf-8")
            report = Path(directory) / "installed-doctor.json"
            result = subprocess.run(
                [sys.executable, str(installed_tool), "doctor", "--report", str(report)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            evidence = json.loads(report.read_text(encoding="utf-8"))
            self.assertTrue(evidence["passed"])
            self.assertEqual(Path(evidence["prefix"]), prefix)
            layout = next(item for item in evidence["checks"] if item["id"] == "layout")
            self.assertIn("installed:", layout["detail"])

    def test_doctor_failure_report_contains_remedies(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "source"
            root.mkdir()
            report = Path(directory) / "doctor.json"
            result = subprocess.run(
                [sys.executable, str(TOOL), "doctor", "--root", str(root),
                 "--prefix", str(Path(directory) / "missing"), "--report", str(report)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 1)
            evidence = json.loads(report.read_text(encoding="utf-8"))
            self.assertFalse(evidence["passed"])
            failed = [item for item in evidence["checks"] if not item["passed"]]
            self.assertGreaterEqual(len(failed), 4)
            self.assertTrue(all(item.get("remedy") for item in failed))

    def test_validate_config_reports_missing_checker(self):
        with tempfile.TemporaryDirectory() as directory:
            configuration = Path(directory) / "runtime.properties"
            configuration.write_text("osp.web.server.port = 9080\n", encoding="utf-8")
            report = Path(directory) / "validation.json"
            result = subprocess.run(
                [sys.executable, str(TOOL), "validate-config", str(configuration),
                 "--prefix", str(Path(directory) / "missing"), "--report", str(report)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 2)
            evidence = json.loads(report.read_text(encoding="utf-8"))
            self.assertFalse(evidence["passed"])
            self.assertIn("configuration checker not found", evidence["error"])


if __name__ == "__main__":
    unittest.main()
