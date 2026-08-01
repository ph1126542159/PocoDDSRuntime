import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("security_gate", ROOT / "tools/security_gate.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class SecurityGateTests(unittest.TestCase):
    def test_loopback_development_is_allowed(self):
        self.assertEqual(
            MODULE.validate({"security.profile": "development", "osp.web.server.host": "127.0.0.1"}),
            [],
        )

    def test_external_unauthenticated_development_is_rejected(self):
        errors = MODULE.validate(
            {"security.profile": "development", "osp.web.server.host": "0.0.0.0"}
        )
        self.assertTrue(any("authentication and TLS" in error for error in errors))

    def test_production_requires_strong_boundary(self):
        errors = MODULE.validate(
            {
                "security.profile": "production",
                "osp.web.server.host": "0.0.0.0",
                "auth.simple.enable": "true",
            }
        )
        self.assertEqual(len(errors), 3)

    def test_inline_secret_is_rejected(self):
        errors = MODULE.validate(
            {
                "security.profile": "development",
                "osp.web.server.host": "127.0.0.1",
                "mqtt.password": "plaintext",
            }
        )
        self.assertTrue(any("inline secret" in error for error in errors))

    def test_production_rejects_serial_loopback(self):
        errors = MODULE.validate({
            "security.profile": "production",
            "osp.web.server.securePort": "9443",
            "osp.web.authServiceName": "oidc",
            "pdr.serial.0.transport": "loopback",
        })
        self.assertEqual(errors, ["production prohibits serial loopback transport"])

    def test_production_rejects_can_loopback(self):
        errors = MODULE.validate({
            "security.profile": "production",
            "osp.web.server.securePort": "9443",
            "osp.web.authServiceName": "oidc",
            "pdr.can.0.transport": "loopback",
        })
        self.assertEqual(errors, ["production prohibits CAN loopback transport"])

    def test_production_rejects_gnss_loopback(self):
        errors = MODULE.validate({
            "security.profile": "production",
            "osp.web.server.securePort": "9443",
            "osp.web.authServiceName": "oidc",
            "pdr.gnss.0.transport": "loopback",
        })
        self.assertEqual(errors, ["production prohibits GNSS loopback transport"])

    def test_production_rejects_xbee_loopback(self):
        errors = MODULE.validate({
            "security.profile": "production",
            "osp.web.server.securePort": "9443",
            "osp.web.authServiceName": "oidc",
            "pdr.xbee.0.transport": "loopback",
        })
        self.assertEqual(errors, ["production prohibits XBee loopback transport"])


if __name__ == "__main__":
    unittest.main()
