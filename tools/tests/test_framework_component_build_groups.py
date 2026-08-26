import copy
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
SPEC = importlib.util.spec_from_file_location(
    "framework_component_build_groups",
    ROOT / "tools/framework_component_build_groups.py",
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def target(root: Path, name: str, directory: str, target_type: str) -> dict:
    return {
        "name": name,
        "type": target_type,
        "sourceDirectory": str(root / directory),
        "sources": [] if target_type == "UTILITY" else ["src/Member.cpp"],
        "dependencies": [],
        "unresolvedLinkItems": [],
        "includeDirectories": [],
        "unresolvedIncludeItems": [],
    }


class FrameworkComponentBuildGroupTests(unittest.TestCase):
    def fixture(self, root: Path):
        for path in ("services/A/src", "services/B/src", "core/src"):
            (root / path).mkdir(parents=True)
        catalog = {
            "schemaVersion": 1,
            "product": "PocoDDSRuntimeFrameworkComponents",
            "globalPaths": ["CMakeLists.txt", "tools/"],
            "components": [
                {
                    "id": "core", "owner": "team/core", "paths": ["core/"],
                    "requires": [], "buildTargets": ["Core"], "testLabels": ["core"],
                },
                {
                    "id": "governance-services", "owner": "team/governance",
                    "paths": ["services/A/", "services/B/"], "requires": ["core"],
                    "buildTargets": ["GovernanceServices"], "testLabels": ["service"],
                },
            ],
        }
        groups = {
            "schemaVersion": 1,
            "operation": "framework-component-build-groups",
            "profile": "server",
            "groups": [{
                "component": "governance-services",
                "target": "GovernanceServices",
                "members": ["ServiceA", "ServiceB"],
            }],
        }
        links = {
            "schemaVersion": 1,
            "operation": "cmake-target-link-manifest",
            "profile": "server",
            "sourceRoot": str(root),
            "buildRoot": str(root / "build"),
            "targets": [
                target(root, "Core", "core", "STATIC_LIBRARY"),
                target(root, "GovernanceServices", "services", "UTILITY"),
                target(root, "ServiceA", "services/A", "MODULE_LIBRARY"),
                target(root, "ServiceB", "services/B", "MODULE_LIBRARY"),
            ],
        }
        return catalog, groups, links

    def test_exact_group_membership_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog, groups, links = self.fixture(root)
            report = MODULE.analyze(root, catalog, groups, links)
            self.assertTrue(report["passed"])
            self.assertEqual(report["componentCount"], 1)
            self.assertEqual(report["memberTargetCount"], 2)

    def test_missing_and_cross_component_members_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog, groups, links = self.fixture(root)
            broken = copy.deepcopy(groups)
            broken["groups"][0]["members"] = ["Core", "ServiceA"]
            report = MODULE.analyze(root, catalog, broken, links)
            self.assertFalse(report["passed"])
            self.assertTrue(any("misses production target ServiceB" in item
                                for item in report["violations"]))
            self.assertTrue(any("foreign or non-production target Core" in item
                                for item in report["violations"]))

    def test_catalog_must_expose_only_the_group_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog, groups, links = self.fixture(root)
            catalog["components"][1]["buildTargets"] = ["ServiceA"]
            report = MODULE.analyze(root, catalog, groups, links)
            self.assertFalse(report["passed"])
            self.assertTrue(any("must expose only group target" in item
                                for item in report["violations"]))


if __name__ == "__main__":
    unittest.main()
