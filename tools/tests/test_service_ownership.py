import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class ServiceOwnershipPolicyTests(unittest.TestCase):
    def test_osp_bundle_activators_do_not_give_services_shared_ptr_ownership(self):
        violations = []
        roots = (ROOT / "services", ROOT / "platform/OSP", ROOT / "application")
        pattern = re.compile(r"Poco::SharedPtr\s*<\s*[^>]*Service[^>]*>")
        for source_root in roots:
            if not source_root.exists():
                continue
            for path in source_root.rglob("*BundleActivator.cpp"):
                for line_number, line in enumerate(
                        path.read_text(encoding="utf-8").splitlines(), 1):
                    if pattern.search(line):
                        violations.append(
                            f"{path.relative_to(ROOT).as_posix()}:{line_number}: {line.strip()}"
                        )
        self.assertEqual(violations, [],
                         "OSP Service derives from RefCountedObject and must use AutoPtr:\n" +
                         "\n".join(violations))

    def test_web_event_stop_signal_is_atomic(self):
        header = (ROOT / "platform/OSP/WebEvent/include/Poco/OSP/WebEvent/"
                  "WebEventServiceImpl.h").read_text(encoding="utf-8")
        source = (ROOT / "platform/OSP/WebEvent/src/WebEventServiceImpl.cpp").read_text(
            encoding="utf-8"
        )
        self.assertIn("std::atomic<bool> _stopped", header)
        self.assertIn("_stopped.store(true, std::memory_order_release)", source)
        self.assertGreaterEqual(source.count("_stopped.load(std::memory_order_acquire)"), 2)

    def test_web_dispatcher_never_formats_bearer_token_into_logs(self):
        source = (ROOT / "platform/OSP/Web/src/WebServerDispatcher.cpp").read_text(
            encoding="utf-8"
        )
        self.assertNotRegex(
            source,
            r'logger\(\)\.[a-z]+\([^\n;]*(?:Bearer[^\n;]*%s|%s[^\n;]*token)[^\n;]*,\s*token\)',
        )
        self.assertIn('warning("Bearer token validation failed."s)', source)


if __name__ == "__main__":
    unittest.main()
