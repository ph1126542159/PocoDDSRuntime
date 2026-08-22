import importlib.util
import tempfile
import unittest
from pathlib import Path


TOOL = Path(__file__).resolve().parents[1] / "check_architecture.py"
SPEC = importlib.util.spec_from_file_location("architecture_policy", TOOL)
assert SPEC and SPEC.loader
POLICY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(POLICY)


class ArchitecturePolicyTests(unittest.TestCase):
    @staticmethod
    def make_layout(root: Path) -> None:
        for relative in POLICY.SCANNED_DIRECTORIES:
            directory = root / relative
            directory.mkdir(parents=True)
            (directory / "Safe.cpp").write_text(
                '#include "PocoDDS/Robotics/Types.h"\n', encoding="utf-8"
            )
        (root / "robotics/CMakeLists.txt").write_text(
            "add_library(PDRRoboticsRuntime src/Safe.cpp)\n", encoding="utf-8"
        )

    def test_accepts_transport_neutral_core(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_layout(root)
            self.assertEqual(POLICY.scan(root), [])

    def test_rejects_ros2_poco_fastdds_and_qt_includes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_layout(root)
            source = root / "robotics/src/Unsafe.cpp"
            source.write_text(
                "#include <rclcpp/rclcpp.hpp>\n#include <Poco/Logger.h>\n"
                "#include <fastdds/dds/domain/DomainParticipant.hpp>\n#include <QtCore/QObject>\n",
                encoding="utf-8",
            )
            findings = POLICY.scan(root)
            self.assertEqual(len(findings), 4)
            self.assertTrue(all(item["file"] == "robotics/src/Unsafe.cpp" for item in findings))


if __name__ == "__main__":
    unittest.main()
