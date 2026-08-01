import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


TOOL = Path(__file__).resolve().parents[1] / "pdr.py"


class PdrToolTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
