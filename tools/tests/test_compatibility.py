import copy
import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.dont_write_bytecode = True
SPEC = importlib.util.spec_from_file_location(
    "check_compatibility", ROOT / "tools/check_compatibility.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class CompatibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.surface = MODULE.current_surface(ROOT)

    def test_current_surface_is_compatible_with_itself(self):
        self.assertEqual(MODULE.compare(self.surface, self.surface), [])

    def test_removed_operation_is_breaking_without_major_bump(self):
        current = copy.deepcopy(self.surface)
        current["openapi"]["operations"].pop()
        errors = MODULE.compare(self.surface, current)
        self.assertTrue(any("removed OpenAPI operation" in error for error in errors))

    def test_new_required_configuration_is_breaking(self):
        current = copy.deepcopy(self.surface)
        current["configuration"]["required"].append("new.required.key")
        errors = MODULE.compare(self.surface, current)
        self.assertTrue(any("new required configuration" in error for error in errors))

    def test_wider_numeric_range_is_compatible(self):
        old = {"type": "integer", "minimum": 0, "maximum": 63}
        new = {"type": "integer", "minimum": 0, "maximum": 511}
        self.assertFalse(MODULE.constraints_breaking(old, new))

    def test_narrower_numeric_range_is_breaking(self):
        old = {"type": "integer", "minimum": 0, "maximum": 511}
        new = {"type": "integer", "minimum": 1, "maximum": 63}
        self.assertTrue(MODULE.constraints_breaking(old, new))

    def test_adding_enum_value_is_compatible_but_removing_is_breaking(self):
        old = {"type": "string", "enum": ["a", "b"]}
        self.assertFalse(MODULE.constraints_breaking(old, {"type": "string", "enum": ["a", "b", "c"]}))
        self.assertTrue(MODULE.constraints_breaking(old, {"type": "string", "enum": ["a"]}))

    def test_major_bump_allows_intentional_break(self):
        current = copy.deepcopy(self.surface)
        current["runtimeVersion"] = "1.0.0"
        current["openapi"]["operations"].clear()
        self.assertEqual(MODULE.compare(self.surface, current), [])


if __name__ == "__main__":
    unittest.main()
