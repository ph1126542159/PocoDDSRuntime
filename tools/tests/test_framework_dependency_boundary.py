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
    "framework_dependency_boundary", ROOT / "tools/framework_dependency_boundary.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def catalog(requires: list[str]) -> dict:
    return {
        "schemaVersion": 1,
        "product": "PocoDDSRuntimeFrameworkComponents",
        "globalPaths": ["CMakeLists.txt"],
        "components": [
            {"id": "core", "owner": "team/core", "paths": ["core/"],
             "requires": [], "buildTargets": ["Core"], "testLabels": ["core"]},
            {"id": "service", "owner": "team/service", "paths": ["service/"],
             "requires": requires, "buildTargets": ["Service"],
             "testLabels": ["service"]},
        ],
    }


class FrameworkDependencyBoundaryTests(unittest.TestCase):
    def fixture(self, root: Path) -> None:
        (root / "core/include/Core").mkdir(parents=True)
        (root / "core/src").mkdir(parents=True)
        (root / "service/include/Service").mkdir(parents=True)
        (root / "service/src").mkdir(parents=True)
        (root / "service/tests").mkdir(parents=True)
        (root / "core/include/Core/API.h").write_text("#pragma once\n", encoding="utf-8")
        (root / "service/include/Service/API.h").write_text(
            '#pragma once\n#include "Core/API.h"\n', encoding="utf-8"
        )
        (root / "service/src/Service.cpp").write_text(
            '#include "Service/API.h"\n#include <Core/API.h>\n', encoding="utf-8"
        )
        (root / "service/tests/Test.cpp").write_text(
            '#include "Unknown/TestOnly.h"\n', encoding="utf-8"
        )

    def test_declared_direct_dependency_passes_and_tests_are_excluded(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            report = MODULE.analyze(root, catalog(["core"]))
            self.assertTrue(report["passed"])
            self.assertEqual(report["scannedProductionFiles"], 3)
            self.assertEqual(len(report["observedEdges"]), 1)
            self.assertEqual(report["observedEdges"][0]["provider"], "core")

    def test_undeclared_dependency_fails_with_file_and_line_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            report = MODULE.analyze(root, catalog([]))
            self.assertFalse(report["passed"])
            violation = report["violations"][0]
            self.assertEqual((violation["consumer"], violation["provider"]),
                             ("service", "core"))
            self.assertIn("service/include/Service/API.h",
                          {item["source"] for item in violation["evidence"]})

    def test_ambiguous_public_header_ownership_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            duplicate = root / "service/include/Core/API.h"
            duplicate.parent.mkdir(parents=True)
            duplicate.write_text("#pragma once\n", encoding="utf-8")
            report = MODULE.analyze(root, catalog(["core"]))
            self.assertFalse(report["passed"])
            self.assertEqual(report["ambiguousPublicHeaders"][0]["include"],
                             "Core/API.h")

    def test_declared_dependency_cannot_include_provider_private_header(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            (root / "core/src/Internal.h").write_text(
                "#pragma once\n", encoding="utf-8"
            )
            (root / "service/src/Service.cpp").write_text(
                '#include "../../core/src/Internal.h"\n', encoding="utf-8"
            )
            report = MODULE.analyze(root, catalog(["core"]))
            self.assertFalse(report["passed"])
            self.assertEqual(report["resolvedCrossComponentPrivateIncludes"], 1)
            violation = report["privateHeaderViolations"][0]
            self.assertEqual((violation["consumer"], violation["provider"]),
                             ("service", "core"))
            self.assertEqual(violation["privateHeader"], "core/src/Internal.h")

    def test_relative_path_to_provider_public_header_keeps_declared_edge(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            (root / "service/src/Service.cpp").write_text(
                '#include "../../core/include/Core/API.h"\n', encoding="utf-8"
            )
            report = MODULE.analyze(root, catalog(["core"]))
            self.assertTrue(report["passed"])
            self.assertEqual(report["observedEdges"][0]["provider"], "core")

    def test_cli_writes_failure_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            catalog_path = root / "catalog.json"
            report_path = root / "report.json"
            catalog_path.write_text(json.dumps(catalog([])), encoding="utf-8")
            result = MODULE.validate_command(argparse.Namespace(
                root=root, catalog=catalog_path, report=report_path
            ))
            self.assertEqual(result, 1)
            self.assertFalse(json.loads(report_path.read_text(encoding="utf-8"))["passed"])


if __name__ == "__main__":
    unittest.main()
