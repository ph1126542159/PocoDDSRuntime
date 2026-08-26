import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
SPEC = importlib.util.spec_from_file_location(
    "repository_ownership", ROOT / "tools/repository_ownership.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class RepositoryOwnershipTests(unittest.TestCase):
    def catalog(self):
        return {
            "$schema": "schema.json",
            "schemaVersion": 1,
            "product": "PocoDDSRuntimeFrameworkComponents",
            "globalPaths": [".github/", "CMakeLists.txt", "cmake/"],
            "components": [
                {
                    "id": "runtime-core",
                    "owner": "team/runtime-core",
                    "paths": ["runtime-core/"],
                    "requires": [],
                    "buildTargets": ["PDRRuntimeCore"],
                    "testLabels": ["core"],
                },
                {
                    "id": "plugin-sdk",
                    "owner": "team/sdk",
                    "paths": ["cmake/PocoDDSPlugins.cmake"],
                    "requires": ["runtime-core"],
                    "buildTargets": ["PDRPlugins"],
                    "testLabels": ["sdk"],
                },
            ],
        }

    def registry(self):
        return {
            "$schema": "repository-owners.schema.json",
            "schemaVersion": 1,
            "product": "PocoDDSRuntimeRepositoryOwners",
            "defaultReviewers": ["@repo-owner"],
            "logicalOwners": {
                "team/runtime-core": ["@acme/runtime-core"],
                "team/sdk": ["@sdk-owner", "@acme/sdk"],
            },
        }

    def test_render_is_deterministic_and_specific_rule_follows_global_rule(self):
        text = MODULE.render(self.catalog(), self.registry())
        self.assertIn("* @repo-owner\n", text)
        self.assertIn("/CMakeLists.txt @repo-owner\n", text)
        self.assertIn("/runtime-core/ @acme/runtime-core\n", text)
        self.assertLess(
            text.index("/cmake/ @repo-owner"),
            text.index("/cmake/PocoDDSPlugins.cmake @acme/sdk @sdk-owner"),
        )

    def test_registry_requires_every_and_only_catalog_owner(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "owners.json"
            registry = self.registry()
            del registry["logicalOwners"]["team/sdk"]
            path.write_text(json.dumps(registry), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "missing=team/sdk"):
                MODULE.load_registry(path, self.catalog())

    def test_registry_rejects_invalid_github_principal(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "owners.json"
            registry = self.registry()
            registry["logicalOwners"]["team/sdk"] = ["team/sdk"]
            path.write_text(json.dumps(registry), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "valid GitHub"):
                MODULE.load_registry(path, self.catalog())

    def test_verify_fails_closed_for_stale_codeowners(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog_path = root / "catalog.json"
            registry_path = root / "owners.json"
            codeowners_path = root / "CODEOWNERS"
            catalog_path.write_text(json.dumps(self.catalog()), encoding="utf-8")
            registry_path.write_text(json.dumps(self.registry()), encoding="utf-8")
            codeowners_path.write_text("* @someone-else\n", encoding="utf-8")
            result = MODULE.verify_command(type("Args", (), {
                "catalog": catalog_path,
                "registry": registry_path,
                "codeowners": codeowners_path,
            })())
            self.assertEqual(result, 1)


if __name__ == "__main__":
    unittest.main()
