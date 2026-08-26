import argparse
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
SPEC = importlib.util.spec_from_file_location(
    "sdk_header_self_containment", ROOT / "tools/sdk_header_self_containment.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class SDKHeaderSelfContainmentTests(unittest.TestCase):
    def fixture(self, root: Path) -> Path:
        install = root / "install"
        header = install / "include/PocoDDS/Core/API.h"
        header.parent.mkdir(parents=True)
        header.write_text("#pragma once\nstruct API {};\n", encoding="utf-8")
        targets = install / "lib/cmake/PocoDDSRuntime/PocoDDSRuntimeTargets.cmake"
        targets.parent.mkdir(parents=True)
        targets.write_text(
            "add_library(PocoDDS::SDK INTERFACE IMPORTED)\n"
            "add_library(PocoDDS::Core STATIC IMPORTED)\n",
            encoding="utf-8",
        )
        return install

    def test_generate_creates_one_translation_unit_per_installed_header(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "project"
            plan = MODULE.generate(self.fixture(root), output)
            self.assertEqual(len(plan["publicHeaders"]), 1)
            sources = list((output / "sources").glob("*.cpp"))
            self.assertEqual(len(sources), 1)
            self.assertEqual(
                sources[0].read_text(encoding="utf-8").splitlines()[0],
                "#include <PocoDDS/Core/API.h>",
            )
            cmake = (output / "CMakeLists.txt").read_text(encoding="utf-8")
            self.assertIn("PocoDDSRuntime_KNOWN_COMPONENTS", cmake)
            self.assertIn("PocoDDS::SDK", cmake)
            self.assertIn("PocoDDS::Core", cmake)

    def test_generate_requires_sdk_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            install = self.fixture(root)
            targets = install / "lib/cmake/PocoDDSRuntime/PocoDDSRuntimeTargets.cmake"
            targets.write_text(
                "add_library(PocoDDS::Core STATIC IMPORTED)\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "PocoDDS::SDK"):
                MODULE.generate(install, root / "project")

    def test_complete_binds_evidence_to_validated_plan(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = MODULE.generate(self.fixture(root), root / "project")
            plan_path, evidence_path = root / "plan.json", root / "evidence.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            result = MODULE.complete_command(argparse.Namespace(
                plan=plan_path, config="Release", evidence=evidence_path
            ))
            self.assertEqual(result, 0)
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            self.assertTrue(evidence["passed"])
            self.assertEqual(evidence["compiledHeaderCount"], 1)
            self.assertEqual(evidence["planSha256"], MODULE.document_digest(plan))

    def test_plan_digest_tampering_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = MODULE.generate(self.fixture(root), root / "project")
            plan["surfaceSha256"] = "0" * 64
            with self.assertRaisesRegex(ValueError, "digest is inconsistent"):
                MODULE.validate_plan(plan)


if __name__ == "__main__":
    unittest.main()
