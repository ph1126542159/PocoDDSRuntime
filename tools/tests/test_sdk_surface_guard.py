import argparse
import copy
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
SPEC = importlib.util.spec_from_file_location(
    "sdk_surface_guard", ROOT / "tools/sdk_surface_guard.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class SDKSurfaceGuardTests(unittest.TestCase):
    def fixture(self, root: Path) -> Path:
        install = root / "install"
        header = install / "include/PocoDDS/Core/API.h"
        header.parent.mkdir(parents=True)
        header.write_text(
            "// comment\n#pragma once\nnamespace PocoDDS { struct API { int value; }; }\n",
            encoding="utf-8",
        )
        targets = install / "lib/cmake/PocoDDSRuntime/PocoDDSRuntimeTargets.cmake"
        targets.parent.mkdir(parents=True)
        targets.write_text(
            "add_library(PocoDDS::Core STATIC IMPORTED)\n", encoding="utf-8"
        )
        return install

    def test_snapshot_is_comment_and_whitespace_stable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            install = self.fixture(root)
            first = MODULE.snapshot(install, "0.1.0")
            header = install / "include/PocoDDS/Core/API.h"
            header.write_text(
                "/* replacement comment */\n#pragma   once\n"
                "namespace PocoDDS{struct API{int value;};}\n",
                encoding="utf-8",
            )
            second = MODULE.snapshot(install, "0.1.0")
            self.assertEqual(first["surfaceSha256"], second["surfaceSha256"])

    def test_governed_deprecation_attribute_is_surface_stable(self):
        with tempfile.TemporaryDirectory() as directory:
            install = self.fixture(Path(directory))
            baseline = MODULE.snapshot(install, "0.1.0")
            header = install / "include/PocoDDS/Core/API.h"
            header.write_text(
                "#pragma once\nnamespace PocoDDS { "
                "struct [[deprecated(\"PDR-DEP-0001: use CoreAPI\")]] "
                "API { int value; }; }\n",
                encoding="utf-8",
            )
            current = MODULE.snapshot(install, "0.1.1")
            self.assertEqual(
                baseline["publicHeaders"]["include/PocoDDS/Core/API.h"],
                current["publicHeaders"]["include/PocoDDS/Core/API.h"],
            )
            self.assertTrue(MODULE.compare(baseline, current, False)["passed"])

    def test_ungoverned_deprecation_attribute_remains_a_surface_change(self):
        with tempfile.TemporaryDirectory() as directory:
            install = self.fixture(Path(directory))
            baseline = MODULE.snapshot(install, "0.1.0")
            header = install / "include/PocoDDS/Core/API.h"
            header.write_text(
                "#pragma once\nnamespace PocoDDS { "
                "struct [[deprecated(\"use CoreAPI\")]] API { int value; }; }\n",
                encoding="utf-8",
            )
            current = MODULE.snapshot(install, "0.1.1")
            self.assertFalse(MODULE.compare(baseline, current, False)["passed"])

    def test_governed_attribute_requires_a_replacement_message(self):
        with tempfile.TemporaryDirectory() as directory:
            install = self.fixture(Path(directory))
            baseline = MODULE.snapshot(install, "0.1.0")
            header = install / "include/PocoDDS/Core/API.h"
            header.write_text(
                "#pragma once\nnamespace PocoDDS { "
                "struct [[deprecated(\"PDR-DEP-0001\")]] API { int value; }; }\n",
                encoding="utf-8",
            )
            current = MODULE.snapshot(install, "0.1.1")
            self.assertFalse(MODULE.compare(baseline, current, False)["passed"])

    def test_changed_header_is_breaking_without_major_bump(self):
        with tempfile.TemporaryDirectory() as directory:
            install = self.fixture(Path(directory))
            baseline = MODULE.snapshot(install, "0.1.0")
            header = install / "include/PocoDDS/Core/API.h"
            header.write_text("#pragma once\nstruct API { long value; };\n", encoding="utf-8")
            current = MODULE.snapshot(install, "0.1.1")
            report = MODULE.compare(baseline, current, False)
            self.assertFalse(report["passed"])
            self.assertEqual(report["changedHeaders"], ["include/PocoDDS/Core/API.h"])

    def test_additive_header_and_target_are_compatible(self):
        with tempfile.TemporaryDirectory() as directory:
            install = self.fixture(Path(directory))
            baseline = MODULE.snapshot(install, "0.1.0")
            extra = install / "include/PocoDDS/Core/Extra.h"
            extra.write_text("#pragma once\nstruct Extra {};\n", encoding="utf-8")
            targets = install / "lib/cmake/PocoDDSRuntime/PocoDDSRuntimeTargets.cmake"
            targets.write_text(targets.read_text(encoding="utf-8") +
                               "add_library(PocoDDS::Extra INTERFACE IMPORTED)\n",
                               encoding="utf-8")
            report = MODULE.compare(baseline, MODULE.snapshot(install, "0.1.1"), False)
            self.assertTrue(report["passed"])
            self.assertEqual(report["addedCmakeTargets"], ["PocoDDS::Extra"])

    def test_removed_target_requires_major_version(self):
        with tempfile.TemporaryDirectory() as directory:
            install = self.fixture(Path(directory))
            baseline = MODULE.snapshot(install, "0.1.0")
            targets = install / "lib/cmake/PocoDDSRuntime/PocoDDSRuntimeTargets.cmake"
            targets.write_text("add_library(Other::Core STATIC IMPORTED)\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "exports no PocoDDS"):
                MODULE.snapshot(install, "0.1.1")
            current = copy.deepcopy(baseline)
            current["runtimeVersion"] = "1.0.0"
            current["cmakeLibraryTargets"] = ["PocoDDS::Replacement"]
            current["surfaceSha256"] = MODULE.surface_digest(
                current["publicHeaders"], current["cmakeLibraryTargets"]
            )
            report = MODULE.compare(baseline, current, False)
            self.assertTrue(report["passed"])
            self.assertTrue(report["majorVersionBreakApproved"])

    def test_binary_abi_digest_change_is_breaking_and_abi_can_be_required(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            install = self.fixture(root)
            artifact = install / ("bin/PDRCore.dll" if MODULE.os.name == "nt"
                                  else "lib/libPDRCore.so")
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_bytes(b"fixture")
            tool = root / "symbols.exe"
            tool.write_bytes(b"fixture")
            baseline = MODULE.snapshot(
                install, "0.1.0", "test-abi", tool,
                reader=lambda _tool, _artifact: ["symbolA"],
            )
            current = MODULE.snapshot(
                install, "0.1.1", "test-abi", tool,
                reader=lambda _tool, _artifact: ["symbolB"],
            )
            report = MODULE.compare(baseline, current, True)
            self.assertFalse(report["passed"])
            self.assertTrue(report["abiChecked"])
            no_abi = MODULE.snapshot(install, "0.1.1")
            with self.assertRaisesRegex(ValueError, "required"):
                MODULE.compare(baseline, no_abi, True)

    def test_cli_writes_failure_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            install = self.fixture(root)
            baseline = MODULE.snapshot(install, "0.1.0")
            current = copy.deepcopy(baseline)
            current["publicHeaders"]["include/PocoDDS/Core/API.h"]["tokenSha256"] = "0" * 64
            current["surfaceSha256"] = MODULE.surface_digest(
                current["publicHeaders"], current["cmakeLibraryTargets"]
            )
            baseline_path, current_path = root / "base.json", root / "current.json"
            report_path = root / "report.json"
            baseline_path.write_text(json.dumps(baseline), encoding="utf-8")
            current_path.write_text(json.dumps(current), encoding="utf-8")
            result = MODULE.compare_command(argparse.Namespace(
                baseline=baseline_path, current=current_path,
                require_abi=False, report=report_path,
            ))
            self.assertEqual(result, 1)
            self.assertFalse(json.loads(report_path.read_text(encoding="utf-8"))["passed"])

    def test_rejects_inconsistent_surface_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            install = self.fixture(Path(directory))
            current = MODULE.snapshot(install, "0.1.0")
            current["surfaceSha256"] = "0" * 64
            with self.assertRaisesRegex(ValueError, "digest is inconsistent"):
                MODULE.validate_snapshot(current, "current")

    def test_rejects_runtime_version_regression(self):
        with tempfile.TemporaryDirectory() as directory:
            install = self.fixture(Path(directory))
            baseline = MODULE.snapshot(install, "1.2.0")
            current = MODULE.snapshot(install, "1.1.9")
            with self.assertRaisesRegex(ValueError, "older than"):
                MODULE.compare(baseline, current, False)


if __name__ == "__main__":
    unittest.main()
